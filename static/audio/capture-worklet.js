// Mic capture -> 16 kHz little-endian Int16 chunks (~40 ms) posted to the main thread,
// which base64s them onto the Live WebSocket.
//
// Preferred path: the AudioContext itself runs at 16 kHz, so the BROWSER resamples the mic
// (properly filtered) and this worklet just converts. Fallback (browsers that can't mix
// sample rates, e.g. Firefox): the context runs at the device rate and we downsample here --
// averaging each output sample's source window first, as a simple anti-aliasing low-pass,
// because naive sample-picking folds high frequencies into the speech band and hurts
// recognition.
const TARGET_RATE = 16000;
const CHUNK_SAMPLES = 640; // 40 ms at 16 kHz

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE; // `sampleRate` is the context's rate (global here)
    this.acc = 0; // running sum of source samples for the current output sample
    this.accN = 0;
    this.need = this.ratio; // source samples still needed for the current output sample
    this.out = new Int16Array(CHUNK_SAMPLES);
    this.outLen = 0;
  }

  emit(sample) {
    const s = Math.max(-1, Math.min(1, sample));
    this.out[this.outLen++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    if (this.outLen === CHUNK_SAMPLES) {
      this.port.postMessage(this.out.buffer, [this.out.buffer]);
      this.out = new Int16Array(CHUNK_SAMPLES);
      this.outLen = 0;
    }
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    if (this.ratio === 1) {
      for (let i = 0; i < input.length; i++) this.emit(input[i]);
      return true;
    }
    // Box-filter decimation: each output sample is the mean of its ~ratio source samples.
    for (let i = 0; i < input.length; i++) {
      this.acc += input[i];
      this.accN += 1;
      this.need -= 1;
      if (this.need <= 0) {
        this.emit(this.acc / this.accN);
        this.acc = 0;
        this.accN = 0;
        this.need += this.ratio;
      }
    }
    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
