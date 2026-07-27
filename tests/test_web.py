from fastapi.testclient import TestClient

from viet_transform.web import app

client = TestClient(app)


def test_home_and_health() -> None:
    home = client.get("/")
    assert home.status_code == 200
    assert "Viet Transform Studio" in home.text
    assert client.get("/api/health").json() == {"status": "ok"}


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
