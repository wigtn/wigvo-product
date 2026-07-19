"""Session A far-field 하네스 v2 — far-field 체인 OFF vs ON 비교 (Whisper 루프).

v1과의 차이:
  1) VAD 대리지표가 아니라 **실제 Whisper 전사**로 할루시·전사오류를 직접 측정
  2) 핑크노이즈 대신 **다화자 babble**(할루시 실제 트리거) 추가
  3) 출력이 "체인 OFF vs ON" 대조표 — far-field 적용 효과가 한눈에

파이프라인 재현: 조건오디오 → [체인] → ClientVAD 커밋 → 서버 에너지게이트(#86)
                → 살아남은 세그먼트만 Whisper로 전사 → 정답과 대조
"""
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SCR = Path(__file__).parent
SR = 16000
CHUNK = 1600  # 100ms
rng = np.random.default_rng(7)

SENTENCES = [
    "안녕하세요, 무엇을 도와드릴까요?",
    "배송은 보통 이틀 정도 걸립니다.",
    "추가 요금은 없습니다.",
]
BABBLE_LINES = [
    ("그러니까 어제 회의에서 그 얘기가 나왔는데요", "Yuna"),
    ("네 알겠습니다 확인해보고 다시 연락드릴게요", "Sandy"),
    ("이번 주 금요일까지 마감이라고 들었어요", "Shelley"),
    ("점심 뭐 드실래요 아까 그 집 어때요", "Flo"),
]

# ---------- 오디오 준비 ----------

def say_to_16k(text: str, out: Path, voice: str | None = None) -> np.ndarray:
    if not out.exists():
        aiff = out.with_suffix(".aiff")
        cmd = ["say", "-o", str(aiff)] + (["-v", voice] if voice else []) + [text]
        subprocess.run(cmd, check=True)
        subprocess.run(
            ["afconvert", str(aiff), "-o", str(out), "-d", f"LEI16@{SR}", "-f", "WAVE", "-c", "1"],
            check=True,
        )
    w = wave.open(str(out), "rb")
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    w.close()
    return x


