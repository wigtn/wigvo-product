"""Silero VAD v5 vs v6 자체 eval — 전화망(8kHz μ-law) 채널, 동일 파이프라인.

목적: WI-2에서 v5→v6로 바꾼 게 실제로 얼마나 좋아졌는지 수치로 재검증.

공정성 원칙 — **변수를 하나만 둔다**:
  현재 wigvo-product `LocalVAD`(에코 뒤 단계·8k→16k 어댑터·RMS 게이트·상태머신·임계값)를
  v5·v6에 100% 동일하게 쓰고, **Silero 모델만 스왑**한다. 옛 윅보 레포의 v5 경로는
  파이프라인이 달라 교란변수가 되므로 쓰지 않는다 (가중치 .onnx만 가져와 현재 코드에 태움).

realism: 실통화 녹음은 미보관(privacy)이고 프레임 정답 라벨도 없다. 대신 이 VAD가 실제로
  도는 채널(Twilio 8kHz g711_μlaw)을 라벨된 합성 음성에 그대로 입혀, 정답 라벨을 유지한 채
  실통화 조건을 재현한다. 음성은 macOS `say` TTS(KO/EN), 무음 간격·SNR 스윕 노이즈는 합성.

지표(프레임 20ms 단위):
  - FRR  발화인데 놓친 비율 (miss)
  - FAR  비발화인데 발화로 오검 (false alarm)
  - 검출률  발화 단위로 온셋을 잡았는지
  - 온셋 지연  발화 시작→SPEAKING 전환까지 (ms)

실행:
  cd apps/relay-server
  uv run python scripts/vad_version_eval.py            # 합성 코퍼스 자동 생성·캐시
  uv run python scripts/vad_version_eval.py --json out.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# 현재 레포 파이프라인을 그대로 쓴다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.realtime.audio_utils import ulaw_to_float32  # noqa: E402
from src.realtime import local_vad as lv  # noqa: E402

SR = 8000          # 입력 sample rate (Twilio)
FRAME_MS = 20
FRAME_SAMPLES = SR * FRAME_MS // 1000   # 160
MODELS_DIR = Path(__file__).resolve().parent.parent / "src" / "realtime" / "models"
V5_PATH = MODELS_DIR / "silero_vad_v5.onnx"
V6_PATH = MODELS_DIR / "silero_vad_v6.onnx"
CACHE = Path(__file__).resolve().parent / "_vad_eval_cache"

# ─────────────────────────────── G.711 μ-law 인코더 ───────────────────────────
# audio_utils엔 디코더(ulaw_to_float32)만 있어 인코더를 직접 둔다. 라운드트립 자가검증함.
_EXP_LUT = np.array(
    [0, 0, 1, 1, 2, 2, 2, 2] + [3] * 8 + [4] * 16 + [5] * 32 + [6] * 64 + [7] * 128,
    dtype=np.int32,
)


def pcm16_to_ulaw(pcm16: np.ndarray) -> np.ndarray:
    """int16 PCM → μ-law uint8 (G.711)."""
    BIAS, CLIP = 0x84, 32635
    x = pcm16.astype(np.int32)
    sign = np.where(x < 0, 0x80, 0x00).astype(np.int32)
    mag = np.minimum(np.abs(x), CLIP) + BIAS
    exponent = _EXP_LUT[(mag >> 7) & 0xFF]
    mantissa = (mag >> (exponent + 3)) & 0x0F
    ulaw = (~(sign | (exponent << 4) | mantissa)) & 0xFF
    return ulaw.astype(np.uint8)


def _selftest_ulaw() -> None:
    """인코더가 레포 디코더와 라운드트립되는지 확인 (틀리면 즉시 중단)."""
    t = np.arange(SR) / SR
    sig = (np.sin(2 * np.pi * 220 * t) * 12000).astype(np.int16)
    back = ulaw_to_float32(pcm16_to_ulaw(sig).tobytes())
    ref = sig.astype(np.float32) / 32768.0
    corr = float(np.corrcoef(ref, back)[0, 1])
    assert corr > 0.99, f"μ-law 인코더 라운드트립 실패 (corr={corr:.4f})"


# ─────────────────────────────── 합성 코퍼스 ───────────────────────────────
UTTERANCES = [
    ("Yuna", "안녕하세요, 통역 서비스에 연결되었습니다."),
    ("Yuna", "네, 무엇을 도와드릴까요?"),
    ("Yuna", "잠시만 기다려 주세요, 확인해 보겠습니다."),
    ("Eddy", "예약을 변경하고 싶은데 가능할까요?"),
    ("Sandy", "감사합니다, 좋은 하루 되세요."),
    ("Yuna", "죄송합니다, 다시 한 번 말씀해 주시겠어요?"),
    ("Samantha", "Hello, thank you for calling our support line."),
    ("Samantha", "Could you please tell me your reservation number?"),
    ("Daniel", "I would like to check the status of my order."),
    ("Samantha", "One moment please, let me look that up for you."),
    ("Eddy", "요금은 어떻게 결제하면 되나요?"),
    ("Yuna", "확인되었습니다. 도움이 더 필요하신가요?"),
]


def _say_clip(voice: str, text: str, idx: int) -> np.ndarray:
    """say→afconvert로 8kHz mono int16 PCM 생성 → float32[-1,1]."""
    CACHE.mkdir(exist_ok=True)
    aiff = CACHE / f"clip_{idx}.aiff"
    wav = CACHE / f"clip_{idx}.wav"
    if not wav.exists():
        subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
        # 8kHz, 16-bit, mono LEI16 WAV
        subprocess.run(
            ["afconvert", str(aiff), str(wav), "-d", "LEI16@8000", "-f", "WAVE", "-c", "1"],
            check=True,
        )
    with wave.open(str(wav), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        raw = w.readframes(w.getnframes())
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    # 앞뒤 무음 트림 (say가 붙이는 여백 제거 — 발화 경계 라벨 정확도)
    energy = np.abs(pcm)
    thr = 0.02
    nz = np.where(energy > thr)[0]
    if len(nz):
        pcm = pcm[max(0, nz[0] - SR // 50): nz[-1] + SR // 50]
    return pcm


@dataclass
class Corpus:
    clips: list = field(default_factory=list)   # float32 8k
    gap_samples: int = SR // 2                    # 0.5s 무음 간격

    def build(self, seed: int = 7):
        _selftest_ulaw()
        self.clips = [_say_clip(v, t, i) for i, (v, t) in enumerate(UTTERANCES)]
        rng = np.random.default_rng(seed)
        parts, mask, regions = [], [], []
        # 선행 무음
        parts.append(np.zeros(self.gap_samples, np.float32))
        mask.append(np.zeros(self.gap_samples, bool))
        for clip in self.clips:
            start = sum(len(p) for p in parts)
            parts.append(clip)
            mask.append(np.ones(len(clip), bool))
            regions.append((start, start + len(clip)))
            g = self.gap_samples + int(rng.integers(0, SR // 4))  # 지터
            parts.append(np.zeros(g, np.float32))
            mask.append(np.zeros(g, bool))
        clean = np.concatenate(parts)
        speech_mask = np.concatenate(mask)
        return clean, speech_mask, regions


def _add_noise(clean: np.ndarray, mask: np.ndarray, snr_db: float, seed: int) -> np.ndarray:
    """발화 구간 RMS 기준 SNR로 백색+저역(전화망 대역) 노이즈 추가."""
    if snr_db is None:
        return clean
    rng = np.random.default_rng(seed)
    speech_rms = float(np.sqrt(np.mean(clean[mask] ** 2))) if mask.any() else 0.02
    noise = rng.standard_normal(len(clean)).astype(np.float32)
    # 전화망 대역 흉내: 간단 이동평균 저역통과
    k = 4
    noise = np.convolve(noise, np.ones(k) / k, mode="same")
    noise_rms = float(np.sqrt(np.mean(noise ** 2)))
    target = speech_rms / (10 ** (snr_db / 20))
    noise *= target / (noise_rms + 1e-9)
    return np.clip(clean + noise, -1.0, 1.0)


def to_ulaw_frames(sig: np.ndarray) -> list[bytes]:
    pcm16 = np.clip(sig * 32768.0, -32768, 32767).astype(np.int16)
    ulaw = pcm16_to_ulaw(pcm16)
    n = (len(ulaw) // FRAME_SAMPLES) * FRAME_SAMPLES
    return [ulaw[i:i + FRAME_SAMPLES].tobytes() for i in range(0, n, FRAME_SAMPLES)]


# ─────────────────────────── v5 래퍼 (현재 v6 래퍼 대칭) ───────────────────────────
class _SileroV5Model:
    """v5 추론기. 컨텍스트 없이 512샘플 그대로 (v6의 64컨텍스트/576과 대비)."""

    def __init__(self, session):
        self._session = session
        self._sr = np.array(SR * 2, dtype=np.int64)  # 16000
        self.reset()

    def reset(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def process(self, frame) -> float:
        f = np.frombuffer(frame, dtype=np.float32).reshape(1, -1)
        out = self._session.run(None, {"input": f, "state": self._state, "sr": self._sr})
        self._state = out[1]
        return float(np.asarray(out[0]).reshape(-1)[0])


def _make_session(path: Path):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    so.inter_op_num_threads = 1
    return ort.InferenceSession(str(path), sess_options=so)


# ─────────────────────────────── eval 구동 ───────────────────────────────
@dataclass
class Run:
    per_frame_speaking: list = field(default_factory=list)   # (frame_idx, is_speaking)


async def run_version(version: str, frames: list[bytes]) -> list[bool]:
    """현재 LocalVAD를 그대로 쓰고 모델만 스왑. 프레임별 is_speaking 반환."""
    vad = lv.LocalVAD()  # 프로덕션 기본값 (임계값·hysteresis 동일)
    if version == "v5":
        vad._model = _SileroV5Model(_make_session(V5_PATH))
    else:
        vad._model = lv._SileroV6Model(_make_session(V6_PATH))
    vad._model.reset()

    speaking = []
    for fr in frames:
        await vad.process(fr)
        speaking.append(vad.is_speaking)
    return speaking


def frame_mask_from_samples(speech_mask: np.ndarray, n_frames: int) -> np.ndarray:
    """샘플 단위 정답 → 프레임 단위 (프레임 과반이 발화면 speech)."""
    out = np.zeros(n_frames, bool)
    for i in range(n_frames):
        seg = speech_mask[i * FRAME_SAMPLES:(i + 1) * FRAME_SAMPLES]
        out[i] = seg.mean() > 0.5 if len(seg) else False
    return out


def metrics(gt: np.ndarray, pred: list[bool], regions):
    pred = np.array(pred[: len(gt)], bool)
    gt = gt[: len(pred)]
    speech, nonspeech = gt, ~gt
    frr = float((~pred[speech]).mean()) if speech.any() else float("nan")
    # FAR은 "깊은 무음"에서만 — 발화 종료 후 hold-over(오프셋 hysteresis, ~480ms)는
    # 설계된 유지 구간이라 오검이 아니다. 발화 종료 GUARD 프레임 이후만 진짜 무음으로 본다.
    GUARD = 30  # 30 × 20ms = 600ms (480ms hold-over + 여유)
    deep = nonspeech.copy()
    for (s, e) in regions:
        fe = e // FRAME_SAMPLES
        deep[fe: fe + GUARD] = False
    far = float((pred[nonspeech]).mean()) if nonspeech.any() else float("nan")
    far_deep = float((pred[deep]).mean()) if deep.any() else float("nan")
    # 발화 단위 검출 + 온셋 지연
    detected, latencies = 0, []
    for (s, e) in regions:
        fs, fe = s // FRAME_SAMPLES, e // FRAME_SAMPLES
        win = pred[fs: min(fe + 15, len(pred))]  # 발화 끝+300ms 여유
        hit = np.where(win)[0]
        if len(hit):
            detected += 1
            latencies.append(hit[0] * FRAME_MS)
    det_rate = detected / len(regions) if regions else float("nan")
    med_lat = float(np.median(latencies)) if latencies else float("nan")
    return {
        "frr": round(frr * 100, 1),
        "far_deep": round(far_deep * 100, 1),
        "far_incl_holdover": round(far * 100, 1),
        "detect_rate": round(det_rate * 100, 1),
        "median_onset_ms": round(med_lat, 0),
        "n_detected": detected,
        "n_utterances": len(regions),
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=str, default="")
    ap.add_argument("--snrs", type=str, default="clean,20,10,5")
    ap.add_argument("--seeds", type=str, default="11,23,42,71,88")
    args = ap.parse_args()

    for p in (V5_PATH, V6_PATH):
        if not p.exists():
            print(f"모델 없음: {p}", file=sys.stderr)
            sys.exit(1)

    print("합성 코퍼스 생성 (say TTS, 캐시=%s) ..." % CACHE)
    clean, speech_mask, regions = Corpus().build()
    dur = len(clean) / SR
    print(f"  발화 {len(regions)}개 · 총 {dur:.1f}s · 발화비율 {speech_mask.mean()*100:.0f}%")

    snr_list = [None if s == "clean" else float(s) for s in args.snrs.split(",")]
    seeds = [int(x) for x in args.seeds.split(",")]
    keys = ("frr", "far_deep", "far_incl_holdover", "detect_rate", "median_onset_ms")
    results = {}
    for snr in snr_list:
        label = "clean" if snr is None else f"{int(snr)}dB"
        row = {}
        for ver in ("v5", "v6"):
            # 노이즈 시드 여러 개로 평균 (clean은 시드 무관하지만 동일 경로로 처리)
            acc = {k: [] for k in keys}
            for sd in seeds:
                sig = _add_noise(clean, speech_mask, snr, seed=sd)
                frames = to_ulaw_frames(sig)
                gt = frame_mask_from_samples(speech_mask, len(frames))
                m = metrics(gt, await run_version(ver, frames), regions)
                for k in keys:
                    acc[k].append(m[k])
            row[ver] = {k: round(float(np.mean(v)), 1) for k, v in acc.items()}
            row[ver]["n_seeds"] = len(seeds)
        results[label] = row

    # 출력 표
    print("\n" + "=" * 72)
    print("Silero v5 vs v6 — 전화망 8kHz μ-law, 동일 LocalVAD 파이프라인")
    print("=" * 72)
    hdr = (f"{'조건':<8} {'모델':<4} {'FRR%':>6} {'FAR%':>6} {'검출%':>7} "
           f"{'온셋ms':>7}   (FAR=깊은무음 기준)")
    print(hdr)
    print("-" * 72)
    for label, row in results.items():
        for ver in ("v5", "v6"):
            m = row[ver]
            print(f"{label:<8} {ver:<4} {m['frr']:>6} {m['far_deep']:>6} "
                  f"{m['detect_rate']:>7} {m['median_onset_ms']:>7.0f}")
        print("-" * 72)

    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"JSON 저장: {args.json}")


if __name__ == "__main__":
    asyncio.run(main())
