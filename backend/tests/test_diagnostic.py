"""The off-loop diagnostic agent — pure prompt/parse logic (no network)."""

from __future__ import annotations

from app.agents import diagnostic


def test_build_messages_carries_grounded_inputs():
    inputs = {
        "threshold_breaches": ["spindle_torque 65.0 Nm over caution limit 60"],
        "open_faults": [{"fault_id": "F-2218", "symptom": "tool-unclamp delay"}],
        "machine": {"model": "PL45LM Turn-Mill"},
    }
    msgs = diagnostic.build_messages(inputs)
    assert msgs[0]["role"] == "system" and "JSON" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "65" in user and "F-2218" in user and "PL45LM" in user  # real values, not placeholders


def test_parse_diagnosis_extracts_fenced_json():
    text = '```json\n{"root_cause": "drawbar unclamp delay", "confidence": "High", ' \
           '"recommended_action": "inspect the unclamp cylinder", "evidence": "F-2218; torque 65"}\n```'
    out = diagnostic.parse_diagnosis(text)
    assert out["root_cause"] == "drawbar unclamp delay"
    assert out["confidence"] == "high"           # normalized
    assert out["recommended_action"].startswith("inspect")
    assert "F-2218" in out["evidence"]


def test_parse_diagnosis_defaults_confidence():
    out = diagnostic.parse_diagnosis('{"root_cause": "x", "recommended_action": "y"}')
    assert out["confidence"] == "med"            # missing/invalid -> med
    assert out["evidence"] == ""


def test_parse_diagnosis_rejects_garbage():
    assert diagnostic.parse_diagnosis("the spindle seems fine, no JSON here") is None
    assert diagnostic.parse_diagnosis("") is None
    assert diagnostic.parse_diagnosis('{"confidence": "high"}') is None  # no root_cause -> reject