def build_speech() -> tuple[np.ndarray, list[tuple[int, int, str]]]:
    """문장 3개 + 사이 무음 1.5s. (신호, [(시작프레임, 끝프레임, 정답텍스트)]) 반환."""
    gap = np.zeros(int(1.5 * SR), dtype=np.float32)
    parts = [np.copy(gap)]
    spans: list[tuple[int, int, str]] = []
    pos = len(gap)
    for i, text in enumerate(SENTENCES):
        x = say_to_16k(text, SCR / f"v2_s{i}.wav", "Yuna")
        spans.append((pos // CHUNK, (pos + len(x)) // CHUNK, text))
        parts += [x, np.copy(gap)]
        pos += len(x) + len(gap)
    sig = np.concatenate(parts)
    n = len(sig) // CHUNK
    return sig[: n * CHUNK], spans


def babble(n: int, level: float) -> np.ndarray:
    """다화자 웅성거림: 여러 목소리를 서로 다른 오프셋으로 겹쳐 사무실 소음 재현.
    핑크노이즈와 달리 Whisper 할루시를 실제로 유발하는 노이즈 유형."""
    out = np.zeros(n, dtype=np.float32)
    for i, (text, voice) in enumerate(BABBLE_LINES):
        v = say_to_16k(text, SCR / f"v2_b{i}.wav", voice)
        reps = int(np.ceil(n / len(v))) + 1
        tiled = np.tile(v, reps)
        off = int(rng.integers(0, len(v)))
        out += tiled[off:off + n]
    rms = np.sqrt(np.mean(out**2)) + 1e-9
    return out / rms * level


def pink(n: int, level: float) -> np.ndarray:
    white = rng.standard_normal(n + 1).astype(np.float32)
    p = np.cumsum(white)[:n]
    p -= p.mean()
    return p / (np.sqrt(np.mean(p**2)) + 1e-9) * level


def synth_rir(rt60: float = 0.4, direct_ratio: float = 0.5) -> np.ndarray:
    n = int(rt60 * SR)
    tail = rng.standard_normal(n).astype(np.float32) * np.exp(-6.9 * np.arange(n) / n)
    tail /= np.abs(tail).sum() / 3.0
    rir = np.zeros(n, dtype=np.float32)
    rir[0] = direct_ratio
    rir += (1 - direct_ratio) * tail
    return rir


def make_condition(clean, dist_gain, reverb, noise_rms, noise_kind="babble"):
    x = clean * dist_gain
    if reverb:
        x = np.convolve(x, synth_rir(), mode="full")[: len(clean)].astype(np.float32)
    noise = babble(len(x), noise_rms) if noise_kind == "babble" else pink(len(x), noise_rms)
    return np.clip(x + noise, -1, 1)

# ---------- far-field 체인 ----------

def highpass(x, fc=100.0):
    a = np.exp(-2 * np.pi * fc / SR)
    b = (1 + a) / 2
    y = np.empty_like(x)
    py = px = 0.0
    for i, v in enumerate(x):
        py = b * (v - px) + a * py
        px = v
        y[i] = py
    return y


def spectral_denoise(x):
    nfft, hop = 512, 128
    win = np.hanning(nfft).astype(np.float32)
    frames = [x[i:i + nfft] * win for i in range(0, len(x) - nfft, hop)]
    S = np.fft.rfft(np.stack(frames), axis=1)
    mag, ph = np.abs(S), np.angle(S)
    idx = np.argsort(mag.sum(axis=1))[: max(4, len(frames) // 10)]
    prof = mag[idx].mean(axis=0)
    S2 = np.maximum(mag - 1.5 * prof, 0.05 * mag) * np.exp(1j * ph)
    y = np.zeros(len(x), dtype=np.float32)
    norm = np.zeros(len(x), dtype=np.float32)
    fr = np.fft.irfft(S2, n=nfft, axis=1).astype(np.float32)
    for k, i in enumerate(range(0, len(x) - nfft, hop)):
        y[i:i + nfft] += fr[k] * win
        norm[i:i + nfft] += win**2
    return y / np.maximum(norm, 1e-6)


def agc(x, target_rms=0.05, max_gain=8.0):
    y = np.empty_like(x)
    level = target_rms
    for i in range(0, len(x), CHUNK):
        c = x[i:i + CHUNK]
        r = float(np.sqrt(np.mean(c**2)) + 1e-9)
        level = 0.9 * level + 0.1 * max(r, 1e-4)
        g = min(max_gain, max(1.0, target_rms / level))
        y[i:i + CHUNK] = c * g
    return np.clip(y, -1, 1)


def agc_gated(x, target_rms=0.05, max_gain=8.0, gate_rms=0.006):
    """게이트형 AGC: 발화로 보이는 청크만 증폭하고, 무음/소음 구간은 건드리지 않는다.
    현행 AGC는 무음에서 레벨이 바닥까지 내려가 게인이 최대로 붙어 소음을 함께 키우고,
    그 결과 VAD가 무음을 못 봐서 세그먼트가 병합된다(옆사람 말까지 전사)."""
    y = np.empty_like(x)
    level = target_rms
    for i in range(0, len(x), CHUNK):
        c = x[i:i + CHUNK]
        r = float(np.sqrt(np.mean(c**2)) + 1e-9)
        if r < gate_rms:
            y[i:i + CHUNK] = c          # 무음/소음: 원음 통과 (노이즈 플로어 유지)
            continue
        level = 0.9 * level + 0.1 * r   # 발화 구간에서만 레벨 추적
        g = min(max_gain, max(1.0, target_rms / level))
        y[i:i + CHUNK] = c * g
    return np.clip(y, -1, 1)


def farfield_chain(x, gated=False):
    d = spectral_denoise(highpass(x))
    return agc_gated(d) if gated else agc(d)

# ---------- ClientVAD (vad.ts 포팅) ----------

class ClientVadSim:
    def __init__(self, adaptive):
        self.adaptive = adaptive
        self.speech_th, self.silence_th = 0.015, 0.008
        self.onset_ms, self.end_ms = 150, 350
        self.floor, self.floor_max = 0.004, 0.04
        self.decay, self.attack = 0.3, 0.05
        self.sp_ratio, self.sil_ratio = 3.0, 1.8

    def commits(self, x) -> list[tuple[int, int]]:
        n = len(x) // CHUNK
        state, sp_t, sil_t, seg0 = "silence", 0, 0, 0
        out = []
        for f in range(n):
            rms = float(np.sqrt(np.mean(x[f * CHUNK:(f + 1) * CHUNK] ** 2)))
            if self.adaptive:
                sp_th = max(self.speech_th, self.floor * self.sp_ratio)
                sil_th = max(self.silence_th, self.floor * self.sil_ratio)
                if rms < sp_th:
                    a = self.decay if rms < self.floor else self.attack
                    self.floor = min(self.floor_max, (1 - a) * self.floor + a * rms)
            else:
                sp_th, sil_th = self.speech_th, self.silence_th
            if state == "silence":
                if rms >= sp_th:
                    sp_t += 100
                    if sp_t >= self.onset_ms:
                        state, seg0, sil_t = "speech", f, 0
                else:
                    sp_t = 0
            else:
                if rms < sil_th:
                    sil_t += 100
                    if sil_t >= self.end_ms:
                        state, sp_t = "silence", 0
                        out.append((seg0, f))
                else:
                    sil_t = 0
        if state == "speech":
            out.append((seg0, n - 1))
        return out


def gate_pass(x, seg, th=250.0) -> bool:
    """서버 커밋 에너지 게이트(#86) 재현: 세그먼트 최대 청크 peak RMS < 250 → 드랍."""
    s = x[seg[0] * CHUNK:(seg[1] + 1) * CHUNK]
    pcm = (np.clip(s, -1, 1) * 32767).astype(np.int16).astype(np.float64)
    peaks = [np.sqrt(np.mean(pcm[i:i + CHUNK] ** 2)) for i in range(0, len(pcm) - CHUNK + 1, CHUNK)]
    return (max(peaks) if peaks else 0.0) >= th

# ---------- Whisper ----------

_client = None

def whisper(x: np.ndarray, seg: tuple[int, int]) -> str:
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI()
    s = x[seg[0] * CHUNK:(seg[1] + 1) * CHUNK]
    if len(s) < SR // 5:  # Whisper 최소 길이 미만이면 패딩
        s = np.concatenate([s, np.zeros(SR // 5 - len(s), dtype=np.float32)])
    path = SCR / "_seg.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(s, -1, 1) * 32767).astype("<i2").tobytes())
    with open(path, "rb") as f:
        try:
            r = _client.audio.transcriptions.create(model="whisper-1", file=f, language="ko")
            return (r.text or "").strip()
        except Exception as e:
            return f"<ERR {e}>"

# ---------- 평가 ----------

def cer(ref: str, hyp: str) -> float:
    """문자 오류율 (한국어는 CER이 WER보다 적합)."""
    r = [c for c in ref if not c.isspace()]
    h = [c for c in hyp if not c.isspace()]
    if not r:
        return 0.0 if not h else 1.0
    d = np.arange(len(h) + 1)
    for i, rc in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hc in enumerate(h, 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (rc != hc))
            prev = cur
    return d[len(h)] / len(r)


def run_arm(cond_audio, spans, arm: str):
    if arm == "OFF":
        x = cond_audio.copy()
    else:
        x = farfield_chain(cond_audio.copy(), gated=(arm == "ON+게이트"))
    segs = ClientVadSim(adaptive=(arm != "OFF")).commits(x)

    n_gate_cut_real = 0
    captured: dict[int, str] = {}   # span index → 전사
    halluc: list[str] = []          # 발화 없는 구간에서 나온 텍스트

    for seg in segs:
        overlaps = [i for i, (a, b, _) in enumerate(spans) if seg[0] <= b and a <= seg[1]]
        if not gate_pass(x, seg):
            if overlaps:
                n_gate_cut_real += 1
            continue
        text = whisper(x, seg)
        if overlaps:
            for i in overlaps:
                captured[i] = (captured.get(i, "") + " " + text).strip()
        elif text:
            halluc.append(text)

    missed = [i for i in range(len(spans)) if i not in captured]
    cers = [cer(spans[i][2], captured[i]) for i in captured]
    dur = sum((b - a + 1) for a, b in segs) * 0.1
    return {
        "seg_dur_s": dur,
        "captured": len(captured),
        "total": len(spans),
        "missed": len(missed),
        "cer": float(np.mean(cers)) * 100 if cers else float("nan"),
        "halluc": len(halluc),
        "halluc_texts": halluc,
        "gate_cut": n_gate_cut_real,
        "commits": len(segs),
    }


def main():
    clean, spans = build_speech()
    conds = {
        "근접·조용": dict(dist_gain=1.0, reverb=False, noise_rms=0.002),
        "1.5m·잔향·babble약": dict(dist_gain=0.35, reverb=True, noise_rms=0.004),
        "1.5m·잔향·babble강": dict(dist_gain=0.35, reverb=True, noise_rms=0.012),
        "3m·잔향·babble약": dict(dist_gain=0.15, reverb=True, noise_rms=0.004),
    }
    print(f"정답 문장 {len(spans)}개 · 조건 {len(conds)}개 × 체인 OFF/ON\n")
    total_s = (spans[-1][1] + 15) * 0.1
    print(f"오디오 총 길이 ≈{total_s:.0f}s · 실발화 구간만 커밋돼야 정상\n")
    print(f"{'조건':20} {'체인':9} {'커밋수':>5} {'커밋길이s':>8} {'전사':>5} {'CER%':>7} {'할루시':>5}")
    print("─" * 66)
    all_h = []
    for cname, kw in conds.items():
        cond = make_condition(clean, **kw)
        for arm in ("OFF", "ON", "ON+게이트"):
            r = run_arm(cond, spans, arm)
            cer_s = "  n/a" if np.isnan(r["cer"]) else f"{r['cer']:6.1f}"
            print(f"{cname:20} {arm:9} {r['commits']:5d} "
                  f"{r['seg_dur_s']:8.1f} {r['captured']}/{r['total']:>3} {cer_s} {r['halluc']:5d}")
            for t in r["halluc_texts"]:
                all_h.append((cname, arm, t))
        print()
    if all_h:
        print("── 할루시 실물 ──")
        for c, arm, t in all_h:
            print(f"  [{c} / {arm}] {t[:70]}")


if __name__ == "__main__":
    main()
