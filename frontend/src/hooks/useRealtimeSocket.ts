import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { AudioPlayer } from "../audio/player";
import { MicRecorder } from "../audio/recorder";
import {
  type AlertMsg,
  type ConnState,
  type ConvState,
  type MetricsMsg,
  type RuntimeConfig,
  type ServerMessage,
  wsUrl,
} from "../lib/api";

export interface Line { id: number; role: "user" | "assistant"; text: string }
export interface ToolTick { name: string; status: string; ts: number }

interface State {
  conn: ConnState;
  conv: ConvState;
  agent: { agent: string; display: string };
  lines: Line[];
  partialUser: string;
  partialAssistant: string;
  panels: Record<string, any>;
  visible: Record<string, boolean>;
  alerts: AlertMsg[];
  events: any[];
  metrics: MetricsMsg;
  sessionRemaining: number;
  visionActive: boolean;
  recentTools: ToolTick[];
  error: string | null;
}

const initial: State = {
  conn: "disconnected",
  conv: "idle",
  agent: { agent: "orchestrator", display: "Orchestrator" },
  lines: [],
  partialUser: "",
  partialAssistant: "",
  panels: {},
  visible: {},
  alerts: [],
  events: [],
  metrics: { type: "metrics", count: 0, last_tool: "", rejected: 0, latency_ms: 0 },
  sessionRemaining: 0,
  visionActive: false,
  recentTools: [],
  error: null,
};

type Action =
  | { k: "conn"; v: ConnState }
  | { k: "msg"; m: ServerMessage }
  | { k: "tick" }
  | { k: "reset" };

let lineId = 0;

function reducer(s: State, a: Action): State {
  switch (a.k) {
    case "conn":
      return { ...s, conn: a.v };
    case "tick":
      return { ...s, sessionRemaining: Math.max(0, s.sessionRemaining - 1) };
    case "reset":
      return { ...initial, conn: s.conn };
    case "msg":
      return applyMsg(s, a.m);
  }
}

function applyMsg(s: State, m: ServerMessage): State {
  switch (m.type) {
    case "hello":
      return { ...s, agent: { agent: m.agent, display: m.display }, sessionRemaining: m.session_max_seconds };
    case "agent":
      return { ...s, agent: { agent: m.agent, display: m.display } };
    case "state":
      return { ...s, conv: m.status as ConvState, sessionRemaining: m.session_remaining ?? s.sessionRemaining };
    case "transcript": {
      if (m.role === "user") {
        if (m.final) return { ...s, lines: [...s.lines, { id: ++lineId, role: "user", text: m.text || s.partialUser }], partialUser: "" };
        return { ...s, partialUser: s.partialUser + m.delta };
      }
      if (m.final) return { ...s, lines: [...s.lines, { id: ++lineId, role: "assistant", text: m.text || s.partialAssistant }], partialAssistant: "" };
      return { ...s, partialAssistant: s.partialAssistant + m.delta };
    }
    case "interrupted":
      return { ...s, partialAssistant: "", conv: "listening" };
    case "panel": {
      const prev = s.panels[m.panel] || {};
      return { ...s, panels: { ...s.panels, [m.panel]: { ...prev, ...m.data } }, visible: { ...s.visible, [m.panel]: true } };
    }
    case "alert":
      return { ...s, alerts: [m, ...s.alerts].slice(0, 6) };
    case "log":
      return { ...s, events: [m.entry, ...s.events].slice(0, 60) };
    case "tool":
      return { ...s, recentTools: [{ name: m.name, status: m.status, ts: Date.now() }, ...s.recentTools].slice(0, 8) };
    case "metrics":
      return { ...s, metrics: m };
    case "control":
      return applyControl(s, m.action, m as Record<string, unknown>);
    case "error":
      return { ...s, error: m.message };
    default:
      return s;
  }
}

function applyControl(s: State, action: string, payload: Record<string, unknown>): State {
  switch (action) {
    case "activate_vision":
      return { ...s, visionActive: true, visible: { ...s.visible, vision: true } };
    case "deactivate_vision":
      return { ...s, visionActive: false };
    case "show_panel": {
      const p = String(payload.panel || "");
      if (p === "all") return { ...s, visible: { schematic: true, machine_data: true, procedure: true, vision: s.visionActive, measurement: true, event_log: true } };
      return { ...s, visible: { ...s.visible, [p]: true } };
    }
    case "hide_panel": {
      const p = String(payload.panel || "");
      if (p === "all") return { ...s, visible: {} };
      return { ...s, visible: { ...s.visible, [p]: false } };
    }
    default:
      return s;
  }
}

