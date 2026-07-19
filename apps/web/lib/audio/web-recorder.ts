/**
 * Web Audio API microphone recorder.
 * Captures PCM16 audio chunks via AudioWorklet (ScriptProcessorNode fallback).
 * Far-field chain: high-pass filter + Speex denoiser (WASM AudioWorklet) + AGC,
 * on top of the browser's built-in noiseSuppression/echoCancellation.
 * Output: base64-encoded PCM16 chunks (1600 samples = 100ms @ 16kHz).
 */

import type { SpeexWorkletNode } from '@sapphi-red/web-noise-suppressor';
import { arrayBufferToBase64, float32ToPcm16, SAMPLE_RATE } from './pcm16-utils';

const CHUNK_SIZE = 1600; // 100ms @ 16kHz

// Speex denoiser assets copied from @sapphi-red/web-noise-suppressor dist
// into public/ (AudioWorklet modules and wasm must be fetched by URL).
const SPEEX_WORKLET_URL = '/noise-suppressor/speexWorklet.js';
const SPEEX_WASM_URL = '/noise-suppressor/speex.wasm';

// High-pass cutoff: removes low-frequency rumble/hum below the voice band.
const HIGHPASS_FREQUENCY_HZ = 100;

// 근접 발화 정규화(near-field normalization).
//
// ⚠️ 목적이 바뀌었다. 처음에는 '멀리 있는 발화를 살리자'(far-field 강화)로
// 만들었으나, 이 제품에서 원거리 소리는 응대자 본인이 아니라 옆자리 동료·다른
// 민원인이다 — 살릴 대상이 아니라 **막을 대상**이다. 실사용 피드백:
// "너무 민감함, 멀리서 사람이 말해도 그게 다 들어감"(2026-07-19).
// 게인을 크게 주면 원거리 음성이 서버 커밋 게이트를 그대로 통과한다.
// 따라서 게인은 '녹음 레벨이 낮은 마이크 보정' 수준으로만 남긴다.
// 청크 단위 EMA 추적, 게인은 [1, AGC_MAX_GAIN]으로 클램프한다.
const AGC_TARGET_RMS = 0.05;
// 8배는 먼 목소리까지 발화 수준으로 끌어올려 게이트를 무력화했다.
// 마이크 레벨 편차 보정에 필요한 최소한만 남긴다.
const AGC_MAX_GAIN = 2;
const AGC_LEVEL_EMA = 0.9; // previous-level weight per 100ms chunk
// 증폭 대상 게이트. 이 값 미만 청크는 손대지 않는다.
// 두 가지 역할을 겸한다.
//  1) 무음 구간에서 레벨 EMA가 바닥까지 내려가 다음 청크에 최대 게인이 붙는 것을
//     막는다 — 그러면 주변 웅성거림이 발화 수준으로 올라가고, VAD가 세그먼트를
//     끊는 데 필요한 무음이 사라져 옆사람 말이 같은 커밋에 실린다.
//  2) 원거리 음성을 애초에 증폭 대상에서 뺀다(근접 수음 목표).
// 이 값보다 작은 청크는 증폭하지 않는다. 원거리 음성을 발화 수준으로
// 끌어올리지 않도록 근접 발화 대역만 대상으로 삼는다.
// ClientVAD speechThreshold(0.035)와 연동한다. 게이트를 임계/게인보다 낮게 두면
// 원거리 청크가 증폭 후 임계를 넘어 통과하므로(0.0175×2 = 0.035), 그 경계를
// 넘지 않도록 임계와 같은 값으로 맞춘다 — 증폭은 '이미 발화로 인정된 크기'에만
// 적용되고, 판정 자체를 뒤집지 않는다.
const AGC_GATE_RMS = 0.035;

interface SpeexAssets {
  SpeexWorkletNode: typeof SpeexWorkletNode;
  wasmBinary: ArrayBuffer;
}

// Loaded once per page; recorder instances are recreated per call.
// The package is imported dynamically because it touches browser-only
// globals (AudioWorkletNode) at module scope, which breaks SSR.
let speexAssetsPromise: Promise<SpeexAssets> | null = null;

