"""Realtime event (de)serialization — pure, no session needed."""

from __future__ import annotations

import base64
import json

from app.realtime import events as ev


def test_parse_session_created():
    out = ev.parse_server_event({"type": "session.created", "session": {"id": "sess_1"}})
    assert isinstance(out, ev.SessionCreated) and out.session_id == "sess_1"


def test_parse_audio_delta_decodes_base64():
    pcm = b"\x01\x02\x03\x04"
    raw = {"type": "response.audio.delta", "delta": base64.b64encode(pcm).decode()}
    out = ev.parse_server_event(raw)
    assert isinstance(out, ev.AudioDelta) and out.audio == pcm


def test_parse_output_transcript_delta():
    out = ev.parse_server_event({"type": "response.audio_transcript.delta", "delta": "hel"})
    assert isinstance(out, ev.OutputTranscriptDelta) and out.text == "hel"


def test_parse_input_transcription_completed():
    out = ev.parse_server_event(
        {"type": "conversation.item.input_audio_transcription.completed", "transcript": "show specs"}
    )
    assert isinstance(out, ev.InputTranscriptDone) and out.text == "show specs"


def test_parse_function_call_done_parses_args():
    raw = {
        "type": "response.function_call_arguments.done",
        "call_id": "call_7",
        "name": "lookup_torque",
        "arguments": json.dumps({"fastener_id": "tool_holder_bolt"}),
    }
    out = ev.parse_server_event(raw)
    assert isinstance(out, ev.FunctionCallDone)
    assert out.call_id == "call_7"
    assert out.arguments == {"fastener_id": "tool_holder_bolt"}


def test_parse_speech_started_for_bargein():
    assert isinstance(
        ev.parse_server_event({"type": "input_audio_buffer.speech_started"}), ev.SpeechStarted
    )


def test_parse_input_audio_committed():
    assert isinstance(
        ev.parse_server_event({"type": "input_audio_buffer.committed"}), ev.InputAudioCommitted
    )


def test_parse_error_and_unknown():
    err = ev.parse_server_event({"type": "error", "error": {"message": "boom", "code": "x"}})
    assert isinstance(err, ev.RealtimeError) and err.message == "boom"
    unk = ev.parse_server_event({"type": "some.future.event", "foo": 1})
    assert isinstance(unk, ev.UnknownEvent) and unk.type == "some.future.event"


def test_session_update_flattens_tools():
    tool = {
        "type": "function",
        "function": {"name": "lookup_part", "description": "d", "parameters": {"type": "object"}},
    }
    upd = ev.session_update(instructions="be helpful", tools=[tool], voice="Cherry")
    assert upd["type"] == "session.update"
    flat = upd["session"]["tools"][0]
    assert flat["type"] == "function" and flat["name"] == "lookup_part"
    assert "function" not in flat  # flattened for the realtime API
    assert upd["session"]["turn_detection"]["type"] == "server_vad"


def test_session_update_matches_live_protocol():
    upd = ev.session_update(instructions="hi", tools=[], voice="Cherry")
    s = upd["session"]
    # Audio format on the wire is "pcm" (NOT the OpenAI "pcm16").
    assert s["input_audio_format"] == "pcm"
    assert s["output_audio_format"] == "pcm"
    # server_vad object carries threshold + silence_duration_ms, and NOT create_response.
    td = s["turn_detection"]
    assert td["type"] == "server_vad"
    assert "threshold" in td and "silence_duration_ms" in td
    assert "create_response" not in td
    assert s["input_audio_transcription"] == {"model": "gummy-realtime-v1"}
    assert s["modalities"] == ["text", "audio"]
    # No tools advertised when none are passed.
    assert "tools" not in s


def test_session_update_vad_type_override():
    upd = ev.session_update(instructions="hi", tools=[], voice="Ethan", vad_type="semantic_vad")
    assert upd["session"]["turn_detection"]["type"] == "semantic_vad"


def test_tools_format_flat_vs_nested_and_tool_choice():
    tool = {"type": "function", "function": {"name": "lookup_part", "description": "d", "parameters": {"type": "object"}}}
    flat = ev.session_update(instructions="x", tools=[tool], voice="Cherry", tools_format="flat")["session"]["tools"][0]
    assert flat["name"] == "lookup_part" and "function" not in flat  # flattened

    nested = ev.session_update(instructions="x", tools=[tool], voice="Cherry", tools_format="nested")["session"]["tools"][0]
    assert "function" in nested and nested["function"]["name"] == "lookup_part"

    # tool_choice only sent when explicitly configured
    assert "tool_choice" not in ev.session_update(instructions="x", tools=[tool], voice="Cherry")["session"]
    assert ev.session_update(instructions="x", tools=[tool], voice="Cherry", tool_choice="auto")["session"]["tool_choice"] == "auto"


def test_session_updated_echo_parsed():
    out = ev.parse_server_event({"type": "session.updated", "session": {"tools": [1], "voice": "Cherry"}})
    assert isinstance(out, ev.SessionUpdated)
    assert out.session.get("tools") == [1]


def test_function_call_output_builder_round_trips():
    out = ev.function_call_output("call_9", {"torque_nm": 12})
    assert out["item"]["type"] == "function_call_output"
    assert out["item"]["call_id"] == "call_9"
    assert json.loads(out["item"]["output"]) == {"torque_nm": 12}


def test_image_and_audio_append_base64():
    a = ev.input_audio_append(b"\x00\x01")
    assert a["type"] == "input_audio_buffer.append"
    assert base64.b64decode(a["audio"]) == b"\x00\x01"
    i = ev.input_image_append(b"\xff\xd8\xff")
    assert i["type"] == "input_image_buffer.append"
    assert base64.b64decode(i["image"]) == b"\xff\xd8\xff"
