"""5 dB 파국 샘플 부검 — 평균과 중앙값이 갈리는 이유를 직접 확인한다.

librispeech_farfield_eval의 5 dB · ON+게이트는 평균 WER 58.9 / 중앙값 42.8이다.
"이상치라서 무시"는 회귀 감지 관점에서 정확히 반대의 태도다 — 소수 샘플에서 난
파국적 실패가 실통화에서 만날 실패 모드일 수 있으므로, 그 샘플에서 체인이
무엇을 잘랐는지 열어본다.

각 발화에 대해 OFF/현행의 WER과 커밋 구조(세그먼트 수, 발화 프레임 커버리지,
게이트 통과 여부)를 함께 뽑아, WER이 크게 나빠진 샘플을 원인별로 분류한다.

실행:
  LIBRI_DIR=... RIRS_DIR=... OPENAI_API_KEY=... uv run python scripts/outlier_autopsy.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detection_eval import PAD_S, covered_frames  # noqa: E402
from differential_check import build, transcribe_detected  # noqa: E402
from farfield_harness import CHUNK, ClientVadSim, farfield_chain, gate_pass  # noqa: E402
from librispeech_farfield_eval import load_any, load_utterances, wer  # noqa: E402

RIRS = Path(os.environ.get("RIRS_DIR", "./RIRS_NOISES"))
N_UTTS = int(os.environ.get("N_UTTS", "120"))
SNR_DB = float(os.environ.get("SNR_DB", "5"))


def structure(sig: np.ndarray, adaptive: bool, truth: np.ndarray) -> dict:
    commits = ClientVadSim(adaptive=adaptive).commits(sig)
    kept = [c for c in commits if gate_pass(sig, c)]
    mask = covered_frames(sig, adaptive)[: len(truth)]
    return {
        "commits": len(commits),
        "gate_dropped": len(commits) - len(kept),
        "coverage": float((mask & truth).sum() / max(1, truth.sum())),
        "noise_frames": int((mask & ~truth).sum()),
    }


def main() -> None:
    utts = load_utterances(N_UTTS)
    rirs = [load_any(p) for p in sorted((RIRS / "real_rirs_isotropic_noises").glob("*.wav"))[:20]]
    noises = [load_any(p) for p in sorted((RIRS / "pointsource_noises").glob("*.wav"))[:20]]

    jobs = []
    for i, (speech, ref) in enumerate(utts):
        mixed, truth = build(speech, rirs[i % len(rirs)], noises[i % len(noises)], SNR_DB)
        cur = farfield_chain(mixed.copy(), gated=True)
        jobs.append((i, ref, mixed, cur, truth))

    def transcribe(j, gated):
        i, ref, mixed, cur, truth = j
        sig = cur if gated else mixed
        mask = covered_frames(sig, gated)[: len(truth)]
        return transcribe_detected(sig, mask, f"aut{'c' if gated else 'o'}{i}")

    with ThreadPoolExecutor(max_workers=12) as ex:
        off_txt = list(ex.map(lambda j: transcribe(j, False), jobs))
        cur_txt = list(ex.map(lambda j: transcribe(j, True), jobs))

    rows = []
    for (i, ref, mixed, cur, truth), o, c in zip(jobs, off_txt, cur_txt):
        w_off, w_cur = wer(ref, o), wer(ref, c)
        if w_off is None or w_cur is None:
            continue
        rows.append({
            "i": i, "ref": ref, "off": o, "cur": c,
            "w_off": w_off * 100, "w_cur": w_cur * 100,
            "s_off": structure(mixed, False, truth),
            "s_cur": structure(cur, True, truth),
        })

    w_cur = np.array([r["w_cur"] for r in rows])
    w_off = np.array([r["w_off"] for r in rows])
    print(f"SNR {SNR_DB:.0f} dB · n={len(rows)}")
    print(f"  OFF   평균 {w_off.mean():.1f} / 중앙값 {np.median(w_off):.1f} / 최대 {w_off.max():.0f}")
    print(f"  현행  평균 {w_cur.mean():.1f} / 중앙값 {np.median(w_cur):.1f} / 최대 {w_cur.max():.0f}")

    # 파국 = WER 100% 초과 (정답보다 긴 삽입 오류가 지배)
    cat = [r for r in rows if r["w_cur"] > 100]
    print(f"\n  현행 WER>100% 파국 샘플: {len(cat)}건 "
          f"({len(cat) / len(rows) * 100:.0f}%) — 평균을 끌어올린 주범")
    if cat:
        excess = sum(r["w_cur"] - np.median(w_cur) for r in cat) / len(rows)
        print(f"  이 {len(cat)}건이 평균에 더한 몫: +{excess:.1f}%p")

    print("\n── 파국 샘플 부검 (상위 5건) ──")
    for r in sorted(cat, key=lambda r: -r["w_cur"])[:5]:
        so, sc = r["s_off"], r["s_cur"]
        print(f"\n  [{r['i']}] WER  OFF {r['w_off']:.0f}% → 현행 {r['w_cur']:.0f}%")
        print(f"      커밋수   {so['commits']} → {sc['commits']}   "
              f"게이트드랍 {so['gate_dropped']} → {sc['gate_dropped']}")
        print(f"      발화커버 {so['coverage']:.0%} → {sc['coverage']:.0%}   "
              f"소음프레임 {so['noise_frames']} → {sc['noise_frames']}")
        print(f"      정답: {r['ref'][:64]}")
        print(f"      현행: {r['cur'][:64]}")

    # 원인 분류
    print("\n── 파국 원인 분류 ──")
    lost = [r for r in cat if r["s_cur"]["coverage"] < 0.5]
    noisy = [r for r in cat if r["s_cur"]["noise_frames"] > r["s_off"]["noise_frames"]]
    print(f"  발화 커버리지 붕괴(<50%)      : {len(lost)}건  ← 게이트가 발화를 잘랐다")
    print(f"  소음 프레임 증가(OFF 대비)     : {len(noisy)}건  ← 소음을 더 실어보냈다")
    print(f"  둘 다 아님(전사기 자체 실패)    : "
          f"{len(cat) - len({id(r) for r in lost} | {id(r) for r in noisy})}건")


if __name__ == "__main__":
    main()
