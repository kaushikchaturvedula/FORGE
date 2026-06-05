"""Before/after tool callbacks — the grounding gate around every tool call.

``execute_tool`` is the single entry point the gateway uses for data tools:

    before  → validate args against the catalog whitelists; reject out-of-catalog
              args with a spoken "I don't have that on file" (no handler runs).
    execute → run the grounded handler over the bundled catalog.
    after   → record tool metrics; surface handler errors as spoken fallbacks
              instead of crashing the session.

Transfers (transfer_to_*, return_to_orchestrator) are handled by the orchestrator,
not here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.session_state import SessionState
from app.agents.tools.handlers import HANDLERS, ToolResult
from app.grounding import whitelists as wl

logger = logging.getLogger("forge.grounding")


@dataclass
class ToolMetrics:
    count: int = 0
    last_tool: str = ""
    rejected: int = 0
    errors: int = 0


def before_tool(name: str, args: dict) -> wl.ValidationResult:
    """Grounding gate: validate arguments before any handler executes."""
    return wl.validate(name, args)


def after_tool(metrics: ToolMetrics, name: str, result: ToolResult) -> None:
    metrics.count += 1
    metrics.last_tool = name
    if result.output.get("error"):
        metrics.errors += 1


def execute_tool(
    state: SessionState, name: str, args: dict, metrics: ToolMetrics | None = None
) -> ToolResult:
    """Validate, execute, and record a single data-tool call."""
    metrics = metrics or ToolMetrics()
    args = args or {}

    verdict = before_tool(name, args)
    if not verdict.ok:
        metrics.rejected += 1
        metrics.count += 1
        metrics.last_tool = name
        logger.info("grounding rejected %s%s: %s", name, args, verdict.message)
        return ToolResult(
            output={"error": "rejected", "message": verdict.message},
        )

    handler = HANDLERS.get(name)
    if handler is None:
        logger.warning("no handler for tool %s", name)
        return ToolResult(output={"error": "unknown_tool", "message": f"I don't have a tool called {name}."})

    try:
        result = handler(state, args)
    except Exception as exc:  # never let a tool crash the live session
        logger.exception("tool %s failed", name)
        result = ToolResult(output={"error": "tool_failed", "message": f"Something went wrong running {name}."})

    after_tool(metrics, name, result)
    return result
