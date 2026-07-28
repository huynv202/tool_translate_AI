from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .errors import PipelineError


@dataclass
class DialogueLine:
    id: int
    start: float
    end: float
    source: str
    translation: str = ""
    voice: str | None = None
    speaker: int | None = None

    @property
    def duration(self) -> float:
        return max(0.4, self.end - self.start)


def save_dialogue(lines: list[DialogueLine], path: Path) -> Path:
    path.write_text(
        json.dumps([asdict(line) for line in lines], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_dialogue(path: Path) -> list[DialogueLine]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [DialogueLine(**item) for item in data]
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise PipelineError(f"Khong doc duoc du lieu hoi thoai: {exc}") from exc


def dialogue_script(lines: list[DialogueLine]) -> str:
    return "\n".join(line.translation for line in lines)


def apply_script(lines: list[DialogueLine], script: str) -> list[DialogueLine]:
    translations = [line.strip() for line in script.splitlines() if line.strip()]
    if len(translations) != len(lines):
        raise PipelineError(
            f"Kich ban can giu dung {len(lines)} dong thoai; hien co {len(translations)} dong."
        )
    for line, translation in zip(lines, translations, strict=True):
        line.translation = translation
    return lines


def dialogue_srt(lines: list[DialogueLine]) -> str:
    return "\n\n".join(
        f"{index}\n{_timestamp(line.start)} --> {_timestamp(line.end)}\n{line.translation.strip()}"
        for index, line in enumerate(lines, start=1)
        if line.translation.strip()
    ) + "\n"


def parse_json_response(content: str) -> list[dict[str, object]]:
    cleaned = content.strip().lstrip("\ufeff")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    candidates = [cleaned]
    for opening, closing in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opening), cleaned.rfind(closing)
        if start >= 0 and end > start:
            candidates.append(cleaned[start : end + 1])

    payload = None
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        normalized = candidate.replace("“", '"').replace("”", '"')
        normalized = re.sub(r",\s*([}\]])", r"\1", normalized)
        try:
            payload = json.loads(normalized)
            break
        except json.JSONDecodeError as exc:
            last_error = exc
    if payload is None:
        raise PipelineError("AI khong tra ve JSON hoi thoai hop le.") from last_error
    if isinstance(payload, dict):
        payload = payload.get("segments", [])
    if not isinstance(payload, list):
        raise PipelineError("JSON hoi thoai phai la mot danh sach.")
    return payload


def _timestamp(seconds: float) -> str:
    milliseconds = round(max(0, seconds) * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