export type FrameProvider = () => string | null; // returns base64 JPEG, no data: prefix

export function useRealtimeSocket(config: RuntimeConfig | null) {
  const [state, dispatch] = useReducer(reducer, initial);
  const ws = useRef<WebSocket | null>(null);
  const player = useRef<AudioPlayer | null>(null);
  const recorder = useRef<MicRecorder | null>(null);
  const userClosed = useRef(false);
  const frameProvider = useRef<FrameProvider | null>(null);
  const screenProvider = useRef<FrameProvider | null>(null);
  const micOn = useRef(false);

  const send = useCallback((obj: unknown) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(obj));
  }, []);

  const connect = useCallback(() => {
    if (!config || ws.current) return;
    userClosed.current = false;
    dispatch({ k: "conn", v: "connecting" });
    if (!player.current) player.current = new AudioPlayer(config.output_sample_rate);

    const socket = new WebSocket(wsUrl());
    socket.binaryType = "arraybuffer";
    ws.current = socket;

    socket.onopen = () => dispatch({ k: "conn", v: "connected" });
    socket.onmessage = (e: MessageEvent) => {
      if (e.data instanceof ArrayBuffer) {
        player.current?.enqueue(e.data);
        return;
      }
      try {
        const m = JSON.parse(e.data as string) as ServerMessage;
        if (m.type === "interrupted") player.current?.drain();
        dispatch({ k: "msg", m });
      } catch {
        /* ignore malformed */
      }
    };
    socket.onclose = () => {
      ws.current = null;
      dispatch({ k: "conn", v: "disconnected" });
      if (!userClosed.current) setTimeout(() => connect(), 1500); // auto-reconnect
    };
    socket.onerror = () => socket.close();
  }, [config]);

  const disconnect = useCallback(() => {
    userClosed.current = true;
    recorder.current?.stop();
    recorder.current = null;
    micOn.current = false;
    ws.current?.close();
    ws.current = null;
    player.current?.close();
    player.current = null;
    dispatch({ k: "conn", v: "disconnected" });
  }, []);

  const toggleMic = useCallback(async () => {
    if (!config) return;
    if (micOn.current) {
      recorder.current?.stop();
      recorder.current = null;
      micOn.current = false;
      dispatch({ k: "msg", m: { type: "state", status: "idle" } });
      return;
    }
    await player.current?.resume(); // unlock audio on the user gesture
    const rec = new MicRecorder();
    await rec.start(config.input_sample_rate, (pcm) => {
      if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(pcm);
    });
    recorder.current = rec;
    micOn.current = true;
    dispatch({ k: "msg", m: { type: "state", status: "listening" } });
  }, [config]);

  const registerFrameProvider = useCallback((fn: FrameProvider | null) => {
    frameProvider.current = fn;
  }, []);

  const registerScreenProvider = useCallback((fn: FrameProvider | null) => {
    screenProvider.current = fn;
  }, []);

  const bargeIn = useCallback(() => {
    player.current?.drain();
    send({ type: "control", action: "barge_in" });
  }, [send]);

  // 1 fps vision frame sender, gated on visionActive.
  useEffect(() => {
    if (!state.visionActive || !config) return;
    const period = Math.max(250, Math.round(1000 / config.vision.fps));
    const id = window.setInterval(() => {
      const frame = frameProvider.current?.();
      if (frame) send({ type: "image", jpeg_b64: frame });
      // Optional SCADA screen frame (only sent while sharing is on).
      const screen = screenProvider.current?.();
      if (screen) send({ type: "image", jpeg_b64: screen });
    }, period);
    return () => window.clearInterval(id);
  }, [state.visionActive, config, send]);

  // session countdown
  useEffect(() => {
    if (state.conn !== "connected") return;
    const id = window.setInterval(() => dispatch({ k: "tick" }), 1000);
    return () => window.clearInterval(id);
  }, [state.conn]);

  useEffect(() => () => disconnect(), [disconnect]);

  const micActive = micOn.current;
  return useMemo(
    () => ({ state, connect, disconnect, toggleMic, registerFrameProvider, registerScreenProvider, bargeIn, micActive }),
    [state, connect, disconnect, toggleMic, registerFrameProvider, registerScreenProvider, bargeIn, micActive],
  );
}
