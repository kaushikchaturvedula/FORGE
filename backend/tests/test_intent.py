"""Keyword intent → tool inference (drives the console panels), and the embedded data."""

from __future__ import annotations

from app.agents.intent import infer_tools
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


def test_short_safety_triggers_are_word_boundary_not_substring():
    def sc(s):
        return [c for c in infer_tools(s, {}) if c[0] == "run_safety_check"]
    # ASR false positives: "ppe" embedded in "dropper"/"swapped" must NOT pop a safety checklist.
    assert sc("what's the part number for the dropper, and the torque spec for the tool holder bolt?") == []
    assert sc("i swapped the tool holder") == []
    # real safety asks still fire
    assert ("run_safety_check", {"check_type": "pre_start"}) in infer_tools("run the pre-start safety check", {})
    assert ("run_safety_check", {"check_type": "ppe"}) in infer_tools("is my ppe okay", {})
    assert ("run_safety_check", {"check_type": "ppe"}) in infer_tools("run the ppe check", {})
    assert ("run_safety_check", {"check_type": "loto"}) in infer_tools("run the lockout procedure", {})


def test_chitchat_and_other_equipment_infer_nothing():
    assert infer_tools("hello, how are you") == []
    assert infer_tools("can you help me with a forklift") == []


# ── new: hide/clear, 3D model, highlight, actions ───────────────────────────
def test_clear_and_hide_panels():
    assert ("hide_panel", {"panel": "all"}) in infer_tools("clear everything", {})
    assert ("hide_panel", {"panel": "all"}) in infer_tools("clear the screen", {})
    assert ("hide_panel", {"panel": "machine_data"}) in infer_tools("hide the machine data", {})
    assert ("hide_panel", {"panel": "model"}) in infer_tools("hide the 3d model", {})


def test_clear_all_needs_screen_as_object_not_a_locative_qualifier():
    # "on/from the screen" is a LOCATION for the real object ("the highlight"), not "clear the
    # screen" — it must NOT wipe the whole dashboard.
    assert infer_tools("clear the highlight on the screen", {}) == []
    assert infer_tools("dismiss the alert on the screen", {}) == []
    assert infer_tools("clear the highlight from the screen", {}) == []


def test_clear_all_still_fires_on_real_clear_all_lines():
    # Live demo lines — the clear-all must stay byte-for-byte.
    assert ("hide_panel", {"panel": "all"}) in infer_tools("clear the screen", {})
    assert ("hide_panel", {"panel": "all"}) in infer_tools("clear everything — we're done", {})
    # conjunction: the screen IS an object here ("...and the screen")
    assert ("hide_panel", {"panel": "all"}) in infer_tools("clear the highlight and the screen", {})
    assert ("hide_panel", {"panel": "all"}) in infer_tools("clear the screen. now — is the work envelope clear and safe to start", {})
    # compound line still triggers the workflow too
    from app.agents import workflows
    line = "dismiss the alert, clear the screen — and diagnose the unclamp fault"
    assert ("hide_panel", {"panel": "all"}) in infer_tools(line, {})
    assert workflows.match_workflow(line) == "unclamp_fault"
    # compound line still fires the work-order log entry too
    ex = "hide everything except the work-order log — and log that i changed the tool"
    calls = infer_tools(ex, {})
    assert ("hide_panel", {"panel": "all"}) in calls
    assert ("log_event", {"event_type": "note", "note": "i changed the tool"}) in calls


def test_clear_all_fix_leaves_neighbors_unchanged():
    assert infer_tools("what's on the screen right now", {}) == []          # no hide trigger
    assert infer_tools("hide the machine data", {}) == [("hide_panel", {"panel": "machine_data"})]
    # "hide the 3d model" keeps its pre-existing behavior: the "3d model" cue reveals the panel
    # first, then hides it (a native no-op UX quirk unrelated to this fix). Assert it's unchanged
    # AND never becomes a whole-screen wipe.
    assert infer_tools("hide the 3d model", {}) == [("show_panel", {"panel": "model"}), ("hide_panel", {"panel": "model"})]
    assert ("hide_panel", {"panel": "all"}) not in infer_tools("hide the 3d model", {})


def test_model_commands_reveal_panel_but_never_rotate():
    # NATIVE-ONLY: the intent fallback only REVEALS the 3D-model panel; it must NOT emit any
    # rotate_model/set_rotation/reset_view (the realtime model's function call is the single
    # authoritative rotation source — a divergent keyword guess used to double-apply).
    for utter in ("show me the 3d model", "rotate the model 30 degrees",
                  "rotate by ninety counterclockwise on y", "reset the view", "rotate 30 on x"):
        calls = infer_tools(utter, {})
        assert ("show_panel", {"panel": "model"}) in calls, utter
        assert not any(n in ("rotate_model", "set_rotation", "reset_view") for n, _ in calls), utter
    # a non-model "turn" must not even reveal the panel
    assert infer_tools("turn it off", {}) == []


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


def test_log_note_drops_filler_fragment_but_keeps_short_substantive():
    from app.agents.intent import _parse_log_note
    # ASR splits "...log that for me" -> the trailing politeness must NOT become a phantom note
    assert _parse_log_note("i changed the tool, log that for me") is None
    assert _parse_log_note("log that please") is None
    # a real note still logs, including a legit SHORT one (no word-count cutoff)
    assert _parse_log_note("log that the coolant line was replaced") == "the coolant line was replaced"
    assert _parse_log_note("log that coolant low") == "coolant low"
    assert ("log_event", {"event_type": "note", "note": "coolant low"}) in infer_tools("log that coolant low", {})
    assert not any(n == "log_event" for n, _ in infer_tools("i changed the tool, log that for me", {}))


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
    assert catalog.resolve_hotspot("I embedded the sensor there") is None
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
