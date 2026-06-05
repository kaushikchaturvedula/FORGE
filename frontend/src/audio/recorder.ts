// Mic capture: getUserMedia -> AudioWorklet (downsample to 16 kHz PCM16) -> callback.

export class MicRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;

  async start(targetRate: number, onFrame: (pcm: ArrayBuffer) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule(new URL("./recorder-worklet.js", import.meta.url));
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "forge-recorder", {
      processorOptions: { targetRate },
    });
    this.node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onFrame(e.data);
    this.source.connect(this.node);
    // The worklet has no audible output; connect to a muted destination to keep it pulled.
    const sink = this.ctx.createGain();
    sink.gain.value = 0;
    this.node.connect(sink);
    sink.connect(this.ctx.destination);
  }

  stop(): void {
    this.node?.port.close();
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.ctx = null;
    this.stream = null;
    this.node = null;
    this.source = null;
  }

  get active(): boolean {
    return this.ctx !== null;
  }
}
