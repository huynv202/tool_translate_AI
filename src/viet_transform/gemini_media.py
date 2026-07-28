from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from google import genai
from google.genai import types

from .errors import PipelineError


def generate_scene_image(
    api_key: str,
    model: str,
    prompt: str,
    output: Path,
    aspect_ratio: str,
) -> Path:
    if not api_key.strip() or not model.strip() or not prompt.strip():
        raise PipelineError("Thieu Gemini key, model anh hoac prompt scene.")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = genai.Client(api_key=api_key).models.generate_images(
            model=model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio=aspect_ratio,
                output_mime_type="image/png",
                add_watermark=False,
                enhance_prompt=True,
            ),
        )
        generated = response.generated_images or []
        image_bytes = generated[0].image.image_bytes if generated and generated[0].image else None
        if not image_bytes:
            reason = generated[0].rai_filtered_reason if generated else "empty response"
            raise PipelineError(f"Gemini khong tao duoc anh scene: {reason}")
        output.write_bytes(image_bytes)
        return output
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError(f"Gemini tao anh scene that bai: {exc}") from exc


def generate_scene_video(
    api_key: str,
    model: str,
    prompt: str,
    output: Path,
    aspect_ratio: str,
    duration_seconds: int = 8,
    reference_image: Path | None = None,
    detail: Callable[[str], None] | None = None,
    poll_interval: float = 10.0,
    timeout_seconds: float = 900.0,
) -> Path:
    if not api_key.strip() or not model.strip() or not prompt.strip():
        raise PipelineError("Thieu Gemini key, model video hoac prompt scene.")
    if duration_seconds not in {4, 6, 8}:
        raise PipelineError("Clip Gemini chi ho tro duration 4, 6 hoac 8 giay trong studio.")
    output.parent.mkdir(parents=True, exist_ok=True)
    client = genai.Client(api_key=api_key)
    image = None
    if reference_image:
        image = types.Image(
            image_bytes=reference_image.read_bytes(),
            mime_type=_image_mime_type(reference_image),
        )
    try:
        operation = client.models.generate_videos(
            model=model,
            prompt=prompt,
            image=image,
            config=types.GenerateVideosConfig(
                number_of_videos=1,
                duration_seconds=duration_seconds,
                aspect_ratio=aspect_ratio,
                generate_audio=False,
                enhance_prompt=True,
            ),
        )
        deadline = time.monotonic() + timeout_seconds
        while not operation.done:
            if time.monotonic() >= deadline:
                raise PipelineError("Gemini tao video scene qua thoi gian cho phep.")
            if detail:
                detail("Gemini dang render clip scene...")
            time.sleep(poll_interval)
            operation = client.operations.get(operation)
        if operation.error:
            raise PipelineError(f"Gemini tao video scene that bai: {operation.error}")
        response = operation.response or operation.result
        videos = response.generated_videos if response else []
        if not videos:
            raise PipelineError("Gemini hoan tat nhung khong tra ve clip video.")
        video = videos[0]
        video_bytes = video.video.video_bytes if video.video else None
        if not video_bytes:
            video_bytes = client.files.download(file=video)
        if not video_bytes:
            raise PipelineError("Khong tai duoc byte cua clip Gemini.")
        output.write_bytes(video_bytes)
        return output
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError(f"Gemini tao video scene that bai: {exc}") from exc


def _image_mime_type(path: Path) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