function loadSpeexAssets(): Promise<SpeexAssets> {
  if (!speexAssetsPromise) {
    speexAssetsPromise = (async () => {
      const mod = await import('@sapphi-red/web-noise-suppressor');
      const wasmBinary = await mod.loadSpeex({ url: SPEEX_WASM_URL });
      return { SpeexWorkletNode: mod.SpeexWorkletNode, wasmBinary };
    })().catch((err) => {
      speexAssetsPromise = null;
      throw err;
    });
  }
  return speexAssetsPromise;
}

export type ChunkCallback = (base64Audio: string, float32Samples: Float32Array) => void;

/**
 * AudioWorklet processor source code (inlined to avoid separate file hosting).
 * Collects samples and posts them to the main thread in CHUNK_SIZE batches.
 */
const WORKLET_PROCESSOR_CODE = `
class Pcm16CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(${CHUNK_SIZE});
    this.writeIndex = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const channelData = input[0];
    let readIndex = 0;

    while (readIndex < channelData.length) {
      const remaining = ${CHUNK_SIZE} - this.writeIndex;
      const available = channelData.length - readIndex;
      const toCopy = Math.min(remaining, available);

      this.buffer.set(
        channelData.subarray(readIndex, readIndex + toCopy),
        this.writeIndex
      );
      this.writeIndex += toCopy;
      readIndex += toCopy;

      if (this.writeIndex >= ${CHUNK_SIZE}) {
        this.port.postMessage({ samples: this.buffer.slice() });
        this.writeIndex = 0;
      }
    }

    return true;
  }
}

registerProcessor('pcm16-capture-processor', Pcm16CaptureProcessor);
`;

export class WebAudioRecorder {
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private highpassNode: BiquadFilterNode | null = null;
  private speexNode: SpeexWorkletNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private scriptProcessorNode: ScriptProcessorNode | null = null;
  private isActive = false;
  private onChunkCallback: ChunkCallback | null = null;

  // ScriptProcessorNode fallback buffer
  private spnBuffer: Float32Array = new Float32Array(CHUNK_SIZE);
  private spnWriteIndex = 0;

  // Far-field AGC state (chunk-level EMA of input level)
  private agcLevel = AGC_TARGET_RMS;

  /** Register a callback for audio chunks. */
  onChunk(callback: ChunkCallback): void {
    this.onChunkCallback = callback;
  }

