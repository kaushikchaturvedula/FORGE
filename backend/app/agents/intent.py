"""Server-side transcript helpers (word-boundary matching + machine-switch detection).

The realtime model is the SOLE driver of tools and the console UI — it emits native function
calls for everything. This module no longer infers tools from the transcript; it retains only
small deterministic helpers used elsewhere in the gateway/workflow layer:

  * ``_has`` / ``_has_word`` — substring / word-boundary membership (``workflows.py`` reuses
    ``_has``);
  * ``is_machine_switch`` — detects the tech announcing they've moved to a DIFFERENT machine, so
    the gateway can dim the header and clear the hero machine-data panel (a demo beat).
"""

from __future__ import annotations

import re


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def _has_word(text: str, *phrases: str) -> bool:
    """Like ``_has`` but WORD-BOUNDARY aware — so a short trigger ("ppe", "loto") can't fire from
    inside a longer word ("dro-ppe-r", "sw-appe-d")."""
    return any(re.search(rf"\b{re.escape(p)}\b", text) for p in phrases)


_SWITCH_PHRASES = ("different machine", "another machine", "new machine", "other machine",
                   "switched machine", "switch machines", "this is a different", "not the same machine",
                   "switched to a", "now on a different")


def is_machine_switch(text: str) -> bool:
    """The tech has clearly moved to a DIFFERENT machine than the loaded hero asset."""
    return _has((text or "").lower(), *_SWITCH_PHRASES)
