"""Keyword intent → tool inference (drives the console panels), and the embedded data."""

from __future__ import annotations

from app.agents.intent import auto_highlight, infer_tools
from app.data.catalog import catalog, catalog_brief


def _names(calls):
    return [n for n, _ in calls]


def test_torque_question_maps_to_lookup_torque():
    calls = infer_tools("what's the torque on the tool-holder bolts")
    assert ("lookup_torque", {"fastener_id": "tool_holder_bolt"}) in calls


def test_telemetry_question_maps_to_machine_data():
    assert ("show_machine_data", {"data_type": "telemetry"}) in infer_tools("what is the tool wear right now")


def test_brief_maps_to_nameplate():
    assert ("show_machine_data", {"data_type": "nameplate"}) in infer_tools("brief me on this machine")


def test_maintenance_and_faults():
    assert ("show_machine_data", {"data_type": "maintenance"}) in infer_tools("show the maintenance history")
    assert ("show_machine_data", {"data_type": "faults"}) in infer_tools("are there any open faults or alarms")


def test_schematic_and_navigate():
    calls = infer_tools("show me the spindle assembly and jump to the drawbar")
    assert "show_schematic" in _names(calls) and "navigate_schematic" in _names(calls)
    nav = next(a for n, a in calls if n == "navigate_schematic")
    assert nav["target"] == "drawbar"


def test_procedure_and_safety():
    assert ("start_procedure", {"procedure_id": "tool_change"}) in infer_tools("walk me through the tool change")
    assert ("run_safety_check", {"check_type": "loto"}) in infer_tools("run the lockout procedure")


def test_chitchat_and_other_equipment_infer_nothing():
    assert infer_tools("hello, how are you") == []
    assert infer_tools("can you help me with a forklift") == []


# ── new: hide/clear, 3D model, highlight, actions ───────────────────────────
def test_clear_and_hide_panels():
    assert ("hide_panel", {"panel": "all"}) in infer_tools("clear everything", {})
    assert ("hide_panel", {"panel": "all"}) in infer_tools("clear the screen", {})
    assert ("hide_panel", {"panel": "machine_data"}) in infer_tools("hide the machine data", {})
    assert ("hide_panel", {"panel": "model"}) in infer_tools("hide the 3d model", {})


def test_show_and_rotate_model_with_context_carry():
    ctx: dict = {}
    assert ("show_panel", {"panel": "model"}) in infer_tools("show me the 3d model", ctx)
    r1 = infer_tools("rotate the model 30 degrees", ctx)
    assert ("rotate_model", {"degrees": 30, "axis": "y"}) in r1
    # follow-up reuses the prior 30 degrees, switches axis
    r2 = infer_tools("on the x axis", ctx)
    assert ("rotate_model", {"degrees": 30, "axis": "x"}) in r2
    assert ("reset_view", {}) in infer_tools("reset the view", ctx)


def test_highlight_component_from_user():
    assert ("highlight_component", {"name": "drawbar"}) in infer_tools("where's the drawbar", {})
    assert ("highlight_component", {"name": "coolant_union"}) in infer_tools("point to the coolant union", {})
    # an explicit schematic request should NOT become a highlight
    assert "highlight_component" not in _names(infer_tools("show me the spindle assembly diagram", {}))


def test_record_log_photo_and_machine_switch():
    assert ("record_measurement", {"type": "spindle_torque", "value": 65.0, "unit": "Nm"}) \
        in infer_tools("record spindle torque 65 newton metres", {})
    logs = infer_tools("log that I replaced the coolant union", {})
    assert any(n == "log_event" and "coolant union" in a["note"] for n, a in logs)
    assert ("capture_photo", {}) in infer_tools("take a photo of this", {})
    assert ("hide_panel", {"panel": "machine_data"}) in infer_tools("this is a different machine now", {})


def test_auto_highlight_from_forge_speech():
    assert auto_highlight("the through-spindle coolant union is part PL45-SP-CU-020") == \
        ("highlight_component", {"name": "coolant_union", "reveal": False})
    assert auto_highlight("that's a clean cut, nice surface finish") is None


# ── regression guards (from the adversarial review) ─────────────────────────
def test_temperature_in_degrees_still_records():
    # "degrees" must NOT suppress a temperature measurement (only a real rotate does).
    r = infer_tools("record the process temperature at 40 degrees celsius", {})
    assert ("record_measurement", {"type": "process_temperature", "value": 40.0, "unit": "C"}) in r


def test_physical_action_does_not_rotate_the_model():
    for phrase in ["I had to turn it off and back on", "spin it up to operating speed",
                   "go ahead and turn the spindle by hand"]:
        names = _names(infer_tools(phrase, {}))
        assert "rotate_model" not in names and "show_panel" not in names, phrase


def test_hotspot_word_boundary_no_false_positives():
    from app.data.catalog import catalog
    assert catalog.resolve_hotspot("you should embed the part fully") is None
    assert catalog.resolve_hotspot("the seabed sample") is None
    assert auto_highlight("I embedded the sensor there") is None
    # but a real standalone word still resolves
    assert catalog.resolve_hotspot("check the bed for chips")[0] == "bed"


def test_inspect_does_not_trigger_specs():
    assert "show_machine_data" not in _names(infer_tools("let me inspect the chuck", {}))


def test_log_event_uses_event_type_key():
    logs = infer_tools("log that I replaced the seal", {})
    assert any(n == "log_event" and a.get("event_type") == "note" and "type" not in a for n, a in logs)


def test_access_layout_mis_transcription_resolves_to_axes():
    # gummy hears "axis layout" as "access layout" — the safety-net resolver must survive it
    assert catalog.resolve_diagram("the full access layout")[0] == "axes"
    assert ("show_schematic", {"diagram_type": "axes"}) in infer_tools("show me the full access layout schematic", {})


def test_resolve_hotspot_maps_real_svg_ids():
    for phrase, key in [("the drawbar", "drawbar"), ("tool changer", "turret"),
                        ("control panel", "control_box"), ("rotary union", "coolant_union")]:
        hit = catalog.resolve_hotspot(phrase)
        assert hit and hit[0] == key
        assert hit[1]["svg"] == f"cmp-{key}"


def test_catalog_brief_has_real_grounded_values():
    b = catalog_brief()
    assert "PL45LM Turn-Mill" in b
    assert "tool wear 191 min" in b          # telemetry
    assert "12 Nm" in b                       # tool-holder bolt torque
    assert "alert at 11000 minNm" in b        # overstrain threshold
    assert "LOTO" in b or "Lockout" in b      # safety
    # no secrets / no raw machine ids that read as math beyond the data block
    assert "DASHSCOPE" not in b and "ACCESS_KEY" not in b
    assert 3000 < len(b) < 12000              # compact enough to embed
