// Mic capture: getUserMedia -> 16 kHz mono PCM16 frames -> callback (sent over the WS).
//
// Primary path is an AudioWorklet loaded from /recorder-worklet.js (served verbatim from
// public/ so Vite never transforms it — loading it via new URL(import.meta.url) is
// unreliable in dev). If AudioWorklet is unavailable or fails to load, we fall back to a
// ScriptProcessorNode (deprecated but works everywhere). All failures throw descriptive
// errors so the UI can show what went wrong instead of failing silently.

const FRAME_MS = 20;

// Stateful linear resampler: AudioContext-rate float32 -> targetRate Int16 frames.
function makeResampler(inputRate: number, targetRate: number, onFrame: (pcm: ArrayBuffer) => void) {
  const ratio = inputRate / targetRate;
  const frameSamples = Math.round(targetRate * (FRAME_MS / 1000));
  let acc: number[] = [];
  let pos = 0;
  return (channel: Float32Array) => {
    let p = pos;
    for (; p < channel.length; p += ratio) {
      const i = Math.floor(p);
      const frac = p - i;
      const a = channel[i] || 0;
      const b = channel[i + 1] !== undefined ? channel[i + 1] : a;
      let s = a + (b - a) * frac;
      s = Math.max(-1, Math.min(1, s));
      acc.push(s < 0 ? s * 0x8000 : s * 0x7fff);
      if (acc.length >= frameSamples) {
        const pcm = new Int16Array(acc.length);
        for (let j = 0; j < acc.length; j++) pcm[j] = acc[j] | 0;
        acc = [];
        onFrame(pcm.buffer);
      }
    }
    pos = p - channel.length;
  };
}

export class MicRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private worklet: AudioWorkletNode | null = null;
  private script: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  mode: "worklet" | "scriptprocessor" | null = null;

  async start(targetRate: number, onFrame: (pcm: ArrayBuffer) => void): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser does not expose microphone access (getUserMedia).");
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      throw new Error(`Microphone access denied or unavailable: ${(e as Error).message}`);
    }

    this.ctx = new AudioContext();
    if (this.ctx.state === "suspended") {
      await this.ctx.resume().catch(() => undefined);
    }
    this.source = this.ctx.createMediaStreamSource(this.stream);

    if (this.ctx.audioWorklet) {
      try {
        await this.startWorklet(targetRate, onFrame);
        this.mode = "worklet";
        return;
      } catch (e) {
        console.warn("[FORGE] AudioWorklet capture failed, falling back to ScriptProcessor:", e);
      }
    }
    this.startScriptProcessor(targetRate, onFrame);
    this.mode = "scriptprocessor";
  }

  private async startWorklet(targetRate: number, onFrame: (pcm: ArrayBuffer) => void): Promise<void> {
    const ctx = this.ctx!;
    try {
      await ctx.audioWorklet.addModule("/recorder-worklet.js");
    } catch (e) {
      throw new Error(`audio engine (worklet) failed to load: ${(e as Error).message}`);
    }
    const node = new AudioWorkletNode(ctx, "forge-recorder", { processorOptions: { targetRate } });
    node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onFrame(e.data);
    // mic -> worklet -> muted gain -> destination (the node must reach a destination
    // to be pulled, but we don't want to hear the mic).
    this.source!.connect(node);
    const sink = ctx.createGain();
    sink.gain.value = 0;
    node.connect(sink);
    sink.connect(ctx.destination);
    this.worklet = node;
  }

  private startScriptProcessor(targetRate: number, onFrame: (pcm: ArrayBuffer) => void): void {
    const ctx = this.ctx!;
    const node = ctx.createScriptProcessor(4096, 1, 1);
    const resample = makeResampler(ctx.sampleRate, targetRate, onFrame);
    node.onaudioprocess = (e: AudioProcessingEvent) => resample(e.inputBuffer.getChannelData(0));
    this.source!.connect(node);
    const sink = ctx.createGain();
    sink.gain.value = 0;
    node.connect(sink);
    sink.connect(ctx.destination);
    this.script = node;
  }

  stop(): void {
    if (this.worklet) {
      this.worklet.port.close();
      this.worklet.disconnect();
    }
    if (this.script) {
      this.script.onaudioprocess = null;
      this.script.disconnect();
    }
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    this.stream = null;
    this.worklet = null;
    this.script = null;
    this.source = null;
    this.mode = null;
  }

  get active(): boolean {
    return this.ctx !== null;
  }
}
