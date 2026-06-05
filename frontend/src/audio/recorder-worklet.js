// FORGE mic capture worklet.
// Runs on the audio thread, downsamples the mic from the AudioContext rate
// (usually 48 kHz) to 16 kHz mono, converts to PCM16, and posts ~20 ms frames to
// the main thread, which forwards them over the WebSocket as binary.

class ForgeRecorder extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this.targetRate = opts.targetRate || 16000;
    this.ratio = sampleRate / this.targetRate; // e.g. 48000/16000 = 3
    this.frameSamples = Math.round(this.targetRate * 0.02); // 20 ms @ target rate
    this.acc = []; // accumulated resampled Int16 samples
    this._pos = 0; // fractional read position into the input block
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel) return true;

    // Linear resample by ratio.
    let pos = this._pos;
    for (; pos < channel.length; pos += this.ratio) {
      const i = Math.floor(pos);
      const frac = pos - i;
      const a = channel[i] || 0;
      const b = channel[i + 1] !== undefined ? channel[i + 1] : a;
      let sample = a + (b - a) * frac;
      sample = Math.max(-1, Math.min(1, sample));
      this.acc.push(sample < 0 ? sample * 0x8000 : sample * 0x7fff);
      if (this.acc.length >= this.frameSamples) {
        this._flush();
      }
    }
    this._pos = pos - channel.length;
    return true;
  }

  _flush() {
    const pcm = new Int16Array(this.acc.length);
    for (let i = 0; i < this.acc.length; i++) pcm[i] = this.acc[i] | 0;
    this.acc = [];
    this.port.postMessage(pcm.buffer, [pcm.buffer]);
  }
}

registerProcessor("forge-recorder", ForgeRecorder);
