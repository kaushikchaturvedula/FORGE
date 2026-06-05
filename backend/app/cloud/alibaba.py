"""Alibaba Cloud integration — OSS (oss2) + deployment-proof health endpoint.

This module is the concrete proof that FORGE runs on Alibaba Cloud:
  * it reads static assets (the CNC video, large schematics) from an Alibaba Cloud
    OSS bucket via the official ``oss2`` SDK, and
  * it exposes ``GET /cloud/health`` returning the live OSS bucket region and the
    DashScope (Model Studio) region the realtime model is served from.

Credentials come only from env vars (``ALIBABA_CLOUD_ACCESS_KEY_ID`` /
``ALIBABA_CLOUD_ACCESS_KEY_SECRET`` / ``OSS_*``). ``oss2`` is imported lazily so the
app still boots (and ``/cloud/health`` still reports status) before cloud creds or
the SDK are present.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter

from app.config import get_settings

logger = logging.getLogger("forge.cloud")
router = APIRouter(prefix="/cloud", tags=["cloud"])


def _bucket():
    """Construct an authenticated oss2 Bucket from env config (lazy import)."""
    settings = get_settings()
    if not settings.oss_configured:
        raise RuntimeError("OSS is not configured (set ALIBABA_CLOUD_* and OSS_* env vars).")
    import oss2  # lazy — keeps the app importable without the SDK/creds

    auth = oss2.Auth(settings.alibaba_cloud_access_key_id, settings.alibaba_cloud_access_key_secret)
    kwargs = {"region": settings.oss_region} if settings.oss_region else {}
    return oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket, **kwargs)


def read_object(key: str) -> bytes:
    """Read an object from the OSS bucket (used to pull bundled assets at startup)."""
    return _bucket().get_object(key).read()


def download_object(key: str, dest: str | Path) -> Path:
    """Download an OSS object to a local path (e.g. the CNC demo video)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _bucket().get_object_to_file(key, str(dest))
    logger.info("downloaded oss://%s/%s -> %s", get_settings().oss_bucket, key, dest)
    return dest


def put_object(key: str, data: bytes) -> None:
    _bucket().put_object(key, data)


def oss_status() -> dict[str, object]:
    """Live OSS status — region + reachability — for the proof endpoint."""
    settings = get_settings()
    status: dict[str, object] = {
        "configured": settings.oss_configured,
        "bucket": settings.oss_bucket,
        "endpoint": settings.oss_endpoint,
        "region": settings.oss_region,
        "reachable": False,
    }
    if not settings.oss_configured:
        status["detail"] = "OSS env vars not set."
        return status
    try:
        info = _bucket().get_bucket_info()
        status["reachable"] = True
        # get_bucket_info exposes the bucket's true region/location from Alibaba Cloud.
        status["region"] = getattr(info, "location", settings.oss_region)
        status["storage_class"] = getattr(info, "storage_class", None)
    except Exception as exc:  # noqa: BLE001 — report, don't crash the endpoint
        status["detail"] = f"{type(exc).__name__}: {exc}"
    return status


@router.get("/health")
def cloud_health() -> dict[str, object]:
    """Deployment proof: live Alibaba Cloud OSS region + DashScope region in use."""
    settings = get_settings()
    return {
        "provider": "Alibaba Cloud",
        "oss": oss_status(),
        "dashscope": {
            "configured": settings.realtime_configured,
            "region": settings.dashscope_region,
            "endpoint": settings.realtime_ws_url.split("?")[0],
            "model": settings.realtime_model,
        },
    }
