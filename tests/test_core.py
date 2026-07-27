from pathlib import Path
from types import SimpleNamespace

import pytest

from viet_transform.ai import _cached_json_completion, _validate_script
from viet_transform.dialogue import DialogueLine, apply_script, dialogue_srt, parse_json_response
from viet_transform.errors import PipelineError
from viet_transform.local_stt import (
    _chunk_ranges,
    _joins_boundary,
    _timestamp,
    _word_aligned_lines,
    normalize_model_name,
    transcribe_srt,
)
from viet_transform.source import is_url
from viet_transform.source_subtitles import parse_srt
from viet_transform.speech import group_dialogue, synthesize_dialogue
from viet_transform.subtitles import escape_filter_path, normalize_srt
from viet_transform.video import RenderOptions, _overlay_position, _watermark_filter, render


def test_source_detection() -> None:
    assert is_url("https://example.com/video")
    assert not is_url("./clip.mp4")


def test_normalize_srt() -> None:
    raw = "1\n00:00:00,000 --> 00:00:01,000\n Xin chao \n cac ban \n\n"
    assert normalize_srt(raw) == "1\n00:00:00,000 --> 00:00:01,000\nXin chao cac ban\n"


def test_escape_filter_path() -> None:
    escaped = escape_filter_path(Path("clip's.srt"))
    assert "\\'" in escaped


def test_script_length_guard() -> None:
    with pytest.raises(PipelineError):
        _validate_script("qua ngan")
    assert _validate_script(" ".join(["tu"] * 130))


def test_srt_timestamp() -> None:
    assert _timestamp(3661.234) == "01:01:01,234"


def test_long_audio_chunks_snap_to_nearby_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "viet_transform.local_stt._silence_points", lambda _: [19.4, 40.8, 61.2]
    )
    ranges = _chunk_ranges(Path("long.wav"), 75.0)
    assert ranges == [(0.0, 19.4), (19.4, 40.8), (40.8, 61.2), (61.2, 75.0)]


def test_long_audio_chunk_extends_when_speech_has_no_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("viet_transform.local_stt._silence_points", lambda _: [])
    assert _chunk_ranges(Path("speech.wav"), 65.0) == [
        (0.0, 30.0),
        (30.0, 60.0),
        (60.0, 65.0),
    ]


def test_speech_split_at_chunk_boundary_is_joined() -> None:
    previous = DialogueLine(1, 18.0, 19.9, "cau dang noi")
    current = DialogueLine(2, 20.1, 21.0, "tiep theo")
    assert _joins_boundary(previous, current, 20.0)
    previous.source = "da xong."
    assert not _joins_boundary(previous, current, 20.0)


def test_word_alignment_uses_absolute_chunk_offset() -> None:
    words = [
        SimpleNamespace(word="你好", start=0.2, end=0.8),
        SimpleNamespace(word="。", start=0.8, end=1.0),
        SimpleNamespace(word="走吧", start=1.5, end=2.1),
    ]
    lines = _word_aligned_lines([SimpleNamespace(words=words, text="")], 20.0, 30.0)
    assert [(line.start, line.end, line.source) for line in lines] == [
        (20.2, 21.0, "你好。"),
        (21.5, 22.1, "走吧"),
    ]


def test_legacy_whisper_model_is_migrated() -> None:
    assert normalize_model_name("whisper-1") == "small"
    with pytest.raises(PipelineError):
        normalize_model_name("unknown-model")


def test_render_ignores_empty_music_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.mp4"
    voice = tmp_path / "voice.mp3"
    subtitles = tmp_path / "voice.srt"
    music = tmp_path / "music.mp3"
    for path in (source, voice, subtitles, music):
        path.touch()
    captured: list[str] = []
    monkeypatch.setattr("viet_transform.video.duration", lambda _: 10.0)
    monkeypatch.setattr("viet_transform.video.run", lambda command: captured.extend(command))
    render(
        source,
        voice,
        subtitles,
        tmp_path / "final.mp4",
        "Montserrat",
        music,
        options=RenderOptions(width=360, height=640),
    )
    assert "-stream_loop" not in captured


def test_render_applies_editor_subtitle_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, voice, subtitles = (tmp_path / name for name in ("s.mp4", "v.mp3", "c.srt"))
    for path in (source, voice, subtitles):
        path.touch()
    captured: list[str] = []
    monkeypatch.setattr("viet_transform.video.duration", lambda _: 10.0)
    monkeypatch.setattr("viet_transform.video.run", lambda command: captured.extend(command))
    render(
        source,
        voice,
        subtitles,
        tmp_path / "out.mp4",
        "Montserrat",
        options=RenderOptions(
            subtitle_font_size=16,
            subtitle_color="yellow",
            brightness=0.1,
            contrast=1.2,
            saturation=1.3,
            voice_volume=0.8,
            audio_fade_in=1.0,
            audio_fade_out=1.5,
        ),
    )
    command = " ".join(captured)
    assert "FontSize=16" in command
    assert "PrimaryColour=&H0000FFFF" in command
    assert "eq=brightness=0.1:contrast=1.2:saturation=1.3" in command
    assert "volume=0.8" in command
    assert "afade=t=in:st=0:d=1.0" in command
    assert "afade=t=out:st=8.500:d=1.5" in command
    assert "veryfast" in captured
    assert "128k" in captured