  /** Start recording from the microphone. */
  async start(): Promise<void> {
    if (this.isActive) return;

    // Request microphone access
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: SAMPLE_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    // Create AudioContext with target sample rate
    this.audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });

    // Safari: resume on user gesture context
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }

    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);

    // Far-field front-end: high-pass → Speex denoiser (best effort).
    // Speex load failure degrades to high-pass only — never blocks the call.
    this.highpassNode = this.audioContext.createBiquadFilter();
    this.highpassNode.type = 'highpass';
    this.highpassNode.frequency.value = HIGHPASS_FREQUENCY_HZ;
    this.sourceNode.connect(this.highpassNode);

    let captureInput: AudioNode = this.highpassNode;
    try {
      const speex = await loadSpeexAssets();
      this.speexNode = new speex.SpeexWorkletNode(this.audioContext, {
        wasmBinary: speex.wasmBinary,
        maxChannels: 1,
      });
      this.highpassNode.connect(this.speexNode);
      captureInput = this.speexNode;
    } catch {
      // Denoiser unavailable (asset/load failure) — proceed with high-pass only.
    }

    this.agcLevel = AGC_TARGET_RMS;

    // Try AudioWorklet first, fall back to ScriptProcessorNode
    const workletAvailable = await this.trySetupWorklet(captureInput);
    if (!workletAvailable) {
      this.setupScriptProcessor(captureInput);
    }

    this.isActive = true;
  }

  /** Stop recording and release resources. */
  stop(): void {
    if (!this.isActive) return;
    this.isActive = false;

    if (this.workletNode) {
      this.workletNode.disconnect();
      this.workletNode = null;
    }

    if (this.scriptProcessorNode) {
      this.scriptProcessorNode.disconnect();
      this.scriptProcessorNode = null;
    }

    if (this.speexNode) {
      this.speexNode.disconnect();
      this.speexNode.destroy();
      this.speexNode = null;
    }

    if (this.highpassNode) {
      this.highpassNode.disconnect();
      this.highpassNode = null;
    }

    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }

    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    this.spnWriteIndex = 0;
  }

  /** Whether the recorder is currently active. */
  get recording(): boolean {
    return this.isActive;
  }

  private async trySetupWorklet(captureInput: AudioNode): Promise<boolean> {
    if (!this.audioContext) return false;

    try {
      const blob = new Blob([WORKLET_PROCESSOR_CODE], { type: 'application/javascript' });
      const url = URL.createObjectURL(blob);

      await this.audioContext.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);

      this.workletNode = new AudioWorkletNode(this.audioContext, 'pcm16-capture-processor');
      this.workletNode.port.onmessage = (event: MessageEvent) => {
        const { samples } = event.data as { samples: Float32Array };
        this.emitChunk(samples);
      };

      captureInput.connect(this.workletNode);
      this.workletNode.connect(this.audioContext.destination);

      return true;
    } catch {
      return false;
    }
  }

  private setupScriptProcessor(captureInput: AudioNode): void {
    if (!this.audioContext) return;

    // Buffer size 4096 is widely supported
    this.scriptProcessorNode = this.audioContext.createScriptProcessor(4096, 1, 1);
    this.spnWriteIndex = 0;

    this.scriptProcessorNode.onaudioprocess = (event: AudioProcessingEvent) => {
      const inputData = event.inputBuffer.getChannelData(0);
      let readIndex = 0;

      while (readIndex < inputData.length) {
        const remaining = CHUNK_SIZE - this.spnWriteIndex;
        const available = inputData.length - readIndex;
        const toCopy = Math.min(remaining, available);

        this.spnBuffer.set(
          inputData.subarray(readIndex, readIndex + toCopy),
          this.spnWriteIndex
        );
        this.spnWriteIndex += toCopy;
        readIndex += toCopy;

        if (this.spnWriteIndex >= CHUNK_SIZE) {
          this.emitChunk(this.spnBuffer.slice());
          this.spnWriteIndex = 0;
        }
      }

      // Pass-through silence to keep the processor alive
      const outputData = event.outputBuffer.getChannelData(0);
      outputData.fill(0);
    };

    captureInput.connect(this.scriptProcessorNode);
    this.scriptProcessorNode.connect(this.audioContext.destination);
  }

  /**
   * Far-field AGC (chunk-level): track the input level with an EMA and lift
   * quiet speech chunks toward AGC_TARGET_RMS, gain clamped to [1, AGC_MAX_GAIN].
   * Runs after the denoiser (graph order), so noise is not re-amplified.
   *
   * Speech-gated: chunks below AGC_GATE_RMS are passed through and excluded
   * from level tracking, so pauses keep their real noise floor and the VAD can
   * still close segments between utterances.
   */
  private applyAgc(samples: Float32Array): Float32Array {
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    const rms = Math.sqrt(sum / samples.length) + 1e-9;
    if (rms < AGC_GATE_RMS) return samples;
    this.agcLevel =
      AGC_LEVEL_EMA * this.agcLevel + (1 - AGC_LEVEL_EMA) * Math.max(rms, 1e-4);
    const gain = Math.min(AGC_MAX_GAIN, Math.max(1, AGC_TARGET_RMS / this.agcLevel));
    if (gain <= 1.001) return samples;
    const out = new Float32Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      const v = samples[i] * gain;
      out[i] = v > 1 ? 1 : v < -1 ? -1 : v;
    }
    return out;
  }

  private emitChunk(float32Samples: Float32Array): void {
    if (!this.onChunkCallback) return;
    const processed = this.applyAgc(float32Samples);
    const pcm16Buffer = float32ToPcm16(processed);
    const base64 = arrayBufferToBase64(pcm16Buffer);
    this.onChunkCallback(base64, processed);
  }
}
