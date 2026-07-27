from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import ai
from .config import Settings
from .dialogue import dialogue_script, dialogue_srt, load_dialogue, save_dialogue
from .local_stt import transcribe_dialogue
from .media import choose_music, extract_audio, require_binaries
from .source import acquire
from .source_subtitles import extract_subtitle_lines
from .speech import synthesize_dialogue
from .video import RenderOptions, render

LOG = logging.getLogger(__name__)
ProgressCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class PipelineOptions:
    source: str
    output: Path
    work_dir: Path
    music: Path | None = None
    logo: Path | None = None
    seed: int | None = None
    resume: bool = True
    target_language: str = "Vietnamese"
    render: RenderOptions = field(default_factory=RenderOptions)


def _stage(path: Path, label: str, resume: bool, action, progress: ProgressCallback | None = None):
    if resume and path.exists() and path.stat().st_size:
        LOG.info("[skip] %s", label)
        if progress:
            progress(label, "completed")
        return path
    LOG.info("[run]  %s", label)
    if progress:
        progress(label, "running")
    result = action()
    if progress:
        progress(label, "completed")
    return result


def _write_text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def execute(
    options: PipelineOptions,
    settings: Settings,
    progress: ProgressCallback | None = None,
) -> Path:
    require_binaries()
    settings.validate_api_keys()
    options.work_dir.mkdir(parents=True, exist_ok=True)

    source = _stage(
        options.work_dir / "source.mp4", "Lay video nguon", options.resume,
        lambda: acquire(options.source, options.work_dir), progress,
    )
    source_audio = _stage(
        options.work_dir / "source.wav", "Trich xuat audio", options.resume,
        lambda: extract_audio(source, options.work_dir / "source.wav"), progress,
    )
    source_dialogue = options.work_dir / "dialogue.source.json"
    _stage(
        source_dialogue,
        "Nhan dang tieng Trung",
        options.resume,
        lambda: _extract_source_dialogue(
            source, source_audio, source_dialogue, options.work_dir, settings
        ),
        progress,
    )
    translated_dialogue = options.work_dir / "dialogue.translated.json"
    script_file = options.work_dir / "script.translated.txt"
    _stage(
        translated_dialogue,
        "Dich va bien tap AI",
        options.resume,
        lambda: _translate_dialogue(
            source_dialogue,
            translated_dialogue,
            script_file,
            settings,
            options.target_language,
        ),
        progress,
    )
    timed_lines = _shift_dialogue(
        load_dialogue(translated_dialogue), options.render.trim_seconds
    )
    voiceover = _stage(
        options.work_dir / "voiceover.mp3",
        "Tao giong doc",
        options.resume,
        lambda: synthesize_dialogue(
            timed_lines, options.work_dir / "voiceover.mp3", settings, options.work_dir
        ),
        progress,
    )
    subtitles = _stage(
        options.work_dir / "voiceover.srt",
        "Tao phu de",
        options.resume,
        lambda: _write_text(options.work_dir / "voiceover.srt", dialogue_srt(timed_lines)),
        progress,
    )
    music = options.music or choose_music(settings.music_dir, options.seed)
    LOG.info("Nhac nen: %s", music or "khong co")
    LOG.info("[run]  Render video")
    if progress:
        progress("Render video", "running")
    result = render(
        source,
        voiceover,
        subtitles,
        options.output,
        settings.font_name,
        music,
        options.logo,
        options.render,
    )
    if progress:
        progress("Render video", "completed")
    return result


def _extract_source_dialogue(
    video: Path, audio: Path, output: Path, work_dir: Path, settings: Settings
) -> Path:
    lines = extract_subtitle_lines(video, work_dir / "source.embedded.srt")
    if not lines:
        lines = transcribe_dialogue(audio, settings.local_whisper_model, "zh")
    _write_text(work_dir / "transcript.txt", "\n".join(line.source for line in lines))
    return save_dialogue(lines, output)


def _translate_dialogue(
    source: Path,
    output: Path,
    script_file: Path,
    settings: Settings,
    target_language: str,
) -> Path:
    lines = ai.translate_dialogue(
        load_dialogue(source), settings, target_language, output.parent / "ai-cache"
    )
    _write_text(script_file, dialogue_script(lines))
    return save_dialogue(lines, output)


def _shift_dialogue(lines, trim_seconds: float):
    shifted = []
    for line in lines:
        if line.end <= trim_seconds:
            continue
        start = max(0.0, line.start - trim_seconds)
        end = max(start + 0.4, line.end - trim_seconds)
        shifted.append(replace(line, start=start, end=end))
    return shifted