def test_ai_batch_cache_avoids_duplicate_router_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from viet_transform.config import Settings

    calls: list[str] = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs["model"])
            message = SimpleNamespace(content='{"segments":[{"id":1,"translation":"Xin chao"}]}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr("viet_transform.ai._client", lambda _: client)
    settings = Settings(
        None, "http://localhost/v1", "gemini-test", "claude-test", "small",
        "vi-piper-vais1000-medium", "+0%", "piper", None, None, tmp_path, "Montserrat",
    )
    first = _cached_json_completion(
        settings, "claude-test", "prompt", "payload", 0.2, tmp_path / "cache", "adapt"
    )
    second = _cached_json_completion(
        settings, "claude-test", "prompt", "payload", 0.2, tmp_path / "cache", "adapt"
    )
    assert first == second
    assert calls == ["claude-test"]


def test_watermark_filter_uses_selected_corner() -> None:
    result = _watermark_filter(
        RenderOptions(width=1080, height=1920, watermark_position="top-left")
    )
    assert result == "delogo=x=19:y=19:w=270:h=144:show=0"


def test_logo_position_uses_safe_margin() -> None:
    assert _overlay_position("top-right") == ("W-w-24", "24")
    with pytest.raises(PipelineError):
        _overlay_position("center")


def test_subtitles_are_split_by_word_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    words = [
        SimpleNamespace(word=f" tu{i}", start=i * 0.4, end=(i + 1) * 0.4)
        for i in range(8)
    ]
    segment = SimpleNamespace(words=words)
    monkeypatch.setattr("viet_transform.local_stt._segments", lambda *args, **kwargs: [segment])
    srt = transcribe_srt(tmp_path / "voice.mp3", "small", "vi")
    assert "tu0 tu1 tu2 tu3 tu4 tu5" in srt
    assert "tu6 tu7" in srt
    assert srt.count("-->") == 2


def test_dialogue_translation_keeps_timeline_and_line_count() -> None:
    lines = [
        DialogueLine(id=1, start=1.0, end=3.0, source="你好", translation="Xin chào bạn nhé"),
        DialogueLine(id=2, start=4.0, end=5.0, source="走吧", translation="Đi thôi"),
    ]
    srt = dialogue_srt(lines)
    assert "00:00:01,000 --> 00:00:03,000" in srt
    assert "Xin chào bạn nhé" in srt
    apply_script(lines, "Chào bạn nha\nĐi nào")
    assert lines[0].translation == "Chào bạn nha"
    with pytest.raises(PipelineError):
        apply_script(lines, "Chỉ còn một dòng")


def test_dialogue_json_accepts_wrapped_payload() -> None:
    result = parse_json_response('```json\n{"segments":[{"id":1,"translation":"Xin chào"}]}\n```')
    assert result[0]["translation"] == "Xin chào"


def test_embedded_srt_is_parsed_with_from_to() -> None:
    content = (
        "1\n00:00:01,250 --> 00:00:03,500\n<i>你好</i>\n\n"
        "2\n00:00:04,000 --> 00:00:05,100\n走吧\n"
    )
    lines = parse_srt(content)
    assert [(line.start, line.end, line.source) for line in lines] == [
        (1.25, 3.5, "你好"),
        (4.0, 5.1, "走吧"),
    ]


def test_long_dialogue_is_grouped_into_resumable_tts_chunks() -> None:
    lines = [
        DialogueLine(
            id=index,
            start=float(index - 1),
            end=float(index),
            source=f"source {index}",
            translation=f"Cau thoai thu {index}.",
        )
        for index in range(1, 61)
    ]
    chunks = group_dialogue(lines, max_span=20)
    assert len(chunks) == 3
    assert chunks[0].start == 0
    assert chunks[-1].end == 60
    assert all(chunk.duration <= 20 for chunk in chunks)


def test_dialogue_voice_change_starts_new_speech_chunk() -> None:
    lines = [
        DialogueLine(1, 0, 2, "a", "Mot", voice="vi-piper-vais1000-medium"),
        DialogueLine(2, 2, 4, "b", "Hai", voice="vi-VN-NamMinhNeural"),
    ]
    chunks = group_dialogue(lines)
    assert [chunk.voice for chunk in chunks] == [
        "vi-piper-vais1000-medium",
        "vi-VN-NamMinhNeural",
    ]


def test_xtts_auto_falls_back_to_piper_instead_of_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from viet_transform.config import Settings

    lines = [DialogueLine(id=1, start=0, end=2, source="你好", translation="Xin chao")]
    called: list[str] = []
    command: list[str] = []
    settings = Settings(
        router_api_key=None,
        router_base_url="http://localhost/v1",
        text_model="gemini-test",
        script_model="gpt-test",
        local_whisper_model="small",
        tts_voice="xtts-auto",
        tts_rate="+0%",
        tts_engine="auto",
        tts_speaker=None,
        tts_reference=None,
        music_dir=tmp_path,
        font_name="Montserrat",
    )
    monkeypatch.setattr("viet_transform.speech.xtts_ready", lambda: False)
    monkeypatch.setattr(
        "viet_transform.speech.synthesize_piper",
        lambda text, output, *args, **kwargs: (output.write_bytes(b"audio"), called.append(text)),
    )
    monkeypatch.setattr("viet_transform.speech.duration", lambda _: 1.0)
    monkeypatch.setattr("viet_transform.speech.run", lambda value: command.extend(value))
    synthesize_dialogue(lines, tmp_path / "voice.mp3", settings, tmp_path)
    assert called == ["Xin chao"]
    filter_script = Path(command[command.index("-filter_complex_script") + 1])
    assert "concat=n=1:v=0:a=1" in filter_script.read_text(encoding="utf-8")
