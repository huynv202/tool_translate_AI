from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field

from .config import Settings
from .dialogue import DialogueLine, apply_script, dialogue_script, load_dialogue, save_dialogue
from .errors import PipelineError
from .local_stt import normalize_model_name
from .pipeline import PipelineOptions, prepare, prepare_render_assets, render_prepared
from .video import RenderOptions

LOG = logging.getLogger(__name__)
ASSETS = Path(__file__).parent / "web_assets"
JOBS_ROOT = Path("work/web-jobs").resolve()
UPLOADS_ROOT = Path("work/uploads").resolve()
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
STAGES = [
    "Lay video nguon",
    "Trich xuat audio",
    "Nhan dang tieng Trung",
    "Dich va bien tap AI",
    "Tao giong doc",
    "Tao phu de",
    "Render video",
]


@dataclass
class Job:
    id: str
    status: str = "queued"
    active_stage: str = "Dang cho"
    phase: str = "prepare"
    stages: dict[str, str] = field(default_factory=lambda: dict.fromkeys(STAGES, "pending"))
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    output: Path | None = None
    work_dir: Path | None = None
    options: PipelineOptions | None = None
    settings: Settings | None = None
    revision: int = 0
    logs: list[dict[str, str]] = field(default_factory=list)

    def add_log(self, message: str, level: str = "info", stage: str | None = None) -> None:
        self.logs.append(
            {
                "time": datetime.now(UTC).isoformat(),
                "level": level,
                "stage": stage or self.active_stage,
                "message": message,
            }
        )
        if len(self.logs) > 1000:
            del self.logs[:-1000]

    def public(self) -> dict[str, object]:
        prepare_stages = STAGES[:6]
        if self.status == "ready":
            progress = 100
        elif self.phase == "prepare":
            completed = sum(self.stages[name] == "completed" for name in prepare_stages)
            progress = round(completed / len(prepare_stages) * 100)
        else:
            completed = sum(value == "completed" for value in self.stages.values())
            progress = round(completed / len(STAGES) * 100)
        artifacts: dict[str, str] = {}
        if self.work_dir:
            for key, filename in (
                ("transcript", "transcript.txt"),
                ("script", "script.translated.txt"),
            ):
                path = self.work_dir / filename
                if path.is_file():
                    artifacts[key] = path.read_text(encoding="utf-8")
            dialogue_path = self.work_dir / "dialogue.translated.json"
            if dialogue_path.is_file():
                artifacts["dialogue"] = [asdict(line) for line in load_dialogue(dialogue_path)]
        return {
            "id": self.id,
            "status": self.status,
            "phase": self.phase,
            "active_stage": self.active_stage,
            "stages": self.stages,
            "progress": progress,
            "error": self.error,
            "created_at": self.created_at,
            "artifacts": artifacts,
            "logs": self.logs,
            "editorial": ({
                "content_mode": self.options.content_mode,
                "editorial_thesis": self.options.editorial_thesis,
                "vietnam_angle": self.options.vietnam_angle,
                "research_sources": list(self.options.research_sources),
            } if self.options else {}),
            "preview_url": (
                f"/api/jobs/{self.id}/preview?v={self.revision}"
                if self.work_dir and (self.work_dir / "source.mp4").is_file()
                else None
            ),
            "video_url": (
                f"/api/jobs/{self.id}/video?v={self.revision}"
                if self.status == "completed" and self.output and self.output.exists()
                else None
            ),
            "voice_url": (
                f"/api/jobs/{self.id}/voice?v={self.revision}"
                if self.work_dir and (self.work_dir / "voiceover.mp3").is_file()
                else None
            ),
            "capcut_assets": ({
                "video": f"/api/jobs/{self.id}/assets/video?v={self.revision}",
                "voice": f"/api/jobs/{self.id}/assets/voice?v={self.revision}",
                "subtitles": f"/api/jobs/{self.id}/assets/subtitles?v={self.revision}",
            } if self.work_dir
            and (self.work_dir / "source.mp4").is_file()
            and (self.work_dir / "voiceover.mp3").is_file()
            and (self.work_dir / "voiceover.srt").is_file() else {}),
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex[:12])
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Khong tim thay job")
        return job


store = JobStore()
app = FastAPI(title="Viet Transform Studio", version="0.2.0")
app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")


class RouterProbe(BaseModel):
    api_key: str
    base_url: str


class RouterModelProbe(RouterProbe):
    model: str


class EditorialBriefRequest(RouterModelProbe):
    topic: str
    description: str = ""


class StoryboardRequest(RouterModelProbe):
    context: str
    manual_narration: str = ""
    duration_seconds: int = 60
    tone: str = "Binh tinh, dien anh"
    visual_style: str = "Dien anh chan thuc"
    aspect_ratio: str = "9:16"
    director_prompt: str = ""
    asset_mode: str = "hybrid"
    image_names: list[str] = Field(default_factory=list)


class UploadInit(BaseModel):
    filename: str
    size: int
    content_type: str = "video/mp4"


class VoicePreview(BaseModel):
    engine: str
    voice: str
    speaker: int | None = None


class EditorSettings(BaseModel):
    font_name: str = "Montserrat"
    subtitle_font_size: int = 11
    subtitle_margin: int = 110
    subtitle_color: str = "white"
    caption_opacity: float = 0.48
    cover_source_subtitles: bool = True
    music_volume: float = 0.12
    logo_position: str = "top-right"
    logo_width: float = 0.16
    logo_opacity: float = 0.9
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    hue: float = 0.0
    blur: float = 0.0
    vignette: float = 0.0
    voice_volume: float = 1.0
    audio_fade_in: float = 0.0
    audio_fade_out: float = 0.0


class TimelineCue(BaseModel):
    id: int
    start: float
    end: float
    translation: str
    voice: str | None = None
    speaker: int | None = None


class TimelineEdit(BaseModel):
    cues: list[TimelineCue]


class CueUpdate(BaseModel):
    start: float
    end: float
    translation: str
    voice: str | None = None
    speaker: int | None = None


class EditorRenderRequest(EditorSettings):
    cues: list[TimelineCue]


class YouTubeReadinessAnswers(BaseModel):
    rights_basis: str = "unknown"
    evidence_saved: bool = False
    original_commentary: bool = False
    multiple_sources: bool = False
    fact_checked: bool = False
    synthetic_disclosure_reviewed: bool = False
    advertiser_friendly_reviewed: bool = False
    thumbnail_accurate: bool = False
    metadata_ready: bool = False
    end_screen_ready: bool = False


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(ASSETS / "home.html")


