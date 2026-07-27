from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from faster_whisper import WhisperModel

from .dialogue import DialogueLine
from .errors import PipelineError

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
    lines = []
    for index, segment in enumerate(_segments(audio, model_name, language), start=1):
        text = segment.text.strip()
        if text:
            lines.append(
                DialogueLine(
                    id=index,
                    start=round(segment.start, 3),
                    end=round(segment.end, 3),
                    source=text,
                )
            )
    if not lines:
        raise PipelineError("Whisper local khong nhan dang duoc hoi thoai.")
    return lines


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
