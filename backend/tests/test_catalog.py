"""Catalog loading + tolerant resolvers."""

from __future__ import annotations

from app.data.catalog import catalog


def test_catalog_loaded():
    assert catalog.default_asset_id == "PL45LM-01"
    assert catalog.machine("PL45LM-01") is not None
    assert len(catalog.parts) >= 10
    assert len(catalog.fasteners) >= 5
    assert set(catalog.diagram_types()) == {"spindle", "turret", "axes"}


def test_resolve_part_voice_phrasings():
    for phrase in ["drawbar", "draw bar", "DRAW-BAR", " pull bar "]:
        resolved = catalog.resolve_part(phrase)
        assert resolved and resolved[0] == "drawbar"


def test_resolve_fastener_plural_and_spacing():
    resolved = catalog.resolve_fastener("tool holder bolts")
    assert resolved and resolved[0] == "tool_holder_bolt"


def test_resolve_procedure_and_check_and_diagram():
    assert catalog.resolve_procedure("change tool")[0] == "tool_change"
    assert catalog.resolve_check("lockout tagout")[0] == "loto"
    assert catalog.resolve_diagram("spindle assembly")[0] == "spindle"


def test_resolve_matches_on_word_boundaries_not_substrings():
    # A short alias ("ppe") must NOT fire from inside a longer word ("dro-ppe-r", "sw-appe-d") —
    # this is the ASR-false-positive class that popped the PPE checklist uninvited.
    assert catalog.resolve_check("what's the part number for the dropper") is None
    assert catalog.resolve_check("i swapped the tool holder") is None
    # real standalone aliases still resolve (whole word, and the norm-in-phrase direction)
    assert catalog.resolve_check("is my ppe okay")[0] == "ppe"
    assert catalog.resolve_check("run the loto check")[0] == "loto"
    assert catalog.resolve_check("pre-start")[0] == "pre_start"


def test_resolve_component_across_and_within_diagram():
    assert catalog.resolve_component("spindle", "draw bar")[0] == "drawbar"
    # target resolvable even without naming the diagram
    assert catalog.resolve_component("", "x ballscrew")[0] == "x_ballscrew"


def test_unknown_returns_none():
    assert catalog.resolve_part("flux capacitor") is None
    assert catalog.resolve_fastener("warp coil") is None
    assert catalog.resolve_asset("NOPE-99") is None


def test_ai4i_row_is_real_overstrain_data():
    row = catalog.ai4i_row(70)
    assert row is not None
    assert row["OSF"] == "1"
    assert float(row["Torque [Nm]"]) == 65.7
    assert float(row["Tool wear [min]"]) == 191
