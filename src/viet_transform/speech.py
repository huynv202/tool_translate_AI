from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import edge_tts
import requests
from aiohttp import ClientError
from edge_tts.exceptions import EdgeTTSException, NoAudioReceived
from piper import PiperVoice, SynthesisConfig

from .config import Settings
from .dialogue import DialogueLine
from .errors import PipelineError
from .media import duration, run

PIPER_VOICES = {
    "vais1000-medium": ("vi_VN-vais1000-medium", "vi/vi_VN/vais1000/medium"),
    "25hours-low": ("vi_VN-25hours_single-low", "vi/vi_VN/25hours_single/low"),
    "vivos-x-low": ("vi_VN-vivos-x_low", "vi/vi_VN/vivos/x_low"),
}
PIPER_REPOSITORY = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


async def _synthesize(text: str, output: Path, settings: Settings) -> None:
    communicator = edge_tts.Communicate(text, settings.tts_voice, rate=settings.tts_rate)
    await communicator.save(str(output))


def synthesize(text: str, output: Path, settings: Settings, retries: int = 5) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(retries):
        if output.exists():
            output.unlink()
        try:
            asyncio.run(_synthesize(text, output, settings))
            if output.is_file() and output.stat().st_size > 0:
                return output
            raise PipelineError("TTS tra ve file am thanh rong.")
        except (EdgeTTSException, ClientError, OSError, PipelineError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries - 1:
                if isinstance(exc, NoAudioReceived):
                    time.sleep((15, 30, 60, 120)[attempt])
                else:
                    time.sleep(2 ** attempt)
    raise PipelineError(f"Tao giong doc that bai sau {retries} lan thu: {last_error}") from last_error


@dataclass(frozen=True)
class SpeechChunk:
    index: int
    start: float
    end: float
    text: str
    voice: str | None = None
    speaker: int | None = None

    @property
    def duration(self) -> float:
        return max(0.5, self.end - self.start)


def synthesize_dialogue(
    lines: list[DialogueLine],
    output: Path,
    settings: Settings,
    work_dir: Path,
    detail: Callable[[str], None] | None = None,
    voice_driven_timeline: bool = False,
) -> Path:
    clips_dir = work_dir / "voice-clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    chunks = dialogue_chunks(lines)
    wants_xtts = settings.tts_engine == "quality" or settings.tts_voice.startswith("xtts-")
    use_xtts = wants_xtts and xtts_ready()
    use_piper = (
        settings.tts_engine == "piper"
        or (wants_xtts and not use_xtts)
        or (
            settings.tts_engine == "auto"
            and len(chunks) > 8
            and settings.tts_voice.startswith("vi-")
        )
    )
    clips: list[tuple[Path, SpeechChunk, float]] = []
    for chunk in chunks:
        if detail and (chunk.index == 1 or chunk.index % 25 == 0 or chunk.index == len(chunks)):
            detail(f"TTS cue {chunk.index}/{len(chunks)} tai {chunk.start:.1f}s")
        chunk_voice = chunk.voice or settings.tts_voice
        chunk_speaker = chunk.speaker if chunk.speaker is not None else settings.tts_speaker
        chunk_uses_piper = chunk_voice.startswith("vi-piper-") or (not chunk.voice and use_piper)
        chunk_uses_xtts = chunk_voice.startswith("xtts-") and use_xtts
        engine_name = "xtts" if chunk_uses_xtts else ("piper" if chunk_uses_piper else "edge")
        voice_key = "".join(char if char.isalnum() else "-" for char in chunk_voice)[-48:]
        content_key = hashlib.sha1(chunk.text.encode("utf-8")).hexdigest()[:10]
        clip = clips_dir / (
            f"{engine_name}-{voice_key}-{content_key}-chunk-{chunk.index:04d}.mp3"
        )
        if not clip.exists() or clip.stat().st_size == 0:
            try:
                if chunk_uses_xtts:
                    try:
                        synthesize_xtts(chunk.text, clip, settings.tts_reference)
                    except PipelineError:
                        engine_name = "piper"
                        clip = clips_dir / f"piper-fallback-chunk-{chunk.index:04d}.mp3"
                        if not clip.exists() or clip.stat().st_size == 0:
                            synthesize_piper(
                                chunk.text,
                                clip,
                                Path("work/models/piper").resolve(),
                            )
                elif chunk_uses_piper:
                    piper_voice = (
                        chunk_voice
                        if chunk_voice.startswith("vi-piper-")
                        else "vi-piper-vais1000-medium"
                    )
                    synthesize_piper(
                        chunk.text,
                        clip,
                        Path("work/models/piper").resolve(),
                        piper_voice,
                        chunk_speaker,
                    )
                else:
                    synthesize(chunk.text, clip, replace(settings, tts_voice=chunk_voice))
            except PipelineError as exc:
                raise PipelineError(
                    f"TTS block {chunk.index}/{len(chunks)} ({chunk.start:.1f}s-"
                    f"{chunk.end:.1f}s) that bai: {exc}"
                ) from exc
            if engine_name == "edge":
                time.sleep(3.0)
        clip_duration = duration(clip)
        clips.append((clip, chunk, clip_duration))

    if voice_driven_timeline:
        available_duration = max(line.end for line in lines)
        raw_duration = sum(clip_duration for _, _, clip_duration in clips)
        scale = min(1.0, available_duration / raw_duration) if raw_duration else 1.0
        cursor = 0.0
        retimed: list[tuple[Path, SpeechChunk, float]] = []
        spoken_lines = [line for line in lines if line.translation.strip()]
        for line, (clip, chunk, clip_duration) in zip(spoken_lines, clips, strict=True):
            slot_duration = max(0.4, clip_duration * scale)
            line.start = cursor
            line.end = cursor + slot_duration
            retimed.append((clip, replace(chunk, start=line.start, end=line.end), clip_duration))
            cursor = line.end
        clips = retimed

    total_duration = max(line.end for line in lines) + 0.5
    _assemble_timeline(clips, output, work_dir, total_duration, detail=detail)
    return output


def dialogue_chunks(lines: list[DialogueLine]) -> list[SpeechChunk]:
    return [
        SpeechChunk(
            index=index,
            start=line.start,
            end=line.end,
            text=line.translation.strip(),
            voice=line.voice,
            speaker=line.speaker,
        )
        for index, line in enumerate(lines, start=1)
        if line.translation.strip()
    ]


def _assemble_timeline(
    clips: list[tuple[Path, SpeechChunk, float]],
    output: Path,
    work_dir: Path,
    total_duration: float,
    batch_size: int = 48,
    detail: Callable[[str], None] | None = None,
) -> None:
    batches_dir = work_dir / "voice-batches"
    batches_dir.mkdir(parents=True, exist_ok=True)
    batch_outputs: list[Path] = []
    cursor = 0.0
    for batch_index, start in enumerate(range(0, len(clips), batch_size), start=1):
        if detail:
            total_batches = (len(clips) + batch_size - 1) // batch_size
            detail(f"Ghep voice batch {batch_index}/{total_batches}")
        batch = clips[start : start + batch_size]
        signature = f"cursor={cursor:.3f}|" + "|".join(
            f"{clip.name}:{chunk.start:.3f}:{chunk.end:.3f}:{clip_duration:.3f}"
            for clip, chunk, clip_duration in batch
        )
        digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
        batch_output = batches_dir / f"batch-{batch_index:04d}-{digest}.mp3"
        batch_end = max(chunk.end for _, chunk, _ in batch)
        if not batch_output.is_file() or batch_output.stat().st_size == 0:
            _render_timeline_batch(batch, batch_output, work_dir, batch_index, cursor)
        batch_outputs.append(batch_output)
        cursor = max(cursor, batch_end)

    command = ["ffmpeg", "-y"]
    for batch_output in batch_outputs:
        command += ["-i", str(batch_output)]
    labels = "".join(f"[{index}:a]" for index in range(len(batch_outputs)))
    command += [
        "-filter_complex",
        f"{labels}concat=n={len(batch_outputs)}:v=0:a=1,apad=pad_dur=0.5[dialogue]",
        "-map", "[dialogue]", "-t", f"{total_duration:.3f}", "-c:a", "libmp3lame",
        "-b:a", "192k", str(output),
    ]
    run(command)


def _render_timeline_batch(
    batch: list[tuple[Path, SpeechChunk, float]],
    output: Path,
    work_dir: Path,
    batch_index: int,
    initial_cursor: float,
) -> None:
    command = ["ffmpeg", "-y"]
    filters: list[str] = []
    labels: list[str] = []
    cursor = initial_cursor
    for index, (clip, chunk, clip_duration) in enumerate(batch):
        command += ["-i", str(clip)]
        tempo = max(1.0, clip_duration / chunk.duration)
        delay = max(0, round((chunk.start - cursor) * 1000))
        span = max(0.4, chunk.end - cursor)
        label = f"s{index}"
        filters.append(
            f"[{index}:a]asetpts=PTS-STARTPTS,{_atempo(tempo)},adelay={delay}|{delay},"
            f"aresample=async=1:first_pts=0,apad,atrim=duration={span:.3f},"
            f"asetpts=PTS-STARTPTS[{label}]"
        )
        labels.append(f"[{label}]")
        cursor = max(cursor, chunk.end)
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[dialogue]")
    filter_script = work_dir / f"voice-filter-{batch_index:04d}.txt"
    filter_script.write_text(";".join(filters), encoding="utf-8")
    command += [
        "-filter_complex_script", str(filter_script), "-map", "[dialogue]",
        "-c:a", "libmp3lame", "-b:a", "192k", str(output),
    ]
    run(command)


def xtts_ready() -> bool:
    if os.getenv("COQUI_TOS_AGREED") != "1":
        return False
    if importlib.util.find_spec("TTS") is None or importlib.util.find_spec("torch") is None:
        return False
    try:
        import torch

        return bool(torch.cuda.is_available()) or os.getenv("XTTS_ALLOW_CPU") == "1"
    except (ImportError, RuntimeError):
        return False


@lru_cache(maxsize=1)
def _xtts_model():
    try:
        import torch
        from TTS.api import TTS

        return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
    except Exception as exc:
        raise PipelineError(f"Khong khoi tao duoc XTTS v2: {exc}") from exc


def synthesize_xtts(text: str, output: Path, reference: Path | None) -> Path:
    if not xtts_ready():
        raise PipelineError("XTTS v2 chua duoc cai hoac may khong co GPU phu hop")
    output.parent.mkdir(parents=True, exist_ok=True)
    wav_path = output.with_suffix(".wav")
    model = _xtts_model()
    try:
        options: dict[str, object] = {
            "text": text,
            "language": "vi",
            "file_path": str(wav_path),
        }
        if reference and reference.is_file():
            options["speaker_wav"] = str(reference)
        else:
            speakers = getattr(model, "speakers", None) or []
            if not speakers:
                raise PipelineError("XTTS can file mau giong 10-30 giay")
            options["speaker"] = speakers[0]
        model.tts_to_file(**options)
        run(["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "libmp3lame", "-b:a", "192k", str(output)])
    except Exception as exc:
        raise PipelineError(f"XTTS v2 tao giong that bai: {exc}") from exc
    finally:
        wav_path.unlink(missing_ok=True)
    return output


def group_dialogue(
    lines: list[DialogueLine], max_span: float = 25.0, max_chars: int = 650
) -> list[SpeechChunk]:
    chunks: list[SpeechChunk] = []
    current: list[DialogueLine] = []

    def flush() -> None:
        if not current:
            return
        chunks.append(
            SpeechChunk(
                index=len(chunks) + 1,
                start=current[0].start,
                end=current[-1].end,
                text=" ".join(line.translation.strip() for line in current),
                voice=current[0].voice,
                speaker=current[0].speaker,
            )
        )
        current.clear()

    for line in lines:
        proposed_chars = sum(len(item.translation) + 1 for item in current) + len(line.translation)
        proposed_span = line.end - current[0].start if current else line.duration
        gap = line.start - current[-1].end if current else 0
        voice_changed = current and (
            line.voice != current[0].voice or line.speaker != current[0].speaker
        )
        if current and (
            proposed_span > max_span or proposed_chars > max_chars or gap > 2.5 or voice_changed
        ):
            flush()
        current.append(line)
    flush()
    return chunks


def synthesize_piper(
    text: str,
    output: Path,
    models_dir: Path,
    voice_name: str = "vi-piper-vais1000-medium",
    speaker_id: int | None = None,
) -> Path:
    model_key = voice_name.removeprefix("vi-piper-")
    model, config = _ensure_piper_model(models_dir, model_key)
    wav_path = output.with_suffix(".wav")
    try:
        with wave.open(str(wav_path), "wb") as wav_file:
            synthesis = SynthesisConfig(speaker_id=speaker_id, length_scale=1.0)
            _piper_voice(str(model), str(config)).synthesize_wav(text, wav_file, synthesis)
        run([
            "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(output),
        ])
    except (OSError, RuntimeError, ValueError, PipelineError) as exc:
        raise PipelineError(f"Piper TTS local that bai: {exc}") from exc
    finally:
        if wav_path.exists():
            wav_path.unlink()
    return output


@lru_cache(maxsize=2)
def _piper_voice(model: str, config: str) -> PiperVoice:
    return PiperVoice.load(model, config)


def _ensure_piper_model(
    models_dir: Path, model_key: str = "vais1000-medium"
) -> tuple[Path, Path]:
    if model_key not in PIPER_VOICES:
        raise PipelineError(f"Piper voice khong hop le: {model_key}")
    model_name, repository_path = PIPER_VOICES[model_key]
    models_dir.mkdir(parents=True, exist_ok=True)
    model = models_dir / f"{model_name}.onnx"
    config = models_dir / f"{model_name}.onnx.json"
    for path, suffix in ((model, ".onnx"), (config, ".onnx.json")):
        if path.exists() and path.stat().st_size > 0:
            continue
        url = f"{PIPER_REPOSITORY}/{repository_path}/{model_name}{suffix}"
        temporary = path.with_suffix(path.suffix + ".part")
        try:
            with requests.get(url, stream=True, timeout=(15, 300)) as response:
                response.raise_for_status()
                with temporary.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            stream.write(chunk)
            temporary.replace(path)
        except (requests.RequestException, OSError) as exc:
            if temporary.exists():
                temporary.unlink()
            raise PipelineError(f"Khong tai duoc Piper voice model: {exc}") from exc
    return model, config


def _atempo(value: float) -> str:
    factors: list[float] = []
    while value > 2.0:
        factors.append(2.0)
        value /= 2.0
    factors.append(max(0.5, value))
    return ",".join(f"atempo={factor:.4f}" for factor in factors)
