import { useCallback, useEffect, useRef, useState } from "react";

// Optional screen-capture for reading an on-screen SCADA / monitoring dashboard.
// getDisplayMedia is acquired ONCE on first use and kept alive across vision
// activations (per the spec lifecycle note); toggling only stops sending frames.
export function useScreenShare(width: number, height: number) {
  const [active, setActive] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const start = useCallback(async () => {
    if (!streamRef.current) {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 2 }, audio: false });
      streamRef.current = stream;
      const v = document.createElement("video");
      v.muted = true;
      v.srcObject = stream;
      await v.play().catch(() => undefined);
      videoRef.current = v;
      // If the user stops sharing from the browser UI, reflect it.
      stream.getVideoTracks()[0]?.addEventListener("ended", () => {
        streamRef.current = null;
        videoRef.current = null;
        setActive(false);
      });
    }
    setActive(true);
  }, []);

  const stop = useCallback(() => setActive(false), []);

  const getFrame = useCallback((): string | null => {
    const v = videoRef.current;
    if (!active || !v || v.readyState < 2) return null;
    if (!canvasRef.current) canvasRef.current = document.createElement("canvas");
    const canvas = canvasRef.current;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(v, 0, 0, width, height);
    return canvas.toDataURL("image/jpeg", 0.6).split(",")[1] ?? null;
  }, [active, width, height]);

  // Fully release the display stream on unmount.
  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    },
    [],
  );

  return { active, start, stop, getFrame };
}
