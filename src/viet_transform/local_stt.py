from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

from faster_whisper import WhisperModel

from .dialogue import DialogueLine
from .errors import PipelineError
from .media import duration

SUPPORTED_MODELS = {
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "large-v3-turbo",
    "turbo",
}


def normalize_model_name(name: str) -> str:
    normalized = name.strip().lower()
    if normalized in {"whisper-1", "whisper"}:
        return "small"
    if normalized not in SUPPORTED_MODELS:
        raise PipelineError(
            f"Whisper model '{name}' khong hop le. Hay chon: base, small, medium hoac turbo."
        )
    return normalized


@lru_cache(maxsize=2)
def _model(name: str) -> WhisperModel:
    name = normalize_model_name(name)
    try:
        return WhisperModel(name, device="cpu", compute_type="int8")
    except Exception as exc:
        raise PipelineError(f"Khong tai duoc Whisper local model '{name}': {exc}") from exc


def _segments(
    audio: Path,
    model_name: str,
    language: str | None,
    *,
    word_timestamps: bool = False,
):
    try:
        segments, _ = _model(model_name).transcribe(
            str(audio),
            language=language,
            beam_size=5,
            vad_filter=True,
            word_timestamps=word_timestamps,
        )
        return list(segments)
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError(f"Whisper local that bai: {exc}") from exc


def transcribe_text(audio: Path, model_name: str, language: str | None = None) -> str:
    text = " ".join(segment.text.strip() for segment in _segments(audio, model_name, language))
    if not text:
        raise PipelineError("Whisper local khong nhan dang duoc loi thoai.")
    return text


def transcribe_dialogue(
    audio: Path, model_name: str, language: str | None = "zh"
) -> list[DialogueLine]:
    audio_duration = duration(audio)
    ranges = _chunk_ranges(audio, audio_duration) if audio_duration > 60 else [(0.0, audio_duration)]
    chunks_dir = audio.parent / "stt-chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    lines: list[DialogueLine] = []
    for chunk_index, (start, end) in enumerate(ranges, start=1):
        chunk = chunks_dir / f"chunk-{chunk_index:04d}-{start:.3f}-{end:.3f}.wav"
        if not chunk.exists() or chunk.stat().st_size == 0:
            _extract_chunk(audio, chunk, start, end)
        segments = _segments(chunk, model_name, language, word_timestamps=True)
        chunk_lines = _word_aligned_lines(segments, start, end)
        if lines and chunk_lines and _joins_boundary(lines[-1], chunk_lines[0], start):
            lines[-1].source = f"{lines[-1].source} {chunk_lines[0].source}".strip()
            lines[-1].end = chunk_lines[0].end
            chunk_lines = chunk_lines[1:]
        for line in chunk_lines:
            line.id = len(lines) + 1
            lines.append(line)
    if not lines:
        raise PipelineError("Whisper local khong nhan dang duoc hoi thoai.")
    return lines


def _joins_boundary(previous: DialogueLine, current: DialogueLine, boundary: float) -> bool:
    punctuation = ("。", "！", "？", ".", "!", "?")
    return (
        boundary - previous.end <= 0.45
        and current.start - boundary <= 0.45
        and not previous.source.rstrip().endswith(punctuation)
    )


def _word_aligned_lines(segments, offset: float, chunk_end: float) -> list[DialogueLine]:
    lines: list[DialogueLine] = []
    words = [word for segment in segments for word in (segment.words or [])]
    if not words:
        for segment in segments:
            text = segment.text.strip()
            if text:
                start = min(chunk_end, offset + max(0.0, segment.start))
                end = min(chunk_end, offset + max(segment.end, segment.start + 0.4))
                lines.append(DialogueLine(0, round(float(start), 3), round(float(end), 3), text))
        return lines

    cue = []

    def flush() -> None:
        if not cue:
            return
        text = "".join(word.word for word in cue).strip()
        start = min(chunk_end, offset + max(0.0, cue[0].start))
        end = min(chunk_end, offset + max(cue[-1].end, cue[0].start + 0.4))
        if text and end > start:
            lines.append(DialogueLine(0, round(float(start), 3), round(float(end), 3), text))
        cue.clear()

    for word in words:
        gap = word.start - cue[-1].end if cue else 0.0
        duration_seconds = word.end - cue[0].start if cue else word.end - word.start
        if cue and (gap > 0.45 or len(cue) >= 8 or duration_seconds > 3.2):
            flush()
        cue.append(word)
        if word.word.rstrip().endswith(("。", "！", "？", ".", "!", "?")):
            flush()
    flush()
    return lines


def _chunk_ranges(
    audio: Path,
    total_duration: float,
    target: float = 20.0,
    min_span: float = 14.0,
    max_span: float = 30.0,
) -> list[tuple[float, float]]:
    silence_points = _silence_points(audio)
    ranges: list[tuple[float, float]] = []
    start = 0.0
    while total_duration - start > max_span:
        candidates = [
            point for point in silence_points if start + min_span <= point <= start + max_span
        ]
        end = (
            min(candidates, key=lambda point: abs(point - (start + target)))
            if candidates
            else start + max_span
        )
        ranges.append((round(start, 3), round(end, 3)))
        start = end
    if total_duration - start >= 0.4:
        ranges.append((round(start, 3), round(total_duration, 3)))
    return ranges or [(0.0, round(total_duration, 3))]


def _silence_points(audio: Path) -> list[float]:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio), "-af",
            "silencedetect=noise=-30dB:d=0.18", "-f", "null", "-",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    starts = [float(value) for value in re.findall(r"silence_start: ([0-9.]+)", result.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end: ([0-9.]+)", result.stderr)]
    return [round((start + end) / 2, 3) for start, end in zip(starts, ends, strict=False)]


def _extract_chunk(audio: Path, output: Path, start: float, end: float) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(end - start),
            "-i", str(audio), "-ac", "1", "-ar", "16000", str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode or not output.exists() or output.stat().st_size == 0:
        raise PipelineError(f"Khong cat duoc audio STT tai {start:.1f}-{end:.1f}s")


def transcribe_srt(audio: Path, model_name: str, language: str | None = None) -> str:
    blocks: list[str] = []
    cue_words = []
    cue_start: float | None = None

    def flush() -> None:
        nonlocal cue_words, cue_start
        if not cue_words or cue_start is None:
            return
        cue_end = cue_words[-1].end
        text = "".join(word.word for word in cue_words).strip()
        blocks.append(
            f"{len(blocks) + 1}\n{_timestamp(cue_start)} --> {_timestamp(cue_end)}\n{text}"
        )
        cue_words = []
        cue_start = None

    for segment in _segments(audio, model_name, language, word_timestamps=True):
        for word in segment.words or []:
            if cue_start is None:
                cue_start = word.start
            cue_words.append(word)
            duration = word.end - cue_start
            ends_sentence = word.word.rstrip().endswith((".", "!", "?", ",", ";", ":"))
            if len(cue_words) >= 6 or duration >= 2.4 or (len(cue_words) >= 3 and ends_sentence):
                flush()
    flush()
    if not blocks:
        raise PipelineError("Whisper local khong tao duoc phu de.")
    return "\n\n".join(blocks) + "\n"


def _timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
