import { useEffect, useRef, useState } from "react";
import { useCamera } from "../../hooks/useCamera";
import type { FrameProvider } from "../../hooks/useRealtimeSocket";

export function FieldVisionPanel({
  active,
  width,
  height,
  perception,
  registerFrameProvider,
}: {
  active: boolean;
  width: number;
  height: number;
  perception: string;
  registerFrameProvider: (fn: FrameProvider | null) => void;
}) {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string | undefined>(undefined);
  const { videoRef, getFrame } = useCamera(active, width, height, deviceId);
  const providerRef = useRef(getFrame);
  providerRef.current = getFrame;

  // Register a stable frame provider for the 1 fps sender.
  useEffect(() => {
    if (active) registerFrameProvider(() => providerRef.current());
    else registerFrameProvider(null);
    return () => registerFrameProvider(null);
  }, [active, registerFrameProvider]);

  // Enumerate cameras so the demo can pick "OBS Virtual Camera".
  useEffect(() => {
    if (!active) return;
    navigator.mediaDevices
      .enumerateDevices()
      .then((d) => setDevices(d.filter((x) => x.kind === "videoinput")))
      .catch(() => undefined);
  }, [active]);

  return (
    <div className="flex h-full flex-col">
      <div className="relative min-h-0 flex-1 overflow-hidden rounded bg-black">
        <video ref={videoRef} className="h-full w-full object-contain" muted playsInline />
        {!active && (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-forge-muted">
            Vision is off. Say “what do you see?” to start the feed.
          </div>
        )}
        {active && (
          <div className="absolute left-2 top-2 flex items-center gap-1 rounded bg-black/60 px-2 py-0.5 text-[10px] text-forge-vision">
            <span className="h-2 w-2 animate-pulseRing rounded-full bg-forge-vision" /> LIVE · 1 fps → Field Advisor
          </div>
        )}
        {active && perception && (
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 text-sm text-forge-text">
            <span className="text-forge-vision">👁 </span>
            {perception}
          </div>
        )}
      </div>
      {active && devices.length > 0 && (
        <select
          className="mt-2 rounded border border-forge-edge bg-forge-bg px-2 py-1 text-xs text-forge-text"
          value={deviceId ?? ""}
          onChange={(e) => setDeviceId(e.target.value || undefined)}
        >
          <option value="">Default camera</option>
          {devices.map((d) => (
            <option key={d.deviceId} value={d.deviceId}>
              {d.label || `Camera ${d.deviceId.slice(0, 6)}`}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