@app.get("/translate", response_class=HTMLResponse)
def translate_studio() -> FileResponse:
    return FileResponse(ASSETS / "index.html")


@app.get("/storytelling", response_class=HTMLResponse)
def storytelling_studio() -> FileResponse:
    return FileResponse(ASSETS / "storytelling.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/voices")
def voices() -> dict[str, object]:
    return {"voices": [
        {"id": "xtts-auto", "engine": "quality", "name": "XTTS v2 Auto", "description": "Uu tien GPU, tu fallback Piper"},
        {"id": "vi-piper-vais1000-medium", "engine": "piper", "name": "Vân Anh", "description": "Nữ rõ chữ · ổn định cho video dài"},
        {"id": "vi-piper-25hours-low", "engine": "piper", "name": "Minh Châu", "description": "Nữ nhẹ, kể chuyện tự nhiên"},
        {"id": "vi-piper-vivos-x-low", "engine": "piper", "speaker": 12, "name": "Hải Nam", "description": "Nam ấm · local, không giới hạn độ dài"},
        {"id": "vi-VN-HoaiMyNeural", "engine": "edge", "name": "Hoài My", "description": "Nữ tự nhiên · cần Internet"},
        {"id": "vi-VN-NamMinhNeural", "engine": "edge", "name": "Nam Minh", "description": "Nam rõ, khỏe · cần Internet"},
    ]}


@app.post("/api/voices/preview")
def preview_voice(preview: VoicePreview) -> FileResponse:
    preview_dir = Path("work/voice-previews").resolve()
    preview_dir.mkdir(parents=True, exist_ok=True)
    safe_id = preview.voice.replace("/", "-")
    output = preview_dir / f"{preview.engine}-{safe_id}-{preview.speaker or 0}.mp3"
    settings = replace(
        Settings.load(),
        tts_engine=preview.engine,
        tts_voice=preview.voice,
        tts_speaker=preview.speaker,
    )
    from .speech import synthesize, synthesize_piper, synthesize_xtts
    if not output.exists():
        text = "Xin chào, đây là giọng đọc mẫu cho video của bạn."
        if preview.engine == "piper":
            synthesize_piper(text, output, Path("work/models/piper").resolve(), preview.voice, preview.speaker)
        elif preview.engine == "quality":
            try:
                synthesize_xtts(text, output, None)
            except PipelineError:
                synthesize_piper(text, output, Path("work/models/piper").resolve())
        elif preview.engine == "edge":
            synthesize(text, output, settings, retries=2)
        else:
            raise HTTPException(status_code=422, detail="TTS engine khong hop le")
    return FileResponse(output, media_type="audio/mpeg")


def _upload_dir(upload_id: str) -> Path:
    if len(upload_id) != 32 or any(char not in "0123456789abcdef" for char in upload_id):
        raise HTTPException(status_code=404, detail="Upload ID khong hop le")
    path = UPLOADS_ROOT / upload_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Khong tim thay upload")
    return path


@app.post("/api/uploads")
def init_upload(payload: UploadInit) -> dict[str, object]:
    if payload.size <= 0 or payload.size > 20 * 1024**3:
        raise HTTPException(status_code=422, detail="Kich thuoc video khong hop le")
    required = payload.size * 3 + 2 * 1024**3
    free = shutil.disk_usage(UPLOADS_ROOT.parent).free
    if free < required:
        raise HTTPException(status_code=507, detail=f"Khong du dung luong. Can toi thieu {required / 1024**3:.1f} GB trong")
    upload_id = uuid.uuid4().hex
    upload_dir = UPLOADS_ROOT / upload_id
    (upload_dir / "parts").mkdir(parents=True, exist_ok=True)
    suffix = Path(payload.filename).suffix.lower() or ".mp4"
    manifest = {
        "filename": Path(payload.filename).name,
        "size": payload.size,
        "content_type": payload.content_type,
        "suffix": suffix,
        "chunk_size": UPLOAD_CHUNK_SIZE,
    }
    (upload_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {"upload_id": upload_id, "chunk_size": UPLOAD_CHUNK_SIZE}


@app.put("/api/uploads/{upload_id}/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request) -> dict[str, int]:
    upload_dir = _upload_dir(upload_id)
    manifest = json.loads((upload_dir / "manifest.json").read_text(encoding="utf-8"))
    total_chunks = (manifest["size"] + manifest["chunk_size"] - 1) // manifest["chunk_size"]
    if index < 0 or index >= total_chunks:
        raise HTTPException(status_code=416, detail="Chi so chunk khong hop le")
    body = await request.body()
    expected = min(manifest["chunk_size"], manifest["size"] - index * manifest["chunk_size"])
    if len(body) != expected:
        raise HTTPException(status_code=400, detail="Chunk khong du byte")
    temporary = upload_dir / "parts" / f"{index:06d}.part.tmp"
    final = upload_dir / "parts" / f"{index:06d}.part"
    temporary.write_bytes(body)
    os.replace(temporary, final)
    return {"index": index, "size": len(body)}


@app.post("/api/uploads/{upload_id}/complete")
def complete_upload(upload_id: str) -> dict[str, object]:
    upload_dir = _upload_dir(upload_id)
    manifest = json.loads((upload_dir / "manifest.json").read_text(encoding="utf-8"))
    total = (manifest["size"] + manifest["chunk_size"] - 1) // manifest["chunk_size"]
    parts = [upload_dir / "parts" / f"{index:06d}.part" for index in range(total)]
    if any(not part.is_file() for part in parts):
        raise HTTPException(status_code=409, detail="Upload chua du cac chunk")
    source = upload_dir / f"source{manifest['suffix']}"
    with source.open("wb") as target:
        for part in parts:
            with part.open("rb") as stream:
                shutil.copyfileobj(stream, target, length=1024 * 1024)
    if source.stat().st_size != manifest["size"]:
        source.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Kich thuoc file sau ghep khong khop")
    shutil.rmtree(upload_dir / "parts")
    return {"upload_id": upload_id, "size": source.stat().st_size}


@app.post("/api/router/models")
def router_models(probe: RouterProbe) -> dict[str, object]:
    if not probe.base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Base URL khong hop le")
    try:
        response = OpenAI(api_key=probe.api_key, base_url=probe.base_url.rstrip("/")).models.list()
        models = [
            {"id": model.id, "provider": getattr(model, "owned_by", "unknown")}
            for model in response.data
        ]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Khong ket noi duoc 9Router: {exc}") from exc
    if not models:
        raise HTTPException(status_code=404, detail="9Router khong tra ve model nao")
    return {"models": models}


@app.post("/api/router/test-model")
def test_router_model(probe: RouterModelProbe) -> dict[str, str]:
    try:
        response = OpenAI(
            api_key=probe.api_key, base_url=probe.base_url.rstrip("/")
        ).chat.completions.create(
            model=probe.model,
            messages=[{"role": "user", "content": "Reply with OK only."}],
            max_tokens=8,
            temperature=0,
        )
        reply = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model khong dung duoc: {exc}") from exc
    return {"status": "ok", "reply": reply}


@app.post("/api/editorial/brief")
def generate_editorial_brief(request: EditorialBriefRequest) -> dict[str, object]:
    topic = request.topic.strip()
    if not 5 <= len(topic) <= 300:
        raise HTTPException(status_code=422, detail="Chu de can tu 5 den 300 ky tu")
    prompt = """Bạn là biên tập viên trưởng của kênh YouTube Việt Nam 'Hồ sơ Giải mã'.
Từ chủ đề và mô tả người dùng cung cấp, hãy xây dựng một brief nội dung có giá trị chuyển hóa.
Video nguồn chỉ là tư liệu minh họa, không được đề xuất dịch hoặc kể lại nguyên bản.
Chỉ trả về JSON hợp lệ theo schema:
{"thesis":"luận điểm chính","vietnam_angle":"góc nhìn cụ thể cho người Việt",
"hook":"hook mở đầu","structure":["Đặt vấn đề","Bằng chứng","Giải thích","Góc nhìn Việt Nam","Kết luận mở"],
"research_queries":["câu hỏi nghiên cứu 1","câu hỏi nghiên cứu 2","câu hỏi nghiên cứu 3"]}.
Không bịa URL, số liệu, nguồn hoặc sự kiện."""
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"Chủ đề: {topic}\nMô tả: {request.description.strip()}"},
    ]
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = OpenAI(
                api_key=request.api_key, base_url=request.base_url.rstrip("/")
            ).chat.completions.create(
                model=request.model,
                messages=messages,
                temperature=0.45 if attempt == 0 else 0,
            )
            content = (response.choices[0].message.content or "").strip()
            cleaned = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            start, end = cleaned.find("{"), cleaned.rfind("}")
            payload = json.loads(cleaned[start:end + 1])
            required = {"thesis", "vietnam_angle", "hook", "structure", "research_queries"}
            if not required.issubset(payload) or not isinstance(payload["structure"], list):
                raise ValueError("AI tra ve brief thieu truong")
            return payload
        except Exception as exc:  # noqa: BLE001 - retry router and malformed model responses
            last_error = exc
            messages.append({
                "role": "user",
                "content": "Phản hồi chưa đúng JSON. Hãy trả lại duy nhất JSON đúng schema, không markdown.",
            })
    raise HTTPException(status_code=502, detail=f"Khong tao duoc brief bien tap: {last_error}")


