// FORGE audio playback: schedules 24 kHz PCM16 output chunks from Qwen with a small
// jitter buffer, and drains instantly on a server interruption (barge-in).

export class AudioPlayer {
  private ctx: AudioContext | null = null;
  private playhead = 0;
  private readonly lookahead = 0.08; // 80 ms jitter buffer
  private sources: AudioBufferSourceNode[] = [];
  private gain: GainNode | null = null;
  speaking = false;

  constructor(private readonly sampleRate = 24000) {}

  private ensure(): AudioContext {
    if (!this.ctx) {
      this.ctx = new AudioContext({ sampleRate: this.sampleRate });
      this.gain = this.ctx.createGain();
      this.gain.connect(this.ctx.destination);
      this.playhead = this.ctx.currentTime;
    }
    return this.ctx;
  }

  async resume(): Promise<void> {
    const ctx = this.ensure();
    if (ctx.state === "suspended") await ctx.resume();
  }

  // Enqueue a chunk of Int16 little-endian PCM (an ArrayBuffer from the WS).
  enqueue(pcm: ArrayBuffer): void {
    const ctx = this.ensure();
    const ints = new Int16Array(pcm);
    if (ints.length === 0) return;
    const buffer = ctx.createBuffer(1, ints.length, this.sampleRate);
    const ch = buffer.getChannelData(0);
    for (let i = 0; i < ints.length; i++) ch[i] = ints[i] / 0x8000;

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.gain!);

    const now = ctx.currentTime;
    if (this.playhead < now + this.lookahead) this.playhead = now + this.lookahead;
    src.start(this.playhead);
    this.playhead += buffer.duration;
    this.speaking = true;

    this.sources.push(src);
    src.onended = () => {
      this.sources = this.sources.filter((s) => s !== src);
      if (this.sources.length === 0) this.speaking = false;
    };
  }

  // Barge-in: stop everything queued and reset the playhead immediately.
  drain(): void {
    for (const src of this.sources) {
      try {
        src.onended = null;
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources = [];
    this.speaking = false;
    if (this.ctx) this.playhead = this.ctx.currentTime;
  }

  close(): void {
    this.drain();
    this.ctx?.close();
    this.ctx = null;
  }
}
