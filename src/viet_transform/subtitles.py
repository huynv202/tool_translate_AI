from __future__ import annotations

import re
from pathlib import Path

from .config import Settings
from .local_stt import transcribe_srt


def create_srt(voiceover: Path, output: Path, settings: Settings) -> Path:
    text = transcribe_srt(voiceover, settings.local_whisper_model, "vi")
    output.write_text(normalize_srt(text), encoding="utf-8")
    return output


def normalize_srt(text: str) -> str:
    """Normalize whitespace without touching SRT timestamps or cue boundaries."""
    blocks = re.split(r"\n\s*\n", text.strip())
    normalized: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) >= 3:
            lines[2:] = [" ".join(lines[2:])]
        normalized.append("\n".join(lines))
    return "\n\n".join(normalized) + "\n"


def escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