@app.post("/api/storytelling/storyboard")
def generate_storyboard(request: StoryboardRequest) -> dict[str, object]:
    if not request.context.strip() or len(request.context) > 20_000:
        raise HTTPException(status_code=422, detail="Cot truyen phai co tu 1 den 20.000 ky tu")
    if request.duration_seconds not in {60, 90, 180, 300, 600}:
        raise HTTPException(status_code=422, detail="Do dai storytelling khong hop le")
    if request.aspect_ratio not in {"9:16", "16:9", "1:1"}:
        raise HTTPException(status_code=422, detail="Ty le storytelling khong hop le")
    if request.asset_mode not in {"hybrid", "generated", "uploaded"}:
        raise HTTPException(status_code=422, detail="Che do anh storytelling khong hop le")
    if len(request.image_names) > 50:
        raise HTTPException(status_code=422, detail="Moi project chi nhan toi da 50 anh")

    supplied_images = [Path(name).name for name in request.image_names]
    payload = {
        "story_context": request.context.strip(),
        "manual_narration": request.manual_narration.strip() or None,
        "target_duration_seconds": request.duration_seconds,
        "target_scene_count": max(4, min(24, round(request.duration_seconds / 12))),
        "tone": request.tone,
        "visual_style": request.visual_style,
        "aspect_ratio": request.aspect_ratio,
        "director_prompt": request.director_prompt.strip(),
        "asset_mode": request.asset_mode,
        "uploaded_images": supplied_images,
    }
    system_prompt = """Bạn là biên kịch kiêm đạo diễn hình ảnh cho video storytelling.
Tự viết lời kể tiếng Việt nếu manual_narration rỗng, rồi chia thành scene theo nhịp đọc. Tổng lời
kể phải phù hợp target_duration_seconds. Mỗi scene có một đoạn narration và một prompt ảnh độc lập,
nhưng phải tuân theo visual_bible để nhân vật và phong cách nhất quán. Với hybrid, ưu tiên ảnh upload
phù hợp; với generated, mọi scene cần sinh ảnh; với uploaded, mọi scene phải dùng ảnh được cung cấp.
Prompt ảnh không chứa chữ, logo hay watermark; nêu bố cục theo aspect_ratio và chừa vùng an toàn cho
subtitle. Chỉ trả về một JSON object hợp lệ, không markdown:
{"title":"...","hook":"...","visual_bible":{"characters":"...","world":"...","palette":"...","style":"..."},"scenes":[{"id":1,"narration":"...","duration_seconds":8,"uploaded_image":null,"image_prompt":"...","composition":"center","transition":"fade"}]}"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = OpenAI(
                api_key=request.api_key, base_url=request.base_url.rstrip("/")
            ).chat.completions.create(
                model=request.model,
                messages=messages,
                temperature=0.55 if attempt == 0 else 0,
            )
            content = (response.choices[0].message.content or "").strip()
            return _parse_storyboard(content, request, supplied_images)
        except Exception as exc:  # noqa: BLE001 - retry router and malformed JSON
            last_error = exc
            messages.append({
                "role": "user",
                "content": "Phản hồi chưa đúng schema. Trả lại duy nhất JSON storyboard hợp lệ.",
            })
    raise HTTPException(status_code=502, detail=f"Khong tao duoc storyboard: {last_error}")


def _parse_storyboard(
    content: str, request: StoryboardRequest, supplied_images: list[str]
) -> dict[str, object]:
    cleaned = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    data = json.loads(cleaned[start:end + 1])
    scenes = data["scenes"]
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 30:
        raise ValueError("Storyboard khong co danh sach scene hop le")
    if not isinstance(data.get("visual_bible"), dict):
        raise TypeError("Storyboard thieu visual bible")
    normalized: list[dict[str, object]] = []
    for index, scene in enumerate(scenes, start=1):
        narration = str(scene.get("narration", "")).strip()
        if not narration:
            raise ValueError(f"Scene {index} khong co loi ke")
        image_name = scene.get("uploaded_image")
        if image_name not in supplied_images:
            image_name = None
        needs_generation = request.asset_mode == "generated" or (
            request.asset_mode == "hybrid" and image_name is None
        )
        if request.asset_mode == "uploaded" and image_name is None:
            raise ValueError(f"Scene {index} chua duoc gan anh upload")
        normalized.append({
            "id": index,
            "narration": narration,
            "duration_seconds": max(2.0, min(30.0, float(scene.get("duration_seconds", 8)))),
            "uploaded_image": image_name,
            "needs_generation": needs_generation,
            "image_prompt": str(scene.get("image_prompt", "")).strip(),
            "composition": str(scene.get("composition", "center")),
            "transition": str(scene.get("transition", "fade")),
        })
    return {
        "title": str(data.get("title", "Storytelling project")).strip(),
        "hook": str(data.get("hook", "")).strip(),
        "visual_bible": data["visual_bible"],
        "full_narration": " ".join(str(scene["narration"]) for scene in normalized),
        "scenes": normalized,
    }


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    return store.get(job_id).public()


@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str) -> FileResponse:
    job = store.get(job_id)
    if not job.output or not job.output.is_file():
        raise HTTPException(status_code=404, detail="Video chua san sang")
    return FileResponse(job.output, media_type="video/mp4", filename=f"viet-transform-{job.id}.mp4")


@app.get("/api/jobs/{job_id}/preview")
def get_preview(job_id: str) -> FileResponse:
    job = store.get(job_id)
    preview = job.work_dir / "source.mp4" if job.work_dir else None
    if not preview or not preview.is_file():
        raise HTTPException(status_code=404, detail="Ban nhap chua san sang")
    return FileResponse(preview, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/voice")
def get_voice_preview(job_id: str) -> FileResponse:
    job = store.get(job_id)
    voice = job.work_dir / "voiceover.mp3" if job.work_dir else None
    if not voice or not voice.is_file():
        raise HTTPException(status_code=404, detail="Giong doc preview chua san sang")
    return FileResponse(voice, media_type="audio/mpeg")


@app.get("/api/jobs/{job_id}/assets/video")
def download_project_video(job_id: str) -> FileResponse:
    job = store.get(job_id)
    video = job.work_dir / "source.mp4" if job.work_dir else None
    if not video or not video.is_file():
        raise HTTPException(status_code=404, detail="Video project chua san sang")
    return FileResponse(video, media_type="video/mp4", filename=f"{job.id}-video.mp4")


@app.get("/api/jobs/{job_id}/assets/voice")
def download_project_voice(job_id: str) -> FileResponse:
    job = store.get(job_id)
    voice = job.work_dir / "voiceover.mp3" if job.work_dir else None
    if not voice or not voice.is_file():
        raise HTTPException(status_code=404, detail="Voice project chua san sang")
    return FileResponse(voice, media_type="audio/mpeg", filename=f"{job.id}-voice.mp3")


@app.get("/api/jobs/{job_id}/assets/subtitles")
def download_project_subtitles(job_id: str) -> FileResponse:
    job = store.get(job_id)
    subtitles = job.work_dir / "voiceover.srt" if job.work_dir else None
    if not subtitles or not subtitles.is_file():
        raise HTTPException(status_code=404, detail="Subtitle project chua san sang")
    return FileResponse(
        subtitles,
        media_type="application/x-subrip; charset=utf-8",
        filename=f"{job.id}-subtitles.srt",
    )


@app.post("/api/jobs/{job_id}/youtube-readiness")
def youtube_readiness(job_id: str, answers: YouTubeReadinessAnswers) -> dict[str, object]:
    job = store.get(job_id)
    if not job.work_dir:
        raise HTTPException(status_code=409, detail="Project chua co artifact de danh gia")
    dialogue_path = job.work_dir / "dialogue.translated.json"
    lines = load_dialogue(dialogue_path) if dialogue_path.is_file() else []
    checks: list[dict[str, object]] = []

    def add(gate: str, label: str, passed: bool, points: int, action: str, blocker: bool = False):
        checks.append({
            "gate": gate,
            "label": label,
            "status": "pass" if passed else ("blocker" if blocker else "warning"),
            "points": points if passed else 0,
            "max_points": points,
            "action": "Da dat" if passed else action,
        })

    allowed_rights = {"owned", "licensed", "creative-commons", "public-domain", "stock"}
    rights_ok = answers.rights_basis in allowed_rights
    add("rights", "Co co so quyen su dung tu lieu", rights_ok, 20,
        "Chon tu lieu tu so huu, duoc cap phep, CC phu hop, public domain hoac stock.", True)
    add("rights", "Da luu bang chung quyen su dung", answers.evidence_saved, 10,
        "Luu license, hoa don, URL, anh chup dieu khoan hoac van ban cho phep.", True)
    add("transform", "Co loi binh, phan tich hoac goc nhin moi", answers.original_commentary, 15,
        "Bo sung nhan dinh va gia tri bien tap rieng; dich va long tieng don thuan la chua du.", True)
    source_count = len(job.options.research_sources) if job.options else 0
    add("transform", "Nghien cuu tu nhieu nguon", answers.multiple_sources or source_count >= 2, 5,
        "Doi chieu them nguon doc lap thay vi phu thuoc mot video goc.")
    creator_mode = bool(job.options and job.options.content_mode == "creator-analysis")
    add("transform", "Dung Creator Analysis thay vi dich sat cue", creator_mode, 5,
        "Chuyen project sang Creator Analysis va viet theo luan diem cua kenh.")
    add("editorial", "Da kiem chung du kien va ten rieng", answers.fact_checked, 8,
        "Kiem tra lai so lieu, ten nguoi, dia danh va trich dan.")
    has_hook = bool(lines and lines[0].start <= 3 and len(lines[0].translation.split()) >= 3)
    add("editorial", "Co hook ro trong 3 giay dau", has_hook, 5,
        "Viet lai cue dau de neu mau thuan, loi hua hoac ly do nen xem tiep.")
    readable_cues = bool(lines) and all(0.4 <= line.duration <= 8 for line in lines)
    add("editorial", "Cue co nhip doc de theo doi", readable_cues, 7,
        "Tach cac cue dai hon 8 giay va sua cue qua ngan.")
    add("technical", "Project co cue va video preview", bool(lines) and bool(job.public()["preview_url"]), 8,
        "Hoan tat nhan dang va tao cue truoc khi danh gia.", True)
    add("technical", "Da xem xet khai bao noi dung AI", answers.synthetic_disclosure_reviewed, 4,
        "Danh gia xem video co noi dung altered/synthetic can khai bao hay khong.")
    add("technical", "Da kiem tra than thien nha quang cao", answers.advertiser_friendly_reviewed, 3,
        "Ra soat ngon tu, bao luc, tinh duc, chat kich thich va chu de nhay cam.")
    add("publish", "Thumbnail mo ta dung noi dung", answers.thumbnail_accurate, 4,
        "Tranh thumbnail gay hieu sai hoac hua dieu video khong cung cap.")
    add("publish", "Tieu de va metadata da san sang", answers.metadata_ready, 4,
        "Hoan thien title, description, credit/license va playlist.")
    add("publish", "Da co end screen hoac cau noi video tiep", answers.end_screen_ready, 2,
        "Chon video tiep theo va dat CTA phu hop.")

    score = sum(int(item["points"]) for item in checks)
    blockers = [item for item in checks if item["status"] == "blocker"]
    if blockers:
        verdict = "blocked"
        verdict_label = "Chua nen xuat ban"
    elif score >= 85:
        verdict = "ready"
        verdict_label = "San sang de review cuoi"
    elif score >= 65:
        verdict = "review"
        verdict_label = "Can hoan thien them"
    else:
        verdict = "risk"
        verdict_label = "Rui ro cao"
    return {
        "score": score,
        "verdict": verdict,
        "verdict_label": verdict_label,
        "checks": checks,
        "blockers": blockers,
        "disclaimer": "Diem nay la cong cu tu kiem tra, khong dam bao YPP, fair use hoac tranh Content ID.",
        "sources": [
            {"label": "YouTube channel monetization policies", "url": "https://support.google.com/youtube/answer/1311392"},
            {"label": "Fair use on YouTube", "url": "https://support.google.com/youtube/answer/9783148"},
            {"label": "How Content ID works", "url": "https://support.google.com/youtube/answer/2797370"},
            {"label": "Disclosing use of GenAI content", "url": "https://support.google.com/youtube/answer/14328491"},
        ],
    }


@app.post("/api/jobs/{job_id}/regenerate", status_code=202)
def regenerate_job(
    job_id: str,
    background: BackgroundTasks,
    script: str = Form(...),
) -> dict[str, str]:
    job = store.get(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Job dang xu ly")
    if not job.work_dir or not job.options or not job.settings:
        raise HTTPException(status_code=409, detail="Job khong con du lieu de tao lai")
    word_count = len(script.split())
    if not 10 <= word_count <= 3000:
        raise HTTPException(
            status_code=422,
            detail=f"Kich ban hien co {word_count} tu; can nam trong khoang 10-3000 tu",
        )
    (job.work_dir / "script.translated.txt").write_text(script.strip(), encoding="utf-8")
    dialogue_path = job.work_dir / "dialogue.translated.json"
    if dialogue_path.exists():
        try:
            lines = apply_script(load_dialogue(dialogue_path), script)
            save_dialogue(lines, dialogue_path)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    for filename in ("voiceover.mp3", "voiceover.srt"):
        path = job.work_dir / filename
        if path.exists():
            path.unlink()
    if job.output and job.output.exists():
        job.output.unlink()
    for stage in ("Tao giong doc", "Tao phu de", "Render video"):
        job.stages[stage] = "pending"
    job.error = None
    background.add_task(_run_render, job, job.options, job.settings)
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, background: BackgroundTasks) -> dict[str, str]:
    job = store.get(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Job dang xu ly")
    if not job.options or not job.settings:
        raise HTTPException(status_code=409, detail="Job khong con du lieu de retry")
    job.error = None
    runner = _run_render if job.phase == "render" else _run_prepare
    background.add_task(runner, job, job.options, job.settings)
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/render", status_code=202)
def render_editor(
    job_id: str, editor: EditorRenderRequest, background: BackgroundTasks
) -> dict[str, str]:
    job = store.get(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Job dang xu ly")
    if not job.work_dir or not job.options or not job.settings:
        raise HTTPException(status_code=409, detail="Job khong con du lieu editor")
    if not editor.cues or len(editor.cues) > 5000:
        raise HTTPException(status_code=422, detail="Timeline phai co tu 1 den 5000 cue")
    if not 7 <= editor.subtitle_font_size <= 30 or not 20 <= editor.subtitle_margin <= 400:
        raise HTTPException(status_code=422, detail="Thong so subtitle khong hop le")
    if not 0 <= editor.music_volume <= 0.5 or not 0 <= editor.caption_opacity <= 0.9:
        raise HTTPException(status_code=422, detail="Thong so am thanh/caption khong hop le")
    if not -1 <= editor.brightness <= 1 or not 0.5 <= editor.contrast <= 2:
        raise HTTPException(status_code=422, detail="Thong so anh khong hop le")
    if not 0 <= editor.saturation <= 3 or not 0 <= editor.voice_volume <= 2:
        raise HTTPException(status_code=422, detail="Thong so mau/voice khong hop le")
    if not -180 <= editor.hue <= 180 or not 0 <= editor.blur <= 10 or not 0 <= editor.vignette <= 1:
        raise HTTPException(status_code=422, detail="Thong so hieu ung khong hop le")
    if not 0 <= editor.audio_fade_in <= 5 or not 0 <= editor.audio_fade_out <= 5:
        raise HTTPException(status_code=422, detail="Thong so fade audio khong hop le")

    dialogue_path = job.work_dir / "dialogue.translated.json"
    source_by_id = {line.id: line.source for line in load_dialogue(dialogue_path)}
    lines: list[DialogueLine] = []
    previous_end = 0.0
    for index, cue in enumerate(editor.cues, start=1):
        text = cue.translation.strip()
        if not text:
            continue
        if cue.start < 0 or cue.end <= cue.start:
            raise HTTPException(status_code=422, detail=f"Cue {index} co thoi gian khong hop le")
        if cue.start < previous_end:
            raise HTTPException(status_code=422, detail=f"Cue {index} bi chong len cue truoc")
        lines.append(DialogueLine(
            id=len(lines) + 1, start=cue.start, end=cue.end,
            source=source_by_id.get(cue.id, ""), translation=text,
            voice=cue.voice, speaker=cue.speaker,
        ))
        previous_end = cue.end
    if not lines:
        raise HTTPException(status_code=422, detail="Timeline khong co cue nao co noi dung")
    save_dialogue(lines, dialogue_path)
    (job.work_dir / "script.translated.txt").write_text(dialogue_script(lines), encoding="utf-8")
    for filename in ("voiceover.mp3", "voiceover.srt", "voice-filter.txt"):
        (job.work_dir / filename).unlink(missing_ok=True)

    job.options = replace(job.options, render=replace(
        job.options.render,
        subtitle_font_size=editor.subtitle_font_size,
        subtitle_margin=editor.subtitle_margin,
        subtitle_color=editor.subtitle_color,
        caption_opacity=editor.caption_opacity,
        cover_source_subtitles=editor.cover_source_subtitles,
        music_volume=editor.music_volume,
        logo_position=editor.logo_position,
        logo_width=editor.logo_width,
        logo_opacity=editor.logo_opacity,
        brightness=editor.brightness,
        contrast=editor.contrast,
        saturation=editor.saturation,
        hue=editor.hue,
        blur=editor.blur,
        vignette=editor.vignette,
        voice_volume=editor.voice_volume,
        audio_fade_in=editor.audio_fade_in,
        audio_fade_out=editor.audio_fade_out,
    ))
    job.settings = replace(job.settings, font_name=editor.font_name)
    if job.output:
        job.output.unlink(missing_ok=True)
    for stage in ("Tao giong doc", "Tao phu de", "Render video"):
        job.stages[stage] = "pending"
    job.error = None
    job.add_log("Da khoa timeline editor; bat dau render video lien mach.")
    background.add_task(_run_render, job, job.options, job.settings)
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/cues/{cue_id}", status_code=202)
def update_single_cue(
    job_id: str, cue_id: int, cue: CueUpdate, background: BackgroundTasks
) -> dict[str, str]:
    job = store.get(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Project dang xu ly mot cue khac")
    if not job.work_dir or not job.options or not job.settings:
        raise HTTPException(status_code=409, detail="Project khong con du lieu cue")
    dialogue_path = job.work_dir / "dialogue.translated.json"
    lines = load_dialogue(dialogue_path)
    index = next((i for i, line in enumerate(lines) if line.id == cue_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Khong tim thay cue")
    text = cue.translation.strip()
    if not text or cue.start < 0 or cue.end <= cue.start:
        raise HTTPException(status_code=422, detail="Noi dung hoac thoi gian cue khong hop le")
    if index > 0 and cue.start < lines[index - 1].end:
        raise HTTPException(status_code=422, detail="Cue bi chong len cue truoc")
    if index + 1 < len(lines) and cue.end > lines[index + 1].start:
        raise HTTPException(status_code=422, detail="Cue bi chong len cue sau")
    lines[index] = replace(
        lines[index], start=cue.start, end=cue.end, translation=text,
        voice=cue.voice, speaker=cue.speaker,
    )
    save_dialogue(lines, dialogue_path)
    (job.work_dir / "script.translated.txt").write_text(dialogue_script(lines), encoding="utf-8")
    for filename in ("voiceover.mp3", "voiceover.srt"):
        (job.work_dir / filename).unlink(missing_ok=True)
    for stage in ("Tao giong doc", "Tao phu de"):
        job.stages[stage] = "pending"
    job.error = None
    job.add_log(f"Cue {cue_id} da thay doi; tao lai voice va subtitle cue nay.")
    background.add_task(_run_cue_update, job, job.options, job.settings, cue_id)
    return {"job_id": job.id, "cue_id": str(cue_id)}


@app.post("/api/jobs/{job_id}/timeline", status_code=202)
def update_timeline(
    job_id: str, editor: TimelineEdit, background: BackgroundTasks
) -> dict[str, str]:
    job = store.get(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Job dang xu ly")
    if not job.work_dir or not job.options or not job.settings:
        raise HTTPException(status_code=409, detail="Job khong con du lieu timeline")
    if not editor.cues or len(editor.cues) > 5000:
        raise HTTPException(status_code=422, detail="Timeline phai co tu 1 den 5000 cue")
    source_path = job.work_dir / "dialogue.translated.json"
    source_by_id = {line.id: line.source for line in load_dialogue(source_path)}
    lines: list[DialogueLine] = []
    previous_end = 0.0
    for index, cue in enumerate(editor.cues, start=1):
        text = cue.translation.strip()
        if not text:
            continue
        if cue.start < 0 or cue.end <= cue.start:
            raise HTTPException(
                status_code=422,
                detail=f"Timeline cue {index} co thoi gian khong hop le",
            )
        if cue.start < previous_end:
            raise HTTPException(status_code=422, detail=f"Timeline cue {index} bi chong lan")
        lines.append(
            DialogueLine(
                id=len(lines) + 1,
                start=cue.start,
                end=cue.end,
                source=source_by_id.get(cue.id, ""),
                translation=text,
                voice=cue.voice,
                speaker=cue.speaker,
            )
        )
        previous_end = cue.end
    if not lines:
        raise HTTPException(status_code=422, detail="Timeline khong co cue nao co noi dung")
    save_dialogue(lines, source_path)
    (job.work_dir / "script.translated.txt").write_text(
        dialogue_script(lines), encoding="utf-8"
    )
    for filename in ("voiceover.mp3", "voiceover.srt", "voice-filter.txt"):
        (job.work_dir / filename).unlink(missing_ok=True)
    if job.output:
        job.output.unlink(missing_ok=True)
    for stage in ("Tao giong doc", "Tao phu de", "Render video"):
        job.stages[stage] = "pending"
    job.error = None
    job.add_log(f"Da cap nhat timeline {len(lines)} cue; xep hang render lai.")
    job.add_log("Nguoi dung yeu cau retry pipeline.", "warning")
    job.add_log("Da cap nhat kich ban; xep hang tao lai voice, subtitle va video.")
    background.add_task(_run_render, job, job.options, job.settings)
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/render-settings", status_code=202)
def update_render_settings(
    job_id: str, editor: EditorSettings, background: BackgroundTasks
) -> dict[str, str]:
    job = store.get(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Job dang xu ly")
    if not job.options or not job.settings:
        raise HTTPException(status_code=409, detail="Job khong con du lieu editor")
    if not 7 <= editor.subtitle_font_size <= 30 or not 20 <= editor.subtitle_margin <= 400:
        raise HTTPException(status_code=422, detail="Thong so subtitle khong hop le")
    if not 0 <= editor.music_volume <= 0.5 or not 0 <= editor.caption_opacity <= 0.9:
        raise HTTPException(status_code=422, detail="Thong so am thanh/caption khong hop le")
    if not -1 <= editor.brightness <= 1 or not 0.5 <= editor.contrast <= 2:
        raise HTTPException(status_code=422, detail="Thong so anh khong hop le")
    if not 0 <= editor.saturation <= 3 or not 0 <= editor.voice_volume <= 2:
        raise HTTPException(status_code=422, detail="Thong so mau/voice khong hop le")
    if not -180 <= editor.hue <= 180 or not 0 <= editor.blur <= 10 or not 0 <= editor.vignette <= 1:
        raise HTTPException(status_code=422, detail="Thong so hieu ung khong hop le")
    if not 0 <= editor.audio_fade_in <= 5 or not 0 <= editor.audio_fade_out <= 5:
        raise HTTPException(status_code=422, detail="Thong so fade audio khong hop le")
    render_options = replace(
        job.options.render,
        subtitle_font_size=editor.subtitle_font_size,
        subtitle_margin=editor.subtitle_margin,
        subtitle_color=editor.subtitle_color,
        caption_opacity=editor.caption_opacity,
        cover_source_subtitles=editor.cover_source_subtitles,
        music_volume=editor.music_volume,
        logo_position=editor.logo_position,
        logo_width=editor.logo_width,
        logo_opacity=editor.logo_opacity,
        brightness=editor.brightness,
        contrast=editor.contrast,
        saturation=editor.saturation,
        hue=editor.hue,
        blur=editor.blur,
        vignette=editor.vignette,
        voice_volume=editor.voice_volume,
        audio_fade_in=editor.audio_fade_in,
        audio_fade_out=editor.audio_fade_out,
    )
    job.options = replace(job.options, render=render_options)
    job.settings = replace(job.settings, font_name=editor.font_name)
    if job.output and job.output.exists():
        job.output.unlink()
    job.stages["Render video"] = "pending"
    job.add_log("Da cap nhat hinh anh/am thanh; xep hang render video.")
    background.add_task(_run_render, job, job.options, job.settings)
    return {"job_id": job.id}


@app.post("/api/jobs", status_code=202)
async def create_job(
    background: BackgroundTasks,
    source_url: str = Form(""),
    upload_id: str = Form(""),
    video_file: Annotated[UploadFile | None, File()] = None,
    music_file: Annotated[UploadFile | None, File()] = None,
    logo_file: Annotated[UploadFile | None, File()] = None,
    voice_reference: Annotated[UploadFile | None, File()] = None,
    router_api_key: str = Form(...),
    router_base_url: str = Form(...),
    text_model: str = Form(...),
    script_model: str = Form(...),
    local_whisper_model: str = Form("small"),
    target_language: str = Form("Vietnamese"),
    content_mode: str = Form("localization"),
    editorial_thesis: str = Form(""),
    vietnam_angle: str = Form(""),
    research_sources: str = Form(""),
    tts_voice: str = Form("vi-VN-HoaiMyNeural"),
    tts_rate: str = Form("+0%"),
    tts_engine: str = Form("auto"),
    tts_speaker: int | None = Form(None),
    font_name: str = Form("Montserrat"),
    resolution: str = Form("1080x1920"),
    zoom: float = Form(1.06),
    trim_seconds: float = Form(0.0),
    music_volume: float = Form(0.12),
    flip: bool = Form(True),
    watermark_position: str = Form("top-left"),
    logo_position: str = Form("top-right"),
    logo_width: float = Form(0.16),
    logo_opacity: float = Form(0.9),
    cover_source_subtitles: bool = Form(True),
) -> dict[str, str]:
    has_video_upload = bool(video_file and video_file.filename)
    has_music_upload = bool(music_file and music_file.filename)
    has_logo_upload = bool(logo_file and logo_file.filename)
    has_voice_reference = bool(voice_reference and voice_reference.filename)
    if not source_url.strip() and not has_video_upload and not upload_id:
        raise HTTPException(status_code=422, detail="Hay upload video hoac nhap URL")
    if has_video_upload and not (video_file.content_type or "").startswith("video/"):
        raise HTTPException(status_code=422, detail="File upload khong phai video")
    if has_logo_upload and not (logo_file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=422, detail="Logo phai la file anh")
    if has_voice_reference and not (voice_reference.content_type or "").startswith("audio/"):
        raise HTTPException(status_code=422, detail="Mau giong phai la file audio")
    try:
        width, height = (int(value) for value in resolution.split("x", 1))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Do phan giai khong hop le") from exc
    if not 1.0 <= zoom <= 1.2 or not 0 <= music_volume <= 0.5 or not 0 <= trim_seconds <= 3:
        raise HTTPException(status_code=422, detail="Thong so render nam ngoai pham vi cho phep")
    if not 0.05 <= logo_width <= 0.4 or not 0.1 <= logo_opacity <= 1:
        raise HTTPException(status_code=422, detail="Thong so logo nam ngoai pham vi cho phep")
    if "gemini" not in text_model.lower():
        raise HTTPException(status_code=422, detail="Hay chon mot model Gemini de dich subtitle")
    if not any(name in script_model.lower() for name in ("gpt", "claude")):
        raise HTTPException(
            status_code=422, detail="Hay chon mot model GPT hoac Claude de viet kich ban"
        )
    if content_mode not in {"creator-analysis", "localization"}:
        raise HTTPException(status_code=422, detail="Che do noi dung khong hop le")
    sources = tuple(
        line.strip() for line in research_sources.splitlines() if line.strip()
    )
    if len(sources) > 20 or any(not source.startswith(("http://", "https://")) for source in sources):
        raise HTTPException(status_code=422, detail="Danh sach nguon nghien cuu khong hop le")
    job = store.create()
    job_dir = JOBS_ROOT / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    job.work_dir = job_dir / "artifacts"
    source = source_url.strip()
    if upload_id:
        upload_dir = _upload_dir(upload_id)
        sources = list(upload_dir.glob("source.*"))
        if len(sources) != 1:
            raise HTTPException(status_code=409, detail="Upload lon chua hoan tat")
        source = str(sources[0])
    if has_video_upload and video_file:
        suffix = Path(video_file.filename or "upload.mp4").suffix or ".mp4"
        upload_path = job_dir / f"upload{suffix}"
        with upload_path.open("wb") as target:
            shutil.copyfileobj(video_file.file, target)
        source = str(upload_path)
    music: Path | None = None
    if has_music_upload and music_file:
        suffix = Path(music_file.filename or "music.mp3").suffix or ".mp3"
        music = job_dir / f"music{suffix}"
        with music.open("wb") as target:
            shutil.copyfileobj(music_file.file, target)
        if music.stat().st_size == 0:
            music.unlink()
            music = None
    logo: Path | None = None
    if has_logo_upload and logo_file:
        suffix = Path(logo_file.filename or "logo.png").suffix or ".png"
        logo = job_dir / f"logo{suffix}"
        with logo.open("wb") as target:
            shutil.copyfileobj(logo_file.file, target)
    reference: Path | None = None
    if has_voice_reference and voice_reference:
        suffix = Path(voice_reference.filename or "voice.wav").suffix or ".wav"
        reference = job_dir / f"voice-reference{suffix}"
        with reference.open("wb") as target:
            shutil.copyfileobj(voice_reference.file, target)
        if reference.stat().st_size > 50 * 1024 * 1024:
            reference.unlink()
            raise HTTPException(status_code=413, detail="Mau giong khong duoc vuot qua 50 MB")

    resolved_tts_engine = "quality" if tts_voice.startswith("xtts-") else tts_engine
    settings = Settings(
        router_api_key=router_api_key,
        router_base_url=router_base_url.rstrip("/"),
        text_model=text_model,
        script_model=script_model,
        local_whisper_model=normalize_model_name(local_whisper_model),
        tts_voice=tts_voice,
        tts_rate=tts_rate,
        tts_engine=resolved_tts_engine,
        tts_speaker=tts_speaker,
        tts_reference=reference,
        music_dir=Path("music"),
        font_name=font_name,
    )
    options = PipelineOptions(
        source=source,
        output=job_dir / "final.mp4",
        work_dir=job.work_dir,
        music=music,
        logo=logo,
        target_language=target_language,
        content_mode=content_mode,
        editorial_thesis=editorial_thesis.strip(),
        vietnam_angle=vietnam_angle.strip(),
        research_sources=sources,
        render=RenderOptions(
            width=width,
            height=height,
            zoom=zoom,
            trim_seconds=trim_seconds,
            music_volume=music_volume,
            flip=flip,
            watermark_position=watermark_position,
            logo_position=logo_position,
            logo_width=logo_width,
            logo_opacity=logo_opacity,
            cover_source_subtitles=cover_source_subtitles,
        ),
    )
    job.options = options
    job.settings = settings
    job.add_log("Job da duoc tao va dang cho xu ly.")
    background.add_task(_run_job, job, options, settings)
    return {"job_id": job.id}


def _progress_for(job: Job):
    def progress(stage: str, status: str) -> None:
        job.active_stage = stage
        job.stages[stage] = status
        labels = {"running": "Bat dau", "completed": "Hoan thanh", "failed": "That bai"}
        job.add_log(f"{labels.get(status, status)}: {stage}", stage=stage)
    return progress


def _run_prepare(job: Job, options: PipelineOptions, settings: Settings) -> None:
    progress = _progress_for(job)

    job.phase = "prepare"
    job.status = "running"
    job.error = None
    job.add_log("Pipeline bat dau chay.")
    try:
        prepare(
            options,
            settings,
            progress,
            lambda message: job.add_log(message, stage=job.active_stage),
        )
        prepare_render_assets(
            options,
            settings,
            progress,
            lambda message: job.add_log(message, stage=job.active_stage),
        )
        job.status = "ready"
        job.active_stage = "San sang chinh sua"
        job.revision += 1
        job.add_log("Ban nhap va cac track da san sang trong editor.", stage="Editor")
    except Exception as exc:
        LOG.exception("Job %s failed", job.id)
        job.status = "failed"
        job.error = str(exc)
        job.add_log(str(exc), "error")
        if job.active_stage in job.stages:
            job.stages[job.active_stage] = "failed"


def _run_job(job: Job, options: PipelineOptions, settings: Settings) -> None:
    """Backward-compatible entry point for preparing a new editor project."""
    _run_prepare(job, options, settings)


def _run_cue_update(
    job: Job,
    options: PipelineOptions,
    settings: Settings,
    cue_id: int,
) -> None:
    progress = _progress_for(job)
    job.phase = "cue"
    job.status = "running"
    job.active_stage = "Tao giong doc"
    job.error = None
    job.add_log(f"Bat dau tao lai voice cho cue {cue_id}.", stage="Editor")
    try:
        prepare_render_assets(
            options,
            settings,
            progress,
            lambda message: job.add_log(message, stage=job.active_stage),
        )
        job.status = "ready"
        job.active_stage = "San sang chinh sua"
        job.revision += 1
        job.add_log(
            f"Cue {cue_id} da cap nhat; voice va subtitle da dong bo.",
            stage="Editor",
        )
    except Exception as exc:
        LOG.exception("Cue update %s for job %s failed", cue_id, job.id)
        job.status = "failed"
        job.error = str(exc)
        job.add_log(str(exc), "error", stage="Editor")
        if job.active_stage in job.stages:
            job.stages[job.active_stage] = "failed"


def _run_render(job: Job, options: PipelineOptions, settings: Settings) -> None:
    progress = _progress_for(job)
    job.phase = "render"
    job.status = "running"
    job.error = None
    job.add_log("Render master bat dau chay.")
    try:
        prepare(
            options,
            settings,
            progress,
            lambda message: job.add_log(message, stage=job.active_stage),
        )
        prepare_render_assets(
            options,
            settings,
            progress,
            lambda message: job.add_log(message, stage=job.active_stage),
        )
        job.output = render_prepared(options, settings, progress)
        job.status = "completed"
        job.active_stage = "Hoan tat"
        job.revision += 1
        job.add_log("Video lien mach da render hoan tat.", stage="Hoan tat")
    except Exception as exc:
        LOG.exception("Render job %s failed", job.id)
        job.status = "failed"
        job.error = str(exc)
        job.add_log(str(exc), "error")
        if job.active_stage in job.stages:
            job.stages[job.active_stage] = "failed"


def main() -> None:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    uvicorn.run("viet_transform.web:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
