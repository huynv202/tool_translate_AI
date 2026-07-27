from __future__ import annotations

import json
import logging
import random
import shutil
import subprocess
from pathlib import Path

from .errors import PipelineError

LOG = logging.getLogger(__name__)


def require_binaries() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise PipelineError(f"Thieu chuong trinh he thong: {', '.join(missing)}")


def run(command: list[str]) -> None:
    LOG.debug("Running: %s", " ".join(command))
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        lines = result.stderr.strip().splitlines()
        error_markers = ("error", "failed", "invalid", "no space", "cannot", "unable")
        relevant = [line for line in lines if any(marker in line.lower() for marker in error_markers)]
        detail_lines = relevant[-8:] or lines[-16:]
        detail = " | ".join(detail_lines) if detail_lines else "unknown error"
        raise PipelineError(f"Lenh media that bai: {detail}")


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise PipelineError(f"Khong doc duoc thong tin video: {path}")
    return float(json.loads(result.stdout)["format"]["duration"])


def extract_audio(video: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    media_duration = duration(video)
    run([
        "ffmpeg", "-y", "-i", str(video), "-vn", "-af",
        "aresample=async=1:first_pts=0", "-ac", "1", "-ar", "16000",
        "-t", f"{media_duration:.3f}", str(output),
    ])
    return output


def choose_music(directory: Path, seed: int | None = None) -> Path | None:
    if not directory.is_dir():
        return None
    tracks = sorted(
        p for p in directory.iterdir() if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac"}
    )
    return random.Random(seed).choice(tracks) if tracks else None
