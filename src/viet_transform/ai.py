from __future__ import annotations

import hashlib
import json
from pathlib import Path

from openai import OpenAI

from .config import Settings
from .dialogue import DialogueLine, parse_json_response
from .errors import PipelineError
from .local_stt import transcribe_text

SYSTEM_PROMPT = """Ban la bien kich review phim Viet Nam. Viet lai noi dung nguon thanh mot loi dan
hoan toan moi, the hien binh luan va goc nhin rieng, khong chep cau thoai. Dau ra 130-150 tu tieng
Viet, co hook manh trong 3 giay dau, nhip nhanh, mach lac, khong bia them tinh tiet, va ket bang CTA
tu nhien. Chi tra ve kich ban, khong tieu de, khong markdown."""

DIALOGUE_PROMPT = """Ban la bien dich long tieng phim Trung-Viet. Dich tung cau theo dung y nghia,
ngu canh va cam xuc cua nhan vat. Ban dich phai ngan gon de doc vua thoi luong goc, tu nhien nhu
nguoi ban dia noi, khong tom tat, khong bien thanh loi review, khong them tinh tiet. Giu nguyen id.
Chi tra ve JSON:
{"segments":[{"id":1,"translation":"..."}]}"""

SCRIPT_PROMPT = """Ban la bien kich long tieng. Viet lai ban dich tho thanh loi thoai tu nhien,
co cam xuc va dung van phong noi cua ngon ngu dich. Co the them chut hai huoc trong cach noi, nhung
khong duoc thay doi su kien, y nghia, id hay thu tu. Moi cau phai ngan gon de doc vua duration_seconds.
Chi tra ve JSON: {"segments":[{"id":1,"translation":"..."}]}"""


def _client(settings: Settings) -> OpenAI:
    return OpenAI(api_key=settings.router_api_key, base_url=settings.router_base_url)


def transcribe(audio: Path, settings: Settings, language: str | None = "zh") -> str:
    return transcribe_text(audio, settings.local_whisper_model, language)


def write_script(transcript: str, settings: Settings) -> str:
    if not transcript.strip():
        raise PipelineError("Ban ghi am rong, khong the viet kich ban.")
    try:
        response = _client(settings).chat.completions.create(
            model=settings.text_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Noi dung tieng Trung can chuyen the:\n{transcript}",
                },
            ],
            temperature=0.7,
        )
        script = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        detail = str(exc)
        if "ACCESS_TOKEN_TYPE_UNSUPPORTED" in detail:
            raise PipelineError(
                "Ban dang chon route gemini/ (API provider) nhung credential la OAuth login. "
                "Hay chon model co prefix gc/ neu auth Gemini CLI, hoac ag/ neu auth Antigravity."
            ) from exc
        if "No active credentials for provider" in detail or "No credentials for provider" in detail:
            raise PipelineError(
                "Model da chon khong co tai khoan provider dang hoat dong trong 9Router. "
                "Mo 9ROUTER CONFIG, tai danh sach model va chon model thuoc tai khoan da auth."
            ) from exc
        raise PipelineError(f"9Router viet kich ban that bai: {detail}") from exc
    return _validate_script(script)


def translate_dialogue(
    lines: list[DialogueLine],
    settings: Settings,
    target_language: str = "Vietnamese",
    cache_dir: Path | None = None,
) -> list[DialogueLine]:
    translated: list[dict[str, object]] = []
    for start in range(0, len(lines), 30):
        translated.extend(
            _translate_batch(lines[start : start + 30], settings, target_language, cache_dir)
        )
    try:
        by_id = {int(item["id"]): str(item["translation"]).strip() for item in translated}
    except (KeyError, TypeError, ValueError) as exc:
        raise PipelineError("AI tra ve cau truc ban dich khong hop le.") from exc
    if set(by_id) != {line.id for line in lines}:
        raise PipelineError("AI tra ve thieu hoac sai id cau thoai.")
    for line in lines:
        line.translation = by_id[line.id]
        if not line.translation:
            raise PipelineError(f"Ban dich cua cau {line.id} bi rong.")
    return adapt_dialogue(lines, settings, cache_dir)


