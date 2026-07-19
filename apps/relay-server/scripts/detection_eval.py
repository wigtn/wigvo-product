"""검출률(FRR/FAR) 중심 far-field 평가 — 표준 VAD 지표.

WER 평가(ami_farfield_eval / librispeech_farfield_eval)에서 far-field 체인의
유일한 이득으로 보였던 축이 "발화 유실"이다. 그런데 두 스크립트 모두 검출을
제대로 재지 못한다(LibriSpeech 쪽은 커밋 구간을 합쳐 전사해 검출 실패가 마스킹됨).
이 스크립트는 Whisper 없이 **VAD 레벨에서만** 표준 지표를 잰다:

  FRR (False Rejection Rate) — 실제 발화 프레임 중 커밋되지 못한 비율 (= 유실)
  FAR (False Alarm Rate)     — 비발화 프레임 중 커밋된 비율 (= 소음/옆사람 유입)
  완전유실                    — 발화 전체가 단 한 프레임도 커밋되지 않은 비율

평가 경로는 프로덕션과 동일: [체인] → ClientVAD 커밋 → 서버 에너지 게이트(#86).
API 호출이 없어 표본을 크게 잡을 수 있다.

실행:
  LIBRI_DIR=... RIRS_DIR=... uv run python scripts/detection_eval.py
  AMI_DIR=...   uv run python scripts/detection_eval.py --ami
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from farfield_harness import CHUNK, SR, ClientVadSim, farfield_chain, gate_pass  # noqa: E402
from librispeech_farfield_eval import load_any, load_utterances  # noqa: E402

RIRS = Path(os.environ.get("RIRS_DIR", "./RIRS_NOISES"))
AMI = Path(os.environ.get("AMI_DIR", "."))
N_UTTS = int(os.environ.get("N_UTTS", "300"))
SNR_DBS = [float(x) for x in os.environ.get("SNR_DBS", "20,15,10,5").split(",")]
PAD_S = 2.0  # 발화 앞뒤 비발화 구간 — FAR를 잴 대상

ARMS = [("OFF (파필드 없음)", None), ("ON (원안)", False), ("ON+게이트 (현행)", True)]
rng = random.Random(11)


def covered_frames(sig: np.ndarray, adaptive: bool) -> np.ndarray:
    """프로덕션 경로대로 커밋된 프레임 마스크 (게이트 통과분만)."""
    n = len(sig) // CHUNK
    mask = np.zeros(n, dtype=bool)
    for c in ClientVadSim(adaptive=adaptive).commits(sig):
        if gate_pass(sig, c):
            mask[c[0]:c[1] + 1] = True
    return mask


def score(mask: np.ndarray, truth: np.ndarray) -> tuple[int, int, int, int, bool]:
    n = min(len(mask), len(truth))
    mask, truth = mask[:n], truth[:n]
    miss = int((~mask & truth).sum())          # 발화인데 미커밋
    hit = int((mask & truth).sum())
    fa = int((mask & ~truth).sum())            # 비발화인데 커밋
    nonspeech = int((~truth).sum())
    return miss, hit, fa, nonspeech, not (mask & truth).any()


def report(rows: dict[str, list[tuple]], title: str) -> None:
    print(f"\n{title}")
    print(f"{'체인':24} {'FRR%':>7} {'FAR%':>7} {'완전유실%':>9}")
    print("─" * 52)
    for name, _ in ARMS:
        miss = sum(r[0] for r in rows[name])
        hit = sum(r[1] for r in rows[name])
        fa = sum(r[2] for r in rows[name])
        ns = sum(r[3] for r in rows[name])
        lost = sum(1 for r in rows[name] if r[4])
        frr = miss / max(1, miss + hit) * 100
        far = fa / max(1, ns) * 100
        print(f"{name:24} {frr:7.1f} {far:7.1f} {lost / max(1, len(rows[name])) * 100:9.1f}")


# ---------------- LibriSpeech + 실측 RIR + 실제 소음 ----------------

def run_librispeech() -> None:
    utts = load_utterances(N_UTTS)
    rirs = [load_any(p) for p in sorted((RIRS / "real_rirs_isotropic_noises").glob("*.wav"))[:20]]
    noises = [load_any(p) for p in sorted((RIRS / "pointsource_noises").glob("*.wav"))[:20]]
    print(f"LibriSpeech 발화 {len(utts)}개 · 실측 RIR {len(rirs)}종 · 실제 소음 {len(noises)}종")
    print(f"발화 앞뒤 비발화 {PAD_S}s (FAR 측정 구간)")

    pad = int(PAD_S * SR)
    for snr in SNR_DBS:
        rows: dict[str, list[tuple]] = {name: [] for name, _ in ARMS}
        for i, (speech, _) in enumerate(utts):
            rev = np.convolve(speech, rirs[i % len(rirs)])[: len(speech)].astype(np.float32)
            rev = rev / (np.sqrt(np.mean(rev**2)) + 1e-9) * 0.05

            body = np.concatenate([np.zeros(pad, np.float32), rev, np.zeros(pad, np.float32)])
            noise = noises[i % len(noises)]
            noise = np.tile(noise, int(np.ceil(len(body) / len(noise))))[: len(body)]
            noise = noise / (np.sqrt(np.mean(noise**2)) + 1e-9) * (0.05 / 10 ** (snr / 20))
            mixed = np.clip(body + noise, -1, 1)

            truth = np.zeros(len(mixed) // CHUNK, dtype=bool)
            truth[pad // CHUNK: (pad + len(rev)) // CHUNK] = True

            for name, gated in ARMS:
                sig = mixed if gated is None else farfield_chain(mixed.copy(), gated=gated)
                rows[name].append(score(covered_frames(sig, gated is not None), truth))
        report(rows, f"■ SNR {snr:.0f} dB (n={len(utts)})")


# ---------------- AMI 실측 ----------------

def run_ami() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ami_farfield_eval import HEADSETS, find_utterances, load, normalize

    meetings = os.environ.get("AMI_MEETINGS", "ES2002a,ES2002b,ES2003a").split(",")
    for meeting in meetings:
        arr_path = AMI / f"{meeting}.Array1-01.wav"
        if not arr_path.exists():
            continue
        array = normalize(load(arr_path))
        array = array[: len(array) // CHUNK * CHUNK]
        n_frames = len(array) // CHUNK

        # 모든 화자의 발화 구간 (헤드셋 = 신뢰 가능한 정답)
        utts: list[tuple[int, int]] = []
        for h in HEADSETS:
            f = AMI / f"{meeting}.Headset-{h}.wav"
            if f.exists():
                utts += find_utterances(normalize(load(f)[: len(array)]))
        if not utts:
            continue
        global_speech = np.zeros(n_frames, dtype=bool)
        for a, b in utts:
            global_speech[a:min(b + 1, n_frames)] = True

        print(f"\n■ AMI {meeting} — 발화 {len(utts)}개 · 회의 {n_frames * 0.1 / 60:.0f}분 "
              f"(발화 {global_speech.mean() * 100:.0f}%)")
        print(f"{'체인':24} {'FRR%':>7} {'FAR%':>7} {'완전유실%':>9}")
        print("─" * 52)
        for name, gated in ARMS:
            sig = array if gated is None else farfield_chain(array.copy(), gated=gated)
            mask = covered_frames(sig, gated is not None)[:n_frames]

            miss = hit = lost = 0
            for a, b in utts:
                seg = mask[a:min(b + 1, n_frames)]
                miss += int((~seg).sum())
                hit += int(seg.sum())
                lost += 0 if seg.any() else 1
            # FAR는 회의 전체 비발화 프레임 기준으로 한 번만
            far = int((mask & ~global_speech).sum()) / max(1, int((~global_speech).sum())) * 100
            frr = miss / max(1, miss + hit) * 100
            print(f"{name:24} {frr:7.1f} {far:7.1f} {lost / len(utts) * 100:9.1f}")


if __name__ == "__main__":
    if "--ami" in sys.argv:
        run_ami()
    else:
        run_librispeech()
