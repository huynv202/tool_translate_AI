from fastapi.testclient import TestClient

from viet_transform.web import app

client = TestClient(app)


def test_home_and_health() -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "Viet Transform Studio" in home.text
    assert 'href="/translate"' in home.text
    assert 'href="/storytelling"' in home.text
    assert client.get("/api/health").json() == {"status": "ok"}


def test_home_uses_single_video_editor_flow() -> None:
    studio = client.get("/translate")
    assert studio.status_code == 200
    assert 'id="videoFile" accept="video/*">' in studio.text
    assert 'id="batchBox" hidden' in studio.text
    assert "XUẤT VIDEO" in studio.text
    assert '<option value="localization" selected>Dịch và lồng tiếng · theo audio gốc</option>' in studio.text


def test_storytelling_has_independent_view_and_hybrid_assets() -> None:
    story = client.get("/storytelling")
    assert story.status_code == 200
    assert 'id="storyNarration"' in story.text
    assert 'id="storyContext" class="narration-input"' in story.text
    assert "AI SCRIPTWRITER" in story.text
    assert 'id="manualNarrationToggle"' in story.text
    assert 'id="storyImages"' in story.text
    assert 'value="hybrid" checked' in story.text
    assert 'href="/translate"' in story.text


def test_storytelling_generates_normalized_storyboard(monkeypatch) -> None:
    from types import SimpleNamespace

    from viet_transform import web

    content = (
        '{"title":"Chuyen trong mua","hook":"Mot dem bat thuong",'
        '"visual_bible":{"characters":"Lan","world":"Pho cu","palette":"xanh",'
        '"style":"dien anh"},"scenes":[{"id":7,"narration":"Lan buoc ra ngoai.",'
        '"duration_seconds":7,"uploaded_image":null,"image_prompt":"Lan trong mua",'
        '"composition":"center","transition":"fade"}]}'
    )

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )))

    monkeypatch.setattr(web, "OpenAI", Client)
    response = client.post("/api/storytelling/storyboard", json={
        "api_key": "key", "base_url": "http://localhost/v1", "model": "gpt-test",
        "context": "Lan di trong mua va tim thay mot ngoi nha cu.",
        "duration_seconds": 60, "asset_mode": "hybrid",
    })

    assert response.status_code == 200
    scene = response.json()["scenes"][0]
    assert scene["id"] == 1
    assert scene["needs_generation"] is True
    assert response.json()["full_narration"] == "Lan buoc ra ngoai."


def test_create_job_requires_source() -> None:
    response = client.post(
        "/api/jobs",
        data={
            "router_api_key": "test-key",
            "router_base_url": "http://localhost:20128/v1",
            "text_model": "test-model",
            "script_model": "gpt-test-model",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Hay upload video hoac nhap URL"


def test_router_probe_rejects_invalid_url() -> None:
    response = client.post(
        "/api/router/models",
        json={"api_key": "test-key", "base_url": "not-a-url"},
    )
    assert response.status_code == 422


def test_editorial_brief_fills_creator_fields(monkeypatch) -> None:
    from types import SimpleNamespace

    from viet_transform import web

    content = (
        '{"thesis":"Luan diem rieng","vietnam_angle":"Goc nhin Viet Nam",'
        '"hook":"Hook mo dau","structure":["Dat van de","Bang chung"],'
        '"research_queries":["Can kiem tra dieu gi?"]}'
    )

    class Client:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )))

    monkeypatch.setattr(web, "OpenAI", Client)
    response = client.post("/api/editorial/brief", json={
        "api_key": "key", "base_url": "http://localhost/v1", "model": "claude-test",
        "topic": "Livestream ban hang tai Trung Quoc", "description": "So sanh voi Viet Nam",
    })

    assert response.status_code == 200
    assert response.json()["thesis"] == "Luan diem rieng"


def test_job_requires_gemini_model() -> None:
    response = client.post(
        "/api/jobs",
        data={
            "source_url": "https://example.com/video.mp4",
            "router_api_key": "test-key",
            "router_base_url": "http://localhost:20128/v1",
            "text_model": "gpt-4.1-mini",
            "script_model": "gpt-4.1-mini",
        },
    )
    assert response.status_code == 422
    assert "Gemini" in response.json()["detail"]


