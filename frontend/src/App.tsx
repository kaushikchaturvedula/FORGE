import { useEffect, useMemo, useState } from "react";
import { Alerts } from "./components/Alerts";
import { HudRail } from "./components/HudRail";
import { Panel } from "./components/Panel";
import { TopBar } from "./components/TopBar";
import { EventLogPanel } from "./components/panels/EventLogPanel";
import { FieldVisionPanel } from "./components/panels/FieldVisionPanel";
import { MachineDataPanel } from "./components/panels/MachineDataPanel";
import { MeasurementPanel } from "./components/panels/MeasurementPanel";
import { ProcedurePanel } from "./components/panels/ProcedurePanel";
import { SchematicPanel } from "./components/panels/SchematicPanel";
import { useRealtimeSocket } from "./hooks/useRealtimeSocket";
import { PANEL_TITLES, fetchConfig, type RuntimeConfig } from "./lib/api";

const PANEL_ORDER = ["machine_data", "schematic", "procedure", "vision", "measurement", "event_log"];
const ACCENTS: Record<string, string> = {
  machine_data: "#7c3aed",
  schematic: "#06b6d4",
  procedure: "#f59e0b",
  vision: "#06b6d4",
  measurement: "#ef4444",
  event_log: "#22c55e",
};

export default function App() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const { state, connect, toggleMic, registerFrameProvider, registerScreenProvider, bargeIn, micActive, manualVision, setManualVision, visionStreaming, clearError } = useRealtimeSocket(config);

  useEffect(() => {
    fetchConfig().then(setConfig).catch((e) => setConfigError(String(e)));
  }, []);

  useEffect(() => {
    if (config) connect();
  }, [config, connect]);

  const lastAssistant = useMemo(() => {
    if (state.partialAssistant) return state.partialAssistant;
    for (let i = state.lines.length - 1; i >= 0; i--) if (state.lines[i].role === "assistant") return state.lines[i].text;
    return "";
  }, [state.lines, state.partialAssistant]);

  const visible: Record<string, boolean> = { ...state.visible, vision: state.visible.vision || manualVision };
  const visiblePanels = PANEL_ORDER.filter((p) => visible[p]);

  return (
    <div className="flex h-screen flex-col bg-forge-bg text-forge-text">
      <TopBar
        conn={state.conn}
        conv={state.conv}
        micActive={micActive}
        sessionRemaining={state.sessionRemaining}
        assetId={config?.asset_id || "PL45LM-01"}
        onToggleMic={() => void toggleMic()}
        onBargeIn={bargeIn}
        visionOn={manualVision}
        onToggleVision={() => setManualVision((v) => !v)}
      />

      <div className="relative flex min-h-0 flex-1">
        <HudRail
          activeAgent={state.agent.agent}
          lines={state.lines}
          partialUser={state.partialUser}
          partialAssistant={state.partialAssistant}
          recentTools={state.recentTools}
          metrics={state.metrics}
        />

        <main className="min-h-0 flex-1 overflow-auto p-3">
          <Alerts alerts={state.alerts} />

          {configError && (
            <div className="mb-3 rounded border border-forge-alert bg-forge-alert/10 p-3 text-sm text-forge-text">
              Could not load runtime config: {configError}. Is the backend running on :8000?
            </div>
          )}

          {state.error && (
            <div className="mb-3 flex items-start justify-between gap-3 rounded border border-forge-alert bg-forge-alert/10 p-3 text-sm text-forge-text">
              <span>⚠ {state.error}</span>
              <button onClick={clearError} className="text-forge-muted hover:text-forge-text" aria-label="Dismiss">
                ✕
              </button>
            </div>
          )}

          {visiblePanels.length === 0 ? (
            <WelcomeMat />
          ) : (
            <div className="grid h-full gap-3" style={{ gridTemplateColumns: `repeat(${visiblePanels.length === 1 ? 1 : 2}, minmax(0, 1fr))` }}>
              {visiblePanels.map((p) => (
                <Panel key={p} title={PANEL_TITLES[p]} accent={ACCENTS[p]}>
                  {renderPanel(p)}
                </Panel>
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );

  function renderPanel(p: string) {
    const data = state.panels[p] || {};
    switch (p) {
      case "machine_data":
        return <MachineDataPanel data={data} />;
      case "schematic":
        return <SchematicPanel data={data} />;
      case "procedure":
        return <ProcedurePanel data={data} />;
      case "measurement":
        return <MeasurementPanel data={data} />;
      case "event_log":
        return <EventLogPanel data={data} events={state.events} />;
      case "vision":
        return (
          <FieldVisionPanel
            active={visionStreaming}
            width={config?.vision.width ?? 320}
            height={config?.vision.height ?? 240}
            screen={config?.vision.screen ?? { width: 768, height: 768 }}
            perception={lastAssistant}
            registerFrameProvider={registerFrameProvider}
            registerScreenProvider={registerScreenProvider}
          />
        );
      default:
        return null;
    }
  }
}

function WelcomeMat() {
  const examples = [
    "“Brief me on this machining center.”",
    "“Run the lockout procedure.”",
    "“What do you see?”",
    "“Show the spindle assembly and jump to the drawbar.”",
    "“What's the torque spec for the tool-holder bolts?”",
    "“Record spindle torque 65 Nm.”",
    "“Log tool replaced.” · “Generate the report.”",
  ];
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <div className="mb-2 text-4xl">🔧</div>
      <h1 className="text-xl font-bold">FORGE is listening.</h1>
      <p className="mb-4 text-sm text-forge-muted">Press <b>Talk</b> and speak. The console fills in as you work.</p>
      <ul className="flex flex-col gap-1 text-sm text-forge-text">
        {examples.map((e) => (
          <li key={e}>{e}</li>
        ))}
      </ul>
    </div>
  );
}
