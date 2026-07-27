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
from pydantic import BaseModel

from .config import Settings
from .dialogue import apply_script, load_dialogue, save_dialogue
from .errors import PipelineError
from .local_stt import normalize_model_name
from .pipeline import PipelineOptions, execute
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
    "Dich Gemini va bien tap GPT",
    "Tao giong doc",
    "Tao phu de",
    "Render video",
]


@dataclass
class Job:
    id: str
    status: str = "queued"
    active_stage: str = "Dang cho"
    stages: dict[str, str] = field(default_factory=lambda: dict.fromkeys(STAGES, "pending"))
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    output: Path | None = None
    work_dir: Path | None = None
    options: PipelineOptions | None = None
    settings: Settings | None = None
    revision: int = 0

    def public(self) -> dict[str, object]:
        progress = sum(value == "completed" for value in self.stages.values())
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
            "active_stage": self.active_stage,
            "stages": self.stages,
            "progress": round(progress / len(STAGES) * 100),
            "error": self.error,
            "created_at": self.created_at,
            "artifacts": artifacts,
            "video_url": (
                f"/api/jobs/{self.id}/video?v={self.revision}"
                if self.status == "completed" and self.output and self.output.exists()
                else None
            ),
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


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(ASSETS / "index.html")


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


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    return store.get(job_id).public()


@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str) -> FileResponse:
    job = store.get(job_id)
    if not job.output or not job.output.is_file():
        raise HTTPException(status_code=404, detail="Video chua san sang")
    return FileResponse(job.output, media_type="video/mp4", filename=f"viet-transform-{job.id}.mp4")


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
    background.add_task(_run_job, job, job.options, job.settings)
    return {"job_id": job.id}


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, background: BackgroundTasks) -> dict[str, str]:
    job = store.get(job_id)
    if job.status == "running":
        raise HTTPException(status_code=409, detail="Job dang xu ly")
    if not job.options or not job.settings:
        raise HTTPException(status_code=409, detail="Job khong con du lieu de retry")
    job.error = None
    background.add_task(_run_job, job, job.options, job.settings)
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
    )
    job.options = replace(job.options, render=render_options)
    job.settings = replace(job.settings, font_name=editor.font_name)
    if job.output and job.output.exists():
        job.output.unlink()
    job.stages["Render video"] = "pending"
    background.add_task(_run_job, job, job.options, job.settings)
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
    tts_voice: str = Form("vi-VN-HoaiMyNeural"),
    tts_rate: str = Form("+0%"),
    tts_engine: str = Form("auto"),
    tts_speaker: int | None = Form(None),
    font_name: str = Form("Montserrat"),
    resolution: str = Form("1080x1920"),
    zoom: float = Form(1.06),
    trim_seconds: float = Form(0.5),
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
    if "gpt" not in script_model.lower():
        raise HTTPException(status_code=422, detail="Hay chon mot model GPT de viet kich ban")

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
    background.add_task(_run_job, job, options, settings)
    return {"job_id": job.id}


def _run_job(job: Job, options: PipelineOptions, settings: Settings) -> None:
    def progress(stage: str, status: str) -> None:
        job.active_stage = stage
        job.stages[stage] = status

    job.status = "running"
    job.error = None
    try:
        job.output = execute(options, settings, progress)
        job.status = "completed"
        job.active_stage = "Hoan tat"
        job.revision += 1
    except Exception as exc:
        LOG.exception("Job %s failed", job.id)
        job.status = "failed"
        job.error = str(exc)
        if job.active_stage in job.stages:
            job.stages[job.active_stage] = "failed"


def main() -> None:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    uvicorn.run("viet_transform.web:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