def test_job_accepts_claude_as_script_model(monkeypatch) -> None:
    from viet_transform import web

    monkeypatch.setattr(web, "_run_job", lambda *args, **kwargs: None)
    response = client.post(
        "/api/jobs",
        data={
            "source_url": "https://example.com/video.mp4",
            "router_api_key": "test-key",
            "router_base_url": "http://localhost:20128/v1",
            "text_model": "gemini-test-model",
            "script_model": "claude-test-model",
        },
    )
    assert response.status_code == 202
    job = web.store.get(response.json()["job_id"])
    assert job.options.content_mode == "localization"
    assert job.options.render.trim_seconds == 0.0


def test_creator_analysis_accepts_optional_thesis(monkeypatch) -> None:
    from viet_transform import web

    monkeypatch.setattr(web, "_run_job", lambda *args, **kwargs: None)
    response = client.post(
        "/api/jobs",
        data={
            "source_url": "https://example.com/video.mp4",
            "router_api_key": "test-key",
            "router_base_url": "http://localhost:20128/v1",
            "text_model": "gemini-test-model",
            "script_model": "claude-test-model",
            "content_mode": "creator-analysis",
        },
    )
    assert response.status_code == 202
    job = web.store.get(response.json()["job_id"])
    assert job.options.editorial_thesis == ""


def test_creator_analysis_stores_editorial_profile(monkeypatch) -> None:
    from viet_transform import web

    monkeypatch.setattr(web, "_run_job", lambda *args, **kwargs: None)
    response = client.post(
        "/api/jobs",
        data={
            "source_url": "https://example.com/video.mp4",
            "router_api_key": "test-key",
            "router_base_url": "http://localhost:20128/v1",
            "text_model": "gemini-test-model",
            "script_model": "claude-test-model",
            "content_mode": "creator-analysis",
            "editorial_thesis": "Vi sao mo hinh nay khong the sao chep nguyen ban?",
            "vietnam_angle": "So sanh voi nguoi dung Viet Nam",
            "research_sources": "https://example.com/a\nhttps://example.com/b",
        },
    )
    assert response.status_code == 202
    job = web.store.get(response.json()["job_id"])
    assert job.options.content_mode == "creator-analysis"
    assert len(job.options.research_sources) == 2


