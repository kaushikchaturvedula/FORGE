"""Qwen Cloud connector inventory.

FORGE's production realtime bridge talks the DashScope realtime WebSocket protocol
directly ([`session.py`](session.py)) because it needs fine-grained control over the
tool/image events and the per-transfer ``session.update`` swaps. Two idiomatic Qwen
connectors are *also* supported when installed, and reported here for transparency:

  * the **DashScope Python SDK** (`dashscope.audio.qwen_omni.OmniRealtimeConversation`),
  * **AgentScope**'s realtime model (`agentscope.realtime.DashScopeRealtimeModel`),
    Alibaba's agent framework.

This module never imports those heavy packages at startup — it only probes whether they
are available (and their version), so the optic is honest without a dead hard dependency
or a risk to the container build.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util


def _probe(module: str) -> dict[str, object]:
    spec = importlib.util.find_spec(module)
    available = spec is not None
    version = None
    if available:
        try:
            version = importlib.metadata.version(module)
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
    return {"available": available, "version": version}


def connector_status() -> dict[str, object]:
    return {
        # The bridge always uses the direct DashScope realtime WebSocket client.
        "active": "dashscope-realtime-ws (direct)",
        "available": {
            "websockets_direct": {"available": True, "version": _probe("websockets")["version"]},
            "dashscope_sdk": _probe("dashscope"),
            "agentscope": _probe("agentscope"),
        },
    }