def adapt_dialogue(
    lines: list[DialogueLine], settings: Settings, cache_dir: Path | None = None
) -> list[DialogueLine]:
    adapted: list[dict[str, object]] = []
    for start in range(0, len(lines), 30):
        batch = lines[start : start + 30]
        payload = [
            {
                "id": line.id,
                "duration_seconds": round(line.duration, 2),
                "literal_translation": line.translation,
            }
            for line in batch
        ]
        try:
            adapted.extend(
                _cached_json_completion(
                    settings,
                    settings.script_model,
                    SCRIPT_PROMPT,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    0.65,
                    cache_dir,
                    "adapt",
                )
            )
        except PipelineError:
            raise
        except Exception as exc:
            detail = str(exc)
            if "No active credentials for provider" in detail:
                raise PipelineError(
                    "Model viet kich ban khong co credential dang hoat dong trong 9Router. "
                    "Hay chon route GPT hoac Claude thuoc tai khoan da auth."
                ) from exc
            raise PipelineError(f"9Router viet kich ban that bai: {detail}") from exc
    try:
        by_id = {int(item["id"]): str(item["translation"]).strip() for item in adapted}
    except (KeyError, TypeError, ValueError) as exc:
        raise PipelineError("AI viet kich ban tra ve cau truc khong hop le.") from exc
    if set(by_id) != {line.id for line in lines}:
        raise PipelineError("AI viet kich ban tra ve thieu hoac sai id cau thoai.")
    for line in lines:
        line.translation = by_id[line.id]
    return lines


def _translate_batch(
    lines: list[DialogueLine],
    settings: Settings,
    target_language: str,
    cache_dir: Path | None = None,
) -> list[dict[str, object]]:
    source = [
        {"id": line.id, "duration_seconds": round(line.duration, 2), "source": line.source}
        for line in lines
    ]
    try:
        return _cached_json_completion(
            settings,
            settings.text_model,
            DIALOGUE_PROMPT,
            f"Target language: {target_language}. Translate every segment.\n"
            + json.dumps(source, ensure_ascii=False, separators=(",", ":")),
            0.25,
            cache_dir,
            "translate",
        )
    except PipelineError:
        raise
    except Exception as exc:
        detail = str(exc)
        if "ACCESS_TOKEN_TYPE_UNSUPPORTED" in detail:
            raise PipelineError(
                "Credential OAuth khong dung duoc voi route gemini/ truc tiep. "
                "Hay chon gc/... cho Gemini CLI OAuth hoac ag/... cho Antigravity OAuth."
            ) from exc
        if "No active credentials for provider" in detail or "No credentials for provider" in detail:
            raise PipelineError(
                "Model da chon khong co provider dang hoat dong trong 9Router."
            ) from exc
        raise PipelineError(f"9Router dich hoi thoai that bai: {detail}") from exc


def _cached_json_completion(
    settings: Settings,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float,
    cache_dir: Path | None,
    prefix: str,
) -> list[dict[str, object]]:
    key_data = json.dumps(
        {
            "model": model,
            "system": system_prompt,
            "user": user_content,
            "temperature": temperature,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    cache_path: Path | None = None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(key_data.encode("utf-8")).hexdigest()[:24]
        cache_path = cache_dir / f"{prefix}-{digest}.json"
        if cache_path.is_file():
            return parse_json_response(cache_path.read_text(encoding="utf-8"))
    response = _client(settings).chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
    )
    content = response.choices[0].message.content or ""
    parsed = parse_json_response(content)
    if cache_path:
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        temporary.replace(cache_path)
    return parsed


def _validate_script(script: str) -> str:
    if not script:
        raise PipelineError("AI tra ve kich ban rong.")
    words = script.split()
    if not 90 <= len(words) <= 190:
        raise PipelineError(f"Kich ban co {len(words)} tu, vuot nguong an toan 90-190 tu.")
    return script
