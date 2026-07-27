from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .errors import PipelineError


@dataclass(frozen=True)
class Settings:
    router_api_key: str | None
    router_base_url: str
    text_model: str
    script_model: str
    local_whisper_model: str
    tts_voice: str
    tts_rate: str
    tts_engine: str
    tts_speaker: int | None
    tts_reference: Path | None
    music_dir: Path
    font_name: str

    @classmethod
    def load(cls, env_file: Path | None = None) -> Settings:
        load_dotenv(env_file or ".env")
        return cls(
            router_api_key=os.getenv("9ROUTER_API_KEY") or None,
            router_base_url=os.getenv("9ROUTER_BASE_URL", "http://localhost:20128/v1").rstrip("/"),
            text_model=os.getenv("9ROUTER_TEXT_MODEL", "gpt-4.1-mini"),
            script_model=os.getenv("9ROUTER_SCRIPT_MODEL", "gpt-4.1-mini"),
            local_whisper_model=os.getenv("LOCAL_WHISPER_MODEL", "small"),
            tts_voice=os.getenv("TTS_VOICE", "vi-VN-HoaiMyNeural"),
            tts_rate=os.getenv("TTS_RATE", "+0%"),
            tts_engine=os.getenv("TTS_ENGINE", "auto"),
            tts_speaker=None,
            tts_reference=None,
            music_dir=Path(os.getenv("MUSIC_DIR", "./music")).expanduser(),
            font_name=os.getenv("FONT_NAME", "Montserrat"),
        )

    def validate_api_keys(self) -> None:
        if not self.router_api_key:
            raise PipelineError("Can 9ROUTER_API_KEY trong file .env.")
        if not self.router_base_url.startswith(("http://", "https://")):
            raise PipelineError("9ROUTER_BASE_URL phai bat dau bang http:// hoac https://.")
