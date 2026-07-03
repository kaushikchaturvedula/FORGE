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
