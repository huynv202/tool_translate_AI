from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from .errors import PipelineError


def is_url(value: str) -> bool:
    return urlparse(value).scheme in {"http", "https"}


def acquire(source: str, work_dir: Path) -> Path:
    target = work_dir / "source.mp4"
    if is_url(source):
        options = {
            "format": "bv*+ba/b",
            "outtmpl": str(work_dir / "download.%(ext)s"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
        }
        try:
            with YoutubeDL(options) as downloader:
                info = downloader.extract_info(source, download=True)
                downloaded = Path(downloader.prepare_filename(info))
        except Exception as exc:
            raise PipelineError(f"Khong tai duoc video: {exc}") from exc
        candidates = [work_dir / "download.mp4", downloaded]
        downloaded = next((p for p in candidates if p.exists()), downloaded)
        if not downloaded.exists():
            raise PipelineError("Tai video xong nhung khong tim thay file dau ra.")
        shutil.move(downloaded, target)
    else:
        local = Path(source).expanduser().resolve()
        if not local.is_file():
            raise PipelineError(f"Khong tim thay video: {local}")
        shutil.copy2(local, target)
    return target

