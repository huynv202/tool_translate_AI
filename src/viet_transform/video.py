from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import PipelineError
from .media import duration, run
from .subtitles import escape_filter_path


@dataclass(frozen=True)
class RenderOptions:
    width: int = 1080
    height: int = 1920
    trim_seconds: float = 0.0
    zoom: float = 1.06
    flip: bool = True
    music_volume: float = 0.12
    crf: int = 23
    preset: str = "veryfast"
    watermark_position: str = "top-left"
    logo_position: str = "top-right"
    logo_width: float = 0.16
    logo_opacity: float = 0.9
    cover_source_subtitles: bool = True
    subtitle_font_size: int = 11
    subtitle_margin: int = 110
    subtitle_color: str = "white"
    caption_opacity: float = 0.48
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    hue: float = 0.0
    blur: float = 0.0
    vignette: float = 0.0
    voice_volume: float = 1.0
    audio_fade_in: float = 0.0
    audio_fade_out: float = 0.0


def render(
    source: Path,
    voiceover: Path,
    subtitles: Path,
    output: Path,
    font_name: str,
    music: Path | None = None,
    logo: Path | None = None,
    options: RenderOptions | None = None,
) -> Path:
    options = options or RenderOptions()
    if music and (not music.is_file() or music.stat().st_size == 0):
        music = None
    if logo and (not logo.is_file() or logo.stat().st_size == 0):
        logo = None
    source_duration = duration(source)
    usable = source_duration - (2 * options.trim_seconds)
    if usable <= 0:
        raise PipelineError("Video qua ngan de cat dau va cuoi.")

    scale_w = int(options.width * options.zoom)
    scale_h = int(options.height * options.zoom)
    video_filters = [
        f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase",
        f"crop={options.width}:{options.height}",
        f"eq=brightness={options.brightness}:contrast={options.contrast}:saturation={options.saturation}",
    ]
    if options.hue:
        video_filters.append(f"hue=h={options.hue}")
    if options.blur:
        video_filters.append(f"gblur=sigma={options.blur}")
    if options.vignette:
        video_filters.append(f"vignette=PI/{max(2.0, 12.0 - options.vignette * 8):.2f}")
    if options.watermark_position != "none":
        video_filters.append(_watermark_filter(options))
    if options.flip:
        video_filters.append("hflip")
    if options.cover_source_subtitles:
        video_filters.append(_caption_band_filter(options))
    subtitle_colors = {
        "white": "&H00FFFFFF",
        "yellow": "&H0000FFFF",
        "cyan": "&H00FFFF00",
    }
    primary_color = subtitle_colors.get(options.subtitle_color, subtitle_colors["white"])
    background_alpha = round((1 - options.caption_opacity) * 255)
    style = (
        f"FontName={font_name},FontSize={options.subtitle_font_size},Bold=1,"
        f"PrimaryColour={primary_color},"
        f"BackColour=&H{background_alpha:02X}000000,"
        "OutlineColour=&H00000000,BorderStyle=3,Outline=3,Shadow=0,"
        f"Alignment=2,MarginV={options.subtitle_margin}"
    )
    video_filters.append(
        f"subtitles='{escape_filter_path(subtitles)}':force_style='{style}'"
    )

    command = [
        "ffmpeg", "-y", "-ss", str(options.trim_seconds), "-t", str(usable), "-i", str(source),
        "-i", str(voiceover),
    ]
    voice_duration = duration(voiceover)
    fade_out_start = max(0.0, voice_duration - options.audio_fade_out)
    voice_filters = [f"volume={options.voice_volume}"]
    if options.audio_fade_in > 0:
        voice_filters.append(f"afade=t=in:st=0:d={options.audio_fade_in}")
    if options.audio_fade_out > 0:
        voice_filters.append(
            f"afade=t=out:st={fade_out_start:.3f}:d={options.audio_fade_out}"
        )
    voice_chain = ",".join(voice_filters)
    if music:
        command += ["-stream_loop", "-1", "-i", str(music)]
        audio_filter = (
            f"[1:a]{voice_chain},loudnorm=I=-16:TP=-1.5:LRA=11,asplit=2[voice][side];"
            f"[2:a]volume={options.music_volume}[music];"
            "[music][side]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[ducked];"
            "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
    else:
        audio_filter = f"[1:a]{voice_chain},loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    logo_filter = ""
    video_output = "vout"
    if logo:
        logo_index = 3 if music else 2
        command += ["-i", str(logo)]
        logo_width = max(64, round(options.width * options.logo_width))
        x, y = _overlay_position(options.logo_position)
        logo_filter = (
            f";[{logo_index}:v]format=rgba,colorchannelmixer=aa={options.logo_opacity},"
            f"scale={logo_width}:-1[logo];[base][logo]overlay={x}:{y}:"
            "format=auto:eof_action=repeat[vout]"
        )
        video_output = "base"
    command += [
        "-filter_complex",
        f"[0:v]{','.join(video_filters)}[{video_output}]{logo_filter};{audio_filter}",
        "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", options.preset,
        "-crf", str(options.crf), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        "-shortest", str(output),
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    run(command)
    return output


def _overlay_position(position: str) -> tuple[str, str]:
    positions = {
        "top-left": ("24", "24"),
        "top-right": ("W-w-24", "24"),
        "bottom-left": ("24", "H-h-180"),
        "bottom-right": ("W-w-24", "H-h-180"),
    }
    if position not in positions:
        raise PipelineError("Vi tri logo khong hop le.")
    return positions[position]


def _caption_band_filter(options: RenderOptions) -> str:
    band_height = max(72, options.subtitle_font_size * 6)
    band_y = max(0, options.height - options.subtitle_margin - band_height)
    return (
        f"drawbox=x=0:y={band_y}:w=iw:h={band_height}:"
        f"color=black@{options.caption_opacity}:t=fill"
    )


def _watermark_filter(options: RenderOptions) -> str:
    width = max(120, round(options.width * 0.25))
    height = max(55, round(options.height * 0.075))
    padding = max(12, round(options.width * 0.018))
    positions = {
        "top-left": (padding, padding),
        "top-right": (options.width - width - padding, padding),
        "bottom-left": (padding, options.height - height - padding),
        "bottom-right": (options.width - width - padding, options.height - height - padding),
    }
    if options.watermark_position not in positions:
        raise PipelineError("Vi tri watermark khong hop le.")
    x, y = positions[options.watermark_position]
    return f"delogo=x={x}:y={y}:w={width}:h={height}:show=0"
