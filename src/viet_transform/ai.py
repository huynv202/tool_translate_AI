from __future__ import annotations

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
    lines: list[DialogueLine], settings: Settings, target_language: str = "Vietnamese"
) -> list[DialogueLine]:
    translated: list[dict[str, object]] = []
    for start in range(0, len(lines), 30):
        translated.extend(
            _translate_batch(lines[start : start + 30], settings, target_language)
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
    return adapt_dialogue(lines, settings)


def adapt_dialogue(lines: list[DialogueLine], settings: Settings) -> list[DialogueLine]:
    adapted: list[dict[str, object]] = []
    for start in range(0, len(lines), 30):
        batch = lines[start : start + 30]
        payload = [
            {
                "id": line.id,
                "duration_seconds": round(line.duration, 2),
                "source": line.source,
                "literal_translation": line.translation,
            }
            for line in batch
        ]
        try:
            response = _client(settings).chat.completions.create(
                model=settings.script_model,
                messages=[
                    {"role": "system", "content": SCRIPT_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.65,
            )
            adapted.extend(parse_json_response(response.choices[0].message.content or ""))
        except PipelineError:
            raise
        except Exception as exc:
            detail = str(exc)
            if "No active credentials for provider" in detail:
                raise PipelineError(
                    "GPT script model khong co credential dang hoat dong trong 9Router. "
                    "Hay chon cx/... neu auth Codex hoac gh/... neu auth GitHub Copilot."
                ) from exc
            raise PipelineError(f"9Router GPT viet kich ban that bai: {detail}") from exc
    try:
        by_id = {int(item["id"]): str(item["translation"]).strip() for item in adapted}
    except (KeyError, TypeError, ValueError) as exc:
        raise PipelineError("GPT tra ve cau truc kich ban khong hop le.") from exc
    if set(by_id) != {line.id for line in lines}:
        raise PipelineError("GPT tra ve thieu hoac sai id cau thoai.")
    for line in lines:
        line.translation = by_id[line.id]
    return lines


def _translate_batch(
    lines: list[DialogueLine], settings: Settings, target_language: str
) -> list[dict[str, object]]:
    source = [
        {"id": line.id, "duration_seconds": round(line.duration, 2), "source": line.source}
        for line in lines
    ]
    try:
        response = _client(settings).chat.completions.create(
            model=settings.text_model,
            messages=[
                {"role": "system", "content": DIALOGUE_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Target language: {target_language}. Translate every segment.\n"
                        + json.dumps(source, ensure_ascii=False)
                    ),
                },
            ],
            temperature=0.25,
        )
        return parse_json_response(response.choices[0].message.content or "")
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


def _validate_script(script: str) -> str:
    if not script:
        raise PipelineError("AI tra ve kich ban rong.")
    words = script.split()
    if not 90 <= len(words) <= 190:
        raise PipelineError(f"Kich ban co {len(words)} tu, vuot nguong an toan 90-190 tu.")
    return script
