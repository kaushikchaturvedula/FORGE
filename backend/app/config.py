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
    # qwen3.5-omni-plus-realtime has full tool support (the older flash variant's is
    # limited). Available on the international endpoint.
    realtime_model: str = Field(
        default="qwen3.5-omni-plus-realtime", alias="FORGE_REALTIME_MODEL"
    )
    voice: str = Field(default="Cherry", alias="FORGE_VOICE")

    # Turn detection: "server_vad" (broadly supported) or "semantic_vad" (qwen3.5+).
    vad_type: str = Field(default="server_vad", alias="FORGE_VAD_TYPE")

    # Realtime tool registration shape: "flat" ({type,name,description,parameters},
    # OpenAI-Realtime style) or "nested" ({type,function:{...}}). The session.updated echo
    # (logged at startup) tells you which the server accepted.
    tools_format: str = Field(default="flat", alias="FORGE_TOOLS_FORMAT")
    # Only sent when set (an unsupported field can nullify tool registration).
    tool_choice: str = Field(default="", alias="FORGE_TOOL_CHOICE")
    # Dump every raw realtime event to the log for protocol debugging.
    debug_events: bool = Field(default=False, alias="FORGE_DEBUG_EVENTS")

    # ── Tool-calling sidecar (the grounding backbone) ────────────────────────
    # A reliable DashScope chat-completions model does the function calling over the
    # bundled catalog; the realtime model speaks the grounded result it returns.
    sidecar_enabled: bool = Field(default=True, alias="FORGE_SIDECAR_ENABLED")
    sidecar_model: str = Field(default="qwen3.7-plus", alias="FORGE_SIDECAR_MODEL")

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
    def sidecar_base_url(self) -> str:
        # DashScope OpenAI-compatible endpoint for the chat-completions tool brain.
        host = "dashscope-intl" if self.region == "intl" else "dashscope"
        return f"https://{host}.aliyuncs.com/compatible-mode/v1"

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