def test_chunked_upload_is_reassembled(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from viet_transform import web

    monkeypatch.setattr(web, "UPLOADS_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(web, "UPLOAD_CHUNK_SIZE", 4)
    monkeypatch.setattr(web.shutil, "disk_usage", lambda _: SimpleNamespace(free=10**12))
    payload = b"abcdefghij"
    initialized = client.post(
        "/api/uploads",
        json={"filename": "long.mp4", "size": len(payload), "content_type": "video/mp4"},
    )
    assert initialized.status_code == 200
    upload_id = initialized.json()["upload_id"]
    for index, chunk in enumerate((payload[:4], payload[4:8], payload[8:])):
        response = client.put(f"/api/uploads/{upload_id}/{index}", content=chunk)
        assert response.status_code == 200
    completed = client.post(f"/api/uploads/{upload_id}/complete")
    assert completed.status_code == 200
    assert (tmp_path / "uploads" / upload_id / "source.mp4").read_bytes() == payload


def test_voice_catalog_contains_long_video_local_voice() -> None:
    voices = client.get("/api/voices").json()["voices"]
    assert any(voice["engine"] == "piper" for voice in voices)


def test_job_public_payload_contains_structured_logs() -> None:
    from viet_transform.web import Job

    job = Job(id="log-test")
    job.add_log("Bat dau thu nghiem", stage="Test")
    payload = job.public()
    assert payload["logs"][0]["stage"] == "Test"
    assert payload["logs"][0]["message"] == "Bat dau thu nghiem"


def test_ready_job_exposes_preview_without_final_video(tmp_path) -> None:
    from viet_transform.web import Job

    work_dir = tmp_path / "artifacts"
    work_dir.mkdir()
    (work_dir / "source.mp4").write_bytes(b"draft")
    (work_dir / "voiceover.mp3").write_bytes(b"voice")
    (work_dir / "voiceover.srt").write_text("subtitle", encoding="utf-8")
    job = Job(id="editor-test", status="ready", work_dir=work_dir)

    payload = job.public()

    assert payload["preview_url"].startswith("/api/jobs/editor-test/preview")
    assert payload["voice_url"].startswith("/api/jobs/editor-test/voice")
    assert payload["video_url"] is None
    assert set(payload["capcut_assets"]) == {"video", "voice", "subtitles"}


def test_capcut_assets_download_as_separate_tracks(tmp_path) -> None:
    from viet_transform import web

    job = web.store.create()
    job.work_dir = tmp_path / job.id
    job.work_dir.mkdir()
    (job.work_dir / "source.mp4").write_bytes(b"video track")
    (job.work_dir / "voiceover.mp3").write_bytes(b"voice track")
    (job.work_dir / "voiceover.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chao\n", encoding="utf-8")

    video = client.get(f"/api/jobs/{job.id}/assets/video")
    voice = client.get(f"/api/jobs/{job.id}/assets/voice")
    subtitles = client.get(f"/api/jobs/{job.id}/assets/subtitles")

    assert video.content == b"video track"
    assert voice.content == b"voice track"
    assert "Xin chao" in subtitles.text
    assert f'{job.id}-video.mp4' in video.headers["content-disposition"]
    assert f'{job.id}-voice.mp3' in voice.headers["content-disposition"]
    assert f'{job.id}-subtitles.srt' in subtitles.headers["content-disposition"]


def test_prepare_job_stops_before_render(monkeypatch, tmp_path) -> None:
    from viet_transform import web
    from viet_transform.config import Settings
    from viet_transform.pipeline import PipelineOptions

    monkeypatch.setattr(web, "prepare", lambda *args, **kwargs: tmp_path / "source.mp4")
    monkeypatch.setattr(
        web,
        "prepare_render_assets",
        lambda *args, **kwargs: (tmp_path / "voice.mp3", tmp_path / "voice.srt"),
    )
    job = web.Job(id="draft-only")
    options = PipelineOptions("source.mp4", tmp_path / "final.mp4", tmp_path / "work")
    settings = Settings(
        "key", "http://localhost/v1", "gemini-test", "claude-test", "small",
        "voice", "+0%", "piper", None, None, tmp_path, "Montserrat",
    )

    web._run_prepare(job, options, settings)

    assert job.status == "ready"
    assert job.output is None
    assert job.stages["Tao giong doc"] == "pending"
    assert job.stages["Render video"] == "pending"


def test_update_single_cue_keeps_cached_clips_and_skips_render(monkeypatch, tmp_path) -> None:
    from viet_transform import web
    from viet_transform.config import Settings
    from viet_transform.dialogue import DialogueLine, load_dialogue, save_dialogue
    from viet_transform.pipeline import PipelineOptions

    job = web.store.create()
    job.status = "ready"
    job.work_dir = tmp_path / job.id
    job.work_dir.mkdir()
    clips_dir = job.work_dir / "voice-clips"
    clips_dir.mkdir()
    cached_clip = clips_dir / "unchanged.mp3"
    cached_clip.write_bytes(b"cached")
    (job.work_dir / "voiceover.mp3").write_bytes(b"old voice")
    (job.work_dir / "voiceover.srt").write_text("old subtitle", encoding="utf-8")
    save_dialogue([
        DialogueLine(1, 0.0, 1.0, "source one", "Cue one"),
        DialogueLine(2, 1.0, 2.0, "source two", "Cue two"),
    ], job.work_dir / "dialogue.translated.json")
    job.options = PipelineOptions("source.mp4", job.work_dir / "final.mp4", job.work_dir)
    job.settings = Settings(
        "key", "http://localhost/v1", "gemini-test", "claude-test", "small",
        "voice", "+0%", "edge", None, None, tmp_path, "Montserrat",
    )
    called: list[int] = []
    monkeypatch.setattr(web, "_run_cue_update", lambda *args: called.append(args[-1]))

    response = client.post(f"/api/jobs/{job.id}/cues/2", json={
        "start": 1.1, "end": 2.2, "translation": "Cue hai da sua",
        "voice": "vi-VN-NamMinhNeural", "speaker": 2,
    })

    assert response.status_code == 202
    lines = load_dialogue(job.work_dir / "dialogue.translated.json")
    assert lines[0].translation == "Cue one"
    assert lines[1].translation == "Cue hai da sua"
    assert lines[1].voice == "vi-VN-NamMinhNeural"
    assert not (job.work_dir / "voiceover.mp3").exists()
    assert not (job.work_dir / "voiceover.srt").exists()
    assert cached_clip.read_bytes() == b"cached"
    assert not (job.work_dir / "final.mp4").exists()
    assert called == [2]


def test_render_skips_empty_cues_and_accepts_short_spoken_cues(monkeypatch, tmp_path) -> None:
    from viet_transform import web
    from viet_transform.config import Settings
    from viet_transform.dialogue import DialogueLine, load_dialogue, save_dialogue
    from viet_transform.pipeline import PipelineOptions

    job = web.store.create()
    job.status = "ready"
    job.work_dir = tmp_path / job.id
    job.work_dir.mkdir()
    dialogue_path = job.work_dir / "dialogue.translated.json"
    save_dialogue([
        DialogueLine(42, 10.0, 10.3, "source 42", "Cue ngan"),
        DialogueLine(43, 10.3, 10.7, "source 43", ""),
        DialogueLine(44, 10.7, 12.0, "source 44", "Cue sau"),
    ], dialogue_path)
    job.options = PipelineOptions("source.mp4", job.work_dir / "final.mp4", job.work_dir)
    job.settings = Settings(
        "key", "http://localhost/v1", "gemini-test", "claude-test", "small",
        "voice", "+0%", "edge", None, None, tmp_path, "Montserrat",
    )
    called: list[str] = []
    monkeypatch.setattr(web, "_run_render", lambda *args: called.append("render"))

    response = client.post(f"/api/jobs/{job.id}/render", json={"cues": [
        {"id": 42, "start": 10.0, "end": 10.3, "translation": "Cue ngan"},
        {"id": 43, "start": 10.3, "end": 10.7, "translation": ""},
        {"id": 44, "start": 10.7, "end": 12.0, "translation": "Cue sau"},
    ]})

    assert response.status_code == 202
    lines = load_dialogue(dialogue_path)
    assert [(line.id, line.translation) for line in lines] == [
        (1, "Cue ngan"), (2, "Cue sau"),
    ]
    assert called == ["render"]


def test_run_cue_update_rebuilds_only_voice_assets(monkeypatch, tmp_path) -> None:
    from viet_transform import web
    from viet_transform.config import Settings
    from viet_transform.pipeline import PipelineOptions

    job = web.Job(id="cue-worker", status="ready", work_dir=tmp_path)
    options = PipelineOptions("source.mp4", tmp_path / "final.mp4", tmp_path)
    settings = Settings(
        "key", "http://localhost/v1", "gemini-test", "claude-test", "small",
        "voice", "+0%", "edge", None, None, tmp_path, "Montserrat",
    )

    def rebuild(*args, **kwargs):
        (tmp_path / "voiceover.mp3").write_bytes(b"new voice")
        (tmp_path / "voiceover.srt").write_text("new subtitle", encoding="utf-8")

    monkeypatch.setattr(web, "prepare_render_assets", rebuild)
    web._run_cue_update(job, options, settings, 7)

    assert job.status == "ready"
    assert job.phase == "cue"
    assert job.revision == 1
    assert (tmp_path / "voiceover.mp3").read_bytes() == b"new voice"
    assert not (tmp_path / "final.mp4").exists()


def test_youtube_readiness_blocks_missing_rights(tmp_path) -> None:
    from viet_transform import web
    from viet_transform.dialogue import DialogueLine, save_dialogue

    job = web.store.create()
    job.work_dir = tmp_path / job.id
    job.work_dir.mkdir()
    (job.work_dir / "source.mp4").write_bytes(b"preview")
    save_dialogue([
        DialogueLine(index, index * 2.0, index * 2.0 + 1.5, "source", "Noi dung bien tap")
        for index in range(1, 7)
    ], job.work_dir / "dialogue.translated.json")

    response = client.post(
        f"/api/jobs/{job.id}/youtube-readiness",
        json={"rights_basis": "unknown", "original_commentary": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "blocked"
    assert any(item["gate"] == "rights" for item in payload["blockers"])


def test_youtube_readiness_never_promises_monetization(tmp_path) -> None:
    from viet_transform import web
    from viet_transform.dialogue import DialogueLine, save_dialogue

    job = web.store.create()
    job.work_dir = tmp_path / job.id
    job.work_dir.mkdir()
    (job.work_dir / "source.mp4").write_bytes(b"preview")
    save_dialogue([
        DialogueLine(index, (index - 1) * 2.0, index * 2.0, "source", "Hook va phan tich rieng")
        for index in range(1, 7)
    ], job.work_dir / "dialogue.translated.json")
    response = client.post(f"/api/jobs/{job.id}/youtube-readiness", json={
        "rights_basis": "licensed", "evidence_saved": True, "original_commentary": True,
        "multiple_sources": True, "fact_checked": True, "synthetic_disclosure_reviewed": True,
        "advertiser_friendly_reviewed": True, "thumbnail_accurate": True,
        "metadata_ready": True, "end_screen_ready": True,
    })

    assert response.status_code == 200
    assert "khong dam bao" in response.json()["disclaimer"].lower()
