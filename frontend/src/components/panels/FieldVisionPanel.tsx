import { type ChangeEvent, useEffect, useRef, useState } from "react";
import { useScreenShare } from "../../hooks/useScreenShare";
import type { FrameProvider } from "../../hooks/useRealtimeSocket";

type Mode = "camera" | "file";

export interface FieldAnnotation { label: string; region: string; seq: number }

// Approximate region → absolute placement of the callout badge over the video.
const REGION_POS: Record<string, string> = {
  "top-left": "left-3 top-8", top: "left-1/2 top-8 -translate-x-1/2", "top-right": "right-3 top-8",
  left: "left-3 top-1/2 -translate-y-1/2", center: "left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2", right: "right-3 top-1/2 -translate-y-1/2",
  "bottom-left": "bottom-12 left-3", bottom: "bottom-12 left-1/2 -translate-x-1/2", "bottom-right": "bottom-12 right-3",
};

// The live "field camera". Three ways to feed it:
//  * a webcam / OBS Virtual Camera (pick the device),
//  * a local video FILE (load a CNC clip directly — no OBS needed),
//  * an optional screen share (SCADA dashboards).
// getFrame() downsamples the current frame to the model's input size and returns
// base64 JPEG, which the 1 fps sender streams while vision is active.
export function FieldVisionPanel({
  active,
  width,
  height,
  screen,
  perception,
  annotate,
  registerFrameProvider,
  registerScreenProvider,
}: {
  active: boolean;
  width: number;
  height: number;
  screen: { width: number; height: number };
  perception: string;
  annotate?: FieldAnnotation | null;
  registerFrameProvider: (fn: FrameProvider | null) => void;
  registerScreenProvider: (fn: FrameProvider | null) => void;
}) {
  const [mode, setMode] = useState<Mode>("camera");
  const [callout, setCallout] = useState<FieldAnnotation | null>(null);

  // Show a callout when one arrives; auto-clear after a few seconds.
  useEffect(() => {
    if (!annotate) return;
    setCallout(annotate);
    const id = window.setTimeout(() => setCallout(null), 6000);
    return () => window.clearTimeout(id);
  }, [annotate?.seq]);

  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string | undefined>(undefined);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const scr = useScreenShare(screen.width, screen.height);

  // Acquire / release the video source when active or the source changes.
  useEffect(() => {
    let cancelled = false;
    const video = videoRef.current;

    function stopCam() {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }

    async function open() {
      if (!video) return;
      if (mode === "file" && fileUrl) {
        stopCam();
        video.srcObject = null;
        video.src = fileUrl;
        video.loop = true;
        await video.play().catch(() => undefined);
        return;
      }
      // camera / OBS Virtual Camera
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: deviceId ? { deviceId: { exact: deviceId } } : { width: 640, height: 480 },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        video.src = "";
        video.srcObject = stream;
        await video.play().catch(() => undefined);
      } catch {
        /* no camera / denied — the file option still works */
      }
    }

    if (active) open();
    else {
      stopCam();
      if (video) video.pause();
    }
    return () => {
      cancelled = true;
      stopCam();
    };
  }, [active, mode, fileUrl, deviceId]);

  // One stable frame provider, drawing whatever the <video> currently shows.
  useEffect(() => {
    function getFrame(): string | null {
      const video = videoRef.current;
      if (!video || video.readyState < 2) return null;
      if (!canvasRef.current) canvasRef.current = document.createElement("canvas");
      const canvas = canvasRef.current;
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.drawImage(video, 0, 0, width, height);
      return canvas.toDataURL("image/jpeg", 0.6).split(",")[1] ?? null;
    }
    if (active) registerFrameProvider(getFrame);
    else registerFrameProvider(null);
    return () => registerFrameProvider(null);
  }, [active, width, height, registerFrameProvider]);

  // Screen frames flow only when vision is active AND the user is sharing.
  const scrGetFrame = scr.getFrame;
  useEffect(() => {
    if (active && scr.active) registerScreenProvider(() => scrGetFrame());
    else registerScreenProvider(null);
    return () => registerScreenProvider(null);
  }, [active, scr.active, scrGetFrame, registerScreenProvider]);

  useEffect(() => {
    if (mode !== "camera" || !active) return;
    navigator.mediaDevices
      .enumerateDevices()
      .then((d) => setDevices(d.filter((x) => x.kind === "videoinput")))
      .catch(() => undefined);
  }, [mode, active]);

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (fileUrl) URL.revokeObjectURL(fileUrl);
    setFileUrl(URL.createObjectURL(file));
    setMode("file");
  }

  return (
    <div className="flex h-full flex-col">
      <div className="relative min-h-0 flex-1 overflow-hidden rounded bg-black">
        <video ref={videoRef} className="h-full w-full object-contain" muted playsInline />
        {!active && (
          <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-xs text-forge-muted">
            Vision is off. Say “what do you see?”, or toggle 👁 Vision above and pick a camera or load a video file.
          </div>
        )}
        {active && (
          <div className="absolute left-2 top-2 flex items-center gap-1 rounded bg-black/60 px-2 py-0.5 text-[10px] text-forge-vision">
            <span className="h-2 w-2 animate-pulseRing rounded-full bg-forge-vision" /> LIVE · 1 fps → Field Advisor
          </div>
        )}
        {active && callout && (
          <div className={`pointer-events-none absolute ${REGION_POS[callout.region] ?? REGION_POS.center} z-10`}>
            <div className="animate-pulseRing rounded-md border-2 border-forge-vision bg-black/70 px-2 py-1 text-xs font-semibold text-forge-vision shadow-lg">
              ◎ {callout.label}
            </div>
          </div>
        )}
        {active && perception && (
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 text-sm text-forge-text">
            <span className="text-forge-vision">👁 </span>
            {perception}
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <div className="flex overflow-hidden rounded border border-forge-edge">
          <button onClick={() => setMode("camera")} className={`px-2 py-1 ${mode === "camera" ? "bg-forge-accent text-white" : "text-forge-muted"}`}>
            📷 Camera
          </button>
          <button onClick={() => setMode("file")} className={`px-2 py-1 ${mode === "file" ? "bg-forge-accent text-white" : "text-forge-muted"}`}>
            🎞 Video file
          </button>
        </div>

        {mode === "camera" && devices.length > 0 && (
          <select
            className="rounded border border-forge-edge bg-forge-bg px-2 py-1 text-forge-text"
            value={deviceId ?? ""}
            onChange={(e) => setDeviceId(e.target.value || undefined)}
          >
            <option value="">Default / OBS Virtual Camera</option>
            {devices.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || `Camera ${d.deviceId.slice(0, 6)}`}
              </option>
            ))}
          </select>
        )}

        {mode === "file" && (
          <label className="cursor-pointer rounded border border-forge-edge px-2 py-1 text-forge-text hover:bg-forge-bg">
            {fileUrl ? "Change clip…" : "Choose a CNC clip…"}
            <input type="file" accept="video/*" className="hidden" onChange={onFile} />
          </label>
        )}

        <button
          onClick={() => (scr.active ? scr.stop() : void scr.start())}
          className={`rounded px-2 py-1 ${scr.active ? "bg-forge-vision text-black" : "border border-forge-edge text-forge-muted"}`}
          title="Share a SCADA / monitoring screen for FORGE to read"
        >
          🖥 {scr.active ? "Sharing" : "Share screen"}
        </button>
      </div>
    </div>
  );
}
