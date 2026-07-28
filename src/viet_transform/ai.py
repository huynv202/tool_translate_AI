from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from openai import OpenAI

from .config import Settings
from .dialogue import DialogueLine, parse_json_response
from .errors import PipelineError
from .local_stt import transcribe_text

LOG = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ban la bien kich review phim Viet Nam. Viet lai noi dung nguon thanh mot loi dan
hoan toan moi, the hien binh luan va goc nhin rieng, khong chep cau thoai. Dau ra 130-150 tu tieng
Viet, co hook manh trong 3 giay dau, nhip nhanh, mach lac, khong bia them tinh tiet, va ket bang CTA
tu nhien. Chi tra ve kich ban, khong tieu de, khong markdown."""

DIALOGUE_PROMPT = """Ban la bien dich long tieng phim Trung-Viet. Dau vao la cac cau duoc nhan dang
truc tiep tu audio goc. Dich tung cau thoai theo dung y nghia, ngu canh va cam xuc cua nguoi dang noi.
Ban dich phai ngan gon de doc vua duration_seconds va giu dung moc thoi gian cua audio goc. Tuyet doi
khong mo ta canh quay, khong tom tat video, khong viet loi dan review, khong them hook, CTA hay tinh
tiet moi. Neu segment chi la ky hieu am thanh, nhac nen hoac mo ta khong phai loi noi, tra translation
rong. Giu nguyen id va chi tra ve noi dung se duoc doc thanh tieng.
Chi tra ve JSON:
{"segments":[{"id":1,"translation":"..."}]}"""

SCRIPT_PROMPT = """Ban la bien kich long tieng. Viet lai ban dich tho thanh loi thoai tu nhien,
co cam xuc va dung van phong noi cua ngon ngu dich. Co the them chut hai huoc trong cach noi, nhung
khong duoc thay doi su kien, y nghia, id hay thu tu. Moi cau phai ngan gon de doc vua duration_seconds.
Chi tra ve JSON: {"segments":[{"id":1,"translation":"..."}]}"""

CREATOR_ANALYSIS_PROMPT = """Ban la bien kich cua mot kenh Viet Nam theo phong cach HO SO GIAI MA.
Video nguon chi la tu lieu bang chung, khong phai bo xuong de dich lai. Hay bien cac du kien tho thanh
loi dan moi cua nguoi ke chuyen: binh tinh, sac, de hieu, khong giat gan rong. Moi cum noi dung dung
nhip: DAT VAN DE -> BANG CHUNG -> GIAI THICH -> GOC NHIN VIET NAM. Cau dau phai tao ly do xem tiep.
Khong gia lam nhan vat, khong dich nguyen van, khong bia du kien ngoai context. Giu id va viet ngan
de doc vua duration_seconds. Chi tra ve JSON {"segments":[{"id":1,"translation":"..."}]}"""


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
    content_mode: str = "localization",
    editorial_thesis: str = "",
    vietnam_angle: str = "",
    research_sources: tuple[str, ...] = (),
) -> list[DialogueLine]:
    if content_mode == "creator-analysis":
        narrated: list[dict[str, object]] = []
        for start in range(0, len(lines), 20):
            narrated.extend(_creator_analysis_batch(
                lines[start : start + 20], settings, target_language, cache_dir,
                editorial_thesis, vietnam_angle, research_sources,
            ))
        try:
            by_id = {int(item["id"]): str(item["translation"]).strip() for item in narrated}
        except (KeyError, TypeError, ValueError) as exc:
            raise PipelineError("AI Creator Analysis tra ve cau truc cue khong hop le.") from exc
        if set(by_id) != {line.id for line in lines}:
            raise PipelineError("AI Creator Analysis tra ve thieu hoac sai id cue.")
        for line in lines:
            line.translation = by_id[line.id]
            if not line.translation:
                line.translation = _plain_text_completion(
                    settings,
                    settings.script_model,
                    CREATOR_ANALYSIS_PROMPT,
                    _single_creator_analysis_content(
                        line, target_language, editorial_thesis, vietnam_angle, research_sources
                    ),
                )
        return lines

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
    translated_lines: list[DialogueLine] = []
    for line in lines:
        line.translation = by_id[line.id]
        if line.translation:
            translated_lines.append(line)
            continue
        # Whisper can split a sentence-final particle into its own very short cue.
        # Keep the original audio span by extending the preceding translated cue.
        if translated_lines and line.duration <= 0.6 and len(line.source.strip()) <= 2:
            translated_lines[-1].end = max(translated_lines[-1].end, line.end)
            continue
        line.translation = _plain_text_completion(
            settings,
            settings.text_model,
            DIALOGUE_PROMPT,
            f"Target language: {target_language}. This is spoken dialogue and must not be empty. "
            f"Translate only this sentence: {line.source}",
        )
        translated_lines.append(line)
    return translated_lines


def adapt_dialogue(
    lines: list[DialogueLine], settings: Settings, cache_dir: Path | None = None,
    content_mode: str = "creator-analysis", editorial_thesis: str = "",
    vietnam_angle: str = "", research_sources: tuple[str, ...] = (),
) -> list[DialogueLine]:
    adapted: list[dict[str, object]] = []
    for start in range(0, len(lines), 30):
        batch = lines[start : start + 30]
        segments = [
            {
                "id": line.id,
                "duration_seconds": round(line.duration, 2),
                "literal_translation": str(line.translation),
            }
            for line in batch
        ]
        context = {
            "mode": str(content_mode),
            "channel_style": "Ho so Giai ma: dat van de, bang chung, giai thich, goc nhin Viet Nam",
            "editorial_thesis": str(editorial_thesis),
            "vietnam_angle": str(vietnam_angle),
            "research_sources": [str(source) for source in research_sources],
            "segments": segments,
        }
        prompt = CREATOR_ANALYSIS_PROMPT if content_mode == "creator-analysis" else SCRIPT_PROMPT
        try:
            adapted.extend(
                _cached_json_completion(
                    settings,
                    settings.script_model,
                    prompt,
                    json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                    0.65,
                    cache_dir,
                    "adapt",
                )
            )
        except PipelineError as exc:
            if "JSON" not in str(exc):
                raise
            if len(batch) > 1:
                midpoint = len(batch) // 2
                for part in (batch[:midpoint], batch[midpoint:]):
                    recovered = adapt_dialogue(
                        part,
                        settings,
                        cache_dir=cache_dir,
                        content_mode=content_mode,
                        editorial_thesis=editorial_thesis,
                        vietnam_angle=vietnam_angle,
                        research_sources=research_sources,
                    )
                    adapted.extend(
                        {"id": line.id, "translation": line.translation} for line in recovered
                    )
            else:
                adapted.append({
                    "id": batch[0].id,
                    "translation": _plain_text_completion(
                        settings,
                        settings.script_model,
                        prompt,
                        json.dumps(context, ensure_ascii=False, separators=(",", ":")),
                    ),
                })
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
        literal_translation = line.translation
        line.translation = by_id[line.id]
        if not line.translation:
            line.translation = _plain_text_completion(
                settings,
                settings.script_model,
                prompt,
                json.dumps(
                    {
                        "mode": str(content_mode),
                        "editorial_thesis": str(editorial_thesis),
                        "vietnam_angle": str(vietnam_angle),
                        "research_sources": [str(source) for source in research_sources],
                        "segments": [{
                            "id": line.id,
                            "duration_seconds": round(line.duration, 2),
                            "literal_translation": str(literal_translation),
                        }],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    return lines


def _creator_analysis_batch(
    lines: list[DialogueLine], settings: Settings, target_language: str,
    cache_dir: Path | None, editorial_thesis: str, vietnam_angle: str,
    research_sources: tuple[str, ...],
) -> list[dict[str, object]]:
    context = {
        "target_language": target_language,
        "editorial_thesis": editorial_thesis,
        "vietnam_angle": vietnam_angle,
        "research_sources": [str(source) for source in research_sources],
        "source_segments": [
            {"id": line.id, "duration_seconds": round(line.duration, 2), "source": line.source}
            for line in lines
        ],
    }
    user_content = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    try:
        result = _cached_json_completion(
            settings, settings.script_model, CREATOR_ANALYSIS_PROMPT, user_content,
            0.55, cache_dir, "creator",
        )
        returned_ids = {int(item["id"]) for item in result}
        if returned_ids != {line.id for line in lines}:
            raise PipelineError("JSON Creator Analysis tra ve thieu hoac sai id cue.")
        return result
    except PipelineError as exc:
        if "JSON" not in str(exc):
            raise
        if len(lines) > 1:
            midpoint = len(lines) // 2
            return _creator_analysis_batch(
                lines[:midpoint], settings, target_language, cache_dir,
                editorial_thesis, vietnam_angle, research_sources,
            ) + _creator_analysis_batch(
                lines[midpoint:], settings, target_language, cache_dir,
                editorial_thesis, vietnam_angle, research_sources,
            )
        return [{
            "id": lines[0].id,
            "translation": _plain_text_completion(
                settings, settings.script_model, CREATOR_ANALYSIS_PROMPT, user_content
            ),
        }]


def _single_creator_analysis_content(
    line: DialogueLine,
    target_language: str,
    editorial_thesis: str,
    vietnam_angle: str,
    research_sources: tuple[str, ...],
) -> str:
    return json.dumps(
        {
            "target_language": target_language,
            "editorial_thesis": editorial_thesis,
            "vietnam_angle": vietnam_angle,
            "research_sources": [str(source) for source in research_sources],
            "source_segments": [{
                "id": line.id,
                "duration_seconds": round(line.duration, 2),
                "source": line.source,
            }],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


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
        result = _cached_json_completion(
            settings,
            settings.text_model,
            DIALOGUE_PROMPT,
            f"Target language: {target_language}. Translate every segment.\n"
            + json.dumps(source, ensure_ascii=False, separators=(",", ":")),
            0.25,
            cache_dir,
            "translate",
        )
        try:
            returned_ids = [int(item["id"]) for item in result]
        except (KeyError, TypeError, ValueError) as exc:
            raise PipelineError("JSON ban dich co id khong hop le.") from exc
        expected_ids = [line.id for line in lines]
        if returned_ids != expected_ids:
            missing = sorted(set(expected_ids) - set(returned_ids))
            raise PipelineError(
                f"JSON ban dich thieu, trung hoac sai thu tu id: {missing or returned_ids}"
            )
        return result
    except PipelineError as exc:
        if "JSON" not in str(exc):
            raise
        if len(lines) > 1:
            midpoint = len(lines) // 2
            return _translate_batch(
                lines[:midpoint], settings, target_language, cache_dir
            ) + _translate_batch(lines[midpoint:], settings, target_language, cache_dir)
        return [{
            "id": lines[0].id,
            "translation": _plain_text_completion(
                settings,
                settings.text_model,
                DIALOGUE_PROMPT,
                f"Target language: {target_language}. Translate this single sentence: {lines[0].source}",
            ),
        }]
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
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    parsed: list[dict[str, object]] | None = None
    last_error: PipelineError | None = None
    for attempt in range(3):
        response = _client(settings).chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature if attempt == 0 else 0,
        )
        content = response.choices[0].message.content or ""
        try:
            parsed = parse_json_response(content)
            break
        except PipelineError as exc:
            last_error = exc
            LOG.warning("Model %s tra ve JSON loi, thu sua lan %s/2", model, attempt + 1)
            messages.extend([
                {"role": "assistant", "content": content[:12000]},
                {
                    "role": "user",
                    "content": (
                        "Phan hoi tren khong parse duoc. Hay tra lai DUY NHAT mot JSON object hop le "
                        "dung schema {\"segments\":[{\"id\":1,\"translation\":\"...\"}]}. "
                        "Khong markdown, khong giai thich, khong bo sot segment."
                    ),
                },
            ])
    if parsed is None:
        raise last_error or PipelineError("AI khong tra ve JSON hoi thoai hop le.")
    if cache_path:
        temporary = cache_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(parsed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        temporary.replace(cache_path)
    return parsed


def _plain_text_completion(
    settings: Settings,
    model: str,
    system_prompt: str,
    user_content: str,
) -> str:
    response = _client(settings).chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": system_prompt + "\nTra ve duy nhat mot cau van ban thuan, khong JSON, khong markdown.",
            },
            {"role": "user", "content": user_content},
        ],
        temperature=0,
    )
    content = (response.choices[0].message.content or "").strip()
    content = content.removeprefix("```").removesuffix("```").strip()
    if not content:
        raise PipelineError("AI tra ve noi dung rong khi fallback tung cue.")
    if content.startswith("{"):
        try:
            parsed = parse_json_response(content)
            content = str(parsed[0]["translation"]).strip()
        except (PipelineError, KeyError, IndexError, TypeError):
            pass
    if not content:
        raise PipelineError("AI tra ve noi dung rong khi fallback tung cue.")
    return content


def _validate_script(script: str) -> str:
    if not script:
        raise PipelineError("AI tra ve kich ban rong.")
    words = script.split()
    if not 90 <= len(words) <= 190:
        raise PipelineError(f"Kich ban co {len(words)} tu, vuot nguong an toan 90-190 tu.")
    return script
