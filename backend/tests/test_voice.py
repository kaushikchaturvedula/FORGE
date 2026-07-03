"""Instruction-content guards for the realtime persona.

These lock in the demo-critical few-shot patterns that make the native (model-driven) tool
routing reliable. They assert on the rendered `realtime_instructions()` string so a well-meaning
edit that drops a pattern (or the whole MULTI-TASK section) fails loudly instead of silently
degrading multi-task command handling.
"""
from app.agents.voice import realtime_instructions


def test_instructions_contain_multitask_section():
    text = realtime_instructions()
    assert "MULTI-TASK COMMANDS" in text
    # core rules that keep native routing honest
    assert "one tool call per distinct ask" in text
    assert "NEVER claim a screen change you didn't call a tool for" in text


def test_instructions_contain_demo_critical_patterns():
    text = realtime_instructions()
    # ordering matters (reset before hide)
    assert "ORDER MATTERS" in text
    # nested machine-data sections: show-just and hide-section
    assert 'Show me just the faults.' in text
    assert 'section:"specs"' in text
    # multi-source lookups in one breath
    assert 'lookup_part{query:"drawbar"}' in text
    assert "lookup_torque" in text
    # clear-highlight vs clear-screen disambiguation
    assert "clear_highlight ONLY" in text


def test_instructions_document_machine_data_section_stacking():
    text = realtime_instructions()
    assert "MACHINE-DATA SECTIONS" in text
    assert "PERSIST" in text


def test_instructions_contain_autopilot_carveout():
    # FIX 1: the honesty rules ("never claim a screen change you didn't call a tool for") must carry
    # an explicit carve-out for server-performed AUTOPILOT WORKFLOW updates, or the model refuses to
    # narrate them and repeats its previous answer.
    text = realtime_instructions()
    assert "AUTOPILOT EXCEPTION" in text
    assert 'messages beginning "AUTOPILOT WORKFLOW —"' in text
    assert "narrate them as done" in text
    assert "never repeat sentences you already said this session" in text


def test_instructions_contain_workflow_entry_fewshot():
    # FIX 1: the multi-task few-shots must include the diagnosis-entry command so the model makes a
    # SHORT ack (dismiss + clear + one line) and lets the autopilot drive — no menu choices.
    text = realtime_instructions()
    assert "Dismiss the alert, clear the screen, and diagnose" in text
    assert "dismiss_alert" in text and 'hide_panel{panel:"all"}' in text
    assert "watch the console" in text
