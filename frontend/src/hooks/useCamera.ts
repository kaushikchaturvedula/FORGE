import { useCallback, useEffect, useRef } from "react";

// Manages the live "field camera". In the demo this is the OBS Virtual Camera
// streaming the CNC clip, which the browser sees as an ordinary webcam device.
// getFrame() draws the current video frame to an offscreen canvas, downscaled to the
// model's input size, and returns base64 JPEG (no data: prefix).
export function useCamera(active: boolean, width: number, height: number, deviceId?: string) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function open() {
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
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => undefined);
        }
      } catch {
        /* no camera / permission denied — panel shows a hint */
      }
    }
    function close() {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
    }
    if (active) open();
    else close();
    return () => {
      cancelled = true;
      close();
    };
  }, [active, deviceId]);

  const getFrame = useCallback((): string | null => {
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
  }, [width, height]);

  return { videoRef, getFrame };
}
