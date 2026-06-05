"""FORGE configuration, loaded from environment / backend/.env.

All secrets come from env vars — nothing is committed. The realtime endpoint is
built from the region + model so a single constant change re-targets the model
(the international endpoint serves qwen3-omni-flash-realtime / qwen-omni-turbo-realtime;
the China endpoint also serves qwen3.5-omni-plus-realtime).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Realtime WebSocket endpoints per region (DashScope / Model Studio).
_WS_ENDPOINTS = {
    "intl": "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime",
    "cn": "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
}
_DASHSCOPE_REGION = {"intl": "ap-southeast-1 (Singapore)", "cn": "cn-beijing"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # ── Qwen Cloud / DashScope ───────────────────────────────────────────────
    dashscope_api_key: str = Field(default="", alias="DASHSCOPE_API_KEY")
    region: str = Field(default="intl", alias="FORGE_REGION")
    realtime_model: str = Field(
        default="qwen3-omni-flash-realtime", alias="FORGE_REALTIME_MODEL"
    )
    voice: str = Field(default="Cherry", alias="FORGE_VOICE")

    # Turn detection: "server_vad" (broadly supported) or "semantic_vad" (qwen3.5+).
    vad_type: str = Field(default="server_vad", alias="FORGE_VAD_TYPE")

    # Audio formats (Qwen-Omni-Realtime: input 16 kHz, output 24 kHz PCM16 mono;
    # the wire format value is "pcm").
    input_sample_rate: int = 16000
    output_sample_rate: int = 24000

    # ── Alibaba Cloud OSS (assets + deployment proof) ────────────────────────
    alibaba_cloud_access_key_id: str = Field(
        default="", alias="ALIBABA_CLOUD_ACCESS_KEY_ID"
    )
    alibaba_cloud_access_key_secret: str = Field(
        default="", alias="ALIBABA_CLOUD_ACCESS_KEY_SECRET"
    )
    oss_bucket: str = Field(default="", alias="OSS_BUCKET")
    oss_endpoint: str = Field(default="", alias="OSS_ENDPOINT")
    oss_region: str = Field(default="", alias="OSS_REGION")

    # ── Server ───────────────────────────────────────────────────────────────
    host: str = Field(default="0.0.0.0", alias="FORGE_HOST")
    port: int = Field(default=8000, alias="FORGE_PORT")
    allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="FORGE_ALLOWED_ORIGINS",
    )

    # Realtime session auto-closes near 120 min; resume a bit before that.
    session_resume_after_seconds: int = 115 * 60

    # ── Derived ──────────────────────────────────────────────────────────────
    @property
    def realtime_ws_url(self) -> str:
        base = _WS_ENDPOINTS.get(self.region, _WS_ENDPOINTS["intl"])
        return f"{base}?model={self.realtime_model}"

    @property
    def dashscope_region(self) -> str:
        return _DASHSCOPE_REGION.get(self.region, self.region)

    @property
    def realtime_configured(self) -> bool:
        return bool(self.dashscope_api_key)

    @property
    def oss_configured(self) -> bool:
        return bool(
            self.alibaba_cloud_access_key_id
            and self.alibaba_cloud_access_key_secret
            and self.oss_bucket
            and self.oss_endpoint
        )

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
