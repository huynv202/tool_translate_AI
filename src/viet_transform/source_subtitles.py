from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .dialogue import DialogueLine

TIMING = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def extract_subtitle_lines(video: Path, output: Path) -> list[DialogueLine] | None:
    if not _has_text_subtitle_stream(video):
        return None
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-map",
            "0:s:0",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode or not output.exists() or output.stat().st_size == 0:
        return None
    return parse_srt(output.read_text(encoding="utf-8", errors="replace"))


def _has_text_subtitle_stream(video: Path) -> bool:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "json",
            str(video),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return False
    try:
        streams = json.loads(result.stdout).get("streams", [])
    except json.JSONDecodeError:
        return False
    text_codecs = {"subrip", "ass", "ssa", "webvtt", "mov_text"}
    return any(stream.get("codec_name") in text_codecs for stream in streams)


def parse_srt(content: str) -> list[DialogueLine]:
    lines: list[DialogueLine] = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip())
    for block in blocks:
        block_lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next(
            (index for index, value in enumerate(block_lines) if TIMING.search(value)), None
        )
        if timing_index is None:
            continue
        match = TIMING.search(block_lines[timing_index])
        if not match:
            continue
        text = " ".join(block_lines[timing_index + 1 :])
        text = re.sub(r"<[^>]+>|\{[^}]+\}", "", text).strip()
        if text:
            lines.append(
                DialogueLine(
                    id=len(lines) + 1,
                    start=_seconds(match.group("start")),
                    end=_seconds(match.group("end")),
                    source=text,
                )
            )
    return lines


def _seconds(value: str) -> float:
    hours, minutes, rest = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)
