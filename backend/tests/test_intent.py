"""The trimmed transcript helpers (the deterministic per-tool `infer_tools` layer was removed —
the realtime model natively drives all tools now)."""

from __future__ import annotations

from app.agents.intent import _has_word, is_machine_switch


def test_machine_switch_detection():
    assert is_machine_switch("this is a different machine now")
    assert is_machine_switch("I've switched to a lathe")
    # not a switch
    assert not is_machine_switch("what's on this machine")
    assert not is_machine_switch("show me the machine data")


def test_has_word_is_boundary_aware():
    # the Phase-1 discipline: short tokens can't match inside a longer word
    assert not _has_word("dropper", "ppe")
    assert not _has_word("i swapped the tool holder", "ppe")
    assert _has_word("is my ppe okay", "ppe")
    assert _has_word("run the loto check", "loto", "lockout")
    assert _has_word("run the pre-start check", "pre-start")
