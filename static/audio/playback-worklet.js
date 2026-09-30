// Tutor audio playback: a queue of 24 kHz Int16 chunks (the AudioContext itself
// runs at 24 kHz). "flush" empties it instantly so he can talk over the tutor.
class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.current = null;
    this.offset = 0;
    this.playing = false;
    this.port.onmessage = (e) => {
      if (e.data === "flush") {
        this.queue = [];
        this.current = null;
        this.offset = 0;
      } else {
        this.queue.push(new Int16Array(e.data));
      }
    };
  }

  process(_inputs, outputs) {
    const out = outputs[0][0];
    let written = 0;
    while (written < out.length) {
      if (!this.current) {
        this.current = this.queue.shift() || null;
        this.offset = 0;
        if (!this.current) break;
      }
      const n = Math.min(out.length - written, this.current.length - this.offset);
      for (let i = 0; i < n; i++) out[written + i] = this.current[this.offset + i] / 0x8000;
      written += n;
      this.offset += n;
      if (this.offset >= this.current.length) this.current = null;
    }
    out.fill(0, written);
    const nowPlaying = written > 0;
    if (nowPlaying !== this.playing) {
      this.playing = nowPlaying;
      this.port.postMessage({ playing: nowPlaying });
    }
    return true;
  }
}

registerProcessor("playback-processor", PlaybackProcessor);
