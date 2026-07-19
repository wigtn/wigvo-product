"""차등 Whisper 검증 — 검출률 개선이 '쓸만한 전사'로 이어지는지 확인.

detection_eval.py는 FRR(유실)이 줄었다고 말하지만, VAD 지표만으로는 부족하다.
더 많이 커밋했는데 그 내용이 옆사람 말·소음이면 FRR은 좋아지고 사용자 경험은
나빠진다(합성 하네스에서 실제로 관측된 실패 모드).

그래서 **팔끼리 결과가 갈린 발화만** 골라 실제로 전사한다:
  - OFF는 놓쳤는데 현행(ON+게이트)은 잡은 발화 → 전사가 정답과 맞는가?
  - 현행이 놓쳤는데 OFF는 잡은 발화 → 역행 사례가 있는가?
대상이 소수라 API 비용이 작고, 질문에 직접 답한다.

실행:
  LIBRI_DIR=... RIRS_DIR=... OPENAI_API_KEY=... uv run python scripts/differential_check.py
"""
from __future__ import annotations

import os
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from detection_eval import PAD_S, covered_frames  # noqa: E402
from farfield_harness import CHUNK, SR, farfield_chain  # noqa: E402
from librispeech_farfield_eval import load_any, load_utterances, wer  # noqa: E402

RIRS = Path(os.environ.get("RIRS_DIR", "./RIRS_NOISES"))
N_UTTS = int(os.environ.get("N_UTTS", "200"))
SNR_DB = float(os.environ.get("SNR_DB", "10"))
WORK = Path(os.environ.get("WORKDIR", "."))

_client = None


def whisper(x: np.ndarray, tag: str) -> str:
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI()
    path = WORK / f"_diff_{tag}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    try:
        with open(path, "rb") as f:
            r = _client.audio.transcriptions.create(model="whisper-1", file=f, language="en")
        return (r.text or "").strip()
    except Exception as e:
        return f"<ERR {e}>"
    finally:
        path.unlink(missing_ok=True)


def build(speech: np.ndarray, rir: np.ndarray, noise: np.ndarray, snr_db: float):
    pad = int(PAD_S * SR)
    rev = np.convolve(speech, rir)[: len(speech)].astype(np.float32)
    rev = rev / (np.sqrt(np.mean(rev**2)) + 1e-9) * 0.05
    body = np.concatenate([np.zeros(pad, np.float32), rev, np.zeros(pad, np.float32)])
    noise = np.tile(noise, int(np.ceil(len(body) / len(noise))))[: len(body)]
    noise = noise / (np.sqrt(np.mean(noise**2)) + 1e-9) * (0.05 / 10 ** (snr_db / 20))
    mixed = np.clip(body + noise, -1, 1)
    truth = np.zeros(len(mixed) // CHUNK, dtype=bool)
    truth[pad // CHUNK: (pad + len(rev)) // CHUNK] = True
    return mixed, truth


def transcribe_detected(sig: np.ndarray, mask: np.ndarray, tag: str) -> str:
    """VAD가 커밋한 구간만 이어붙여 전사 — 실제 파이프라인이 STT에 보내는 것과 동일."""
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return ""
    parts = [sig[a * CHUNK:(a + 1) * CHUNK] for a in idx]
    return whisper(np.concatenate(parts), tag)


def main() -> None:
    utts = load_utterances(N_UTTS)
    rirs = [load_any(p) for p in sorted((RIRS / "real_rirs_isotropic_noises").glob("*.wav"))[:20]]
    noises = [load_any(p) for p in sorted((RIRS / "pointsource_noises").glob("*.wav"))[:20]]

    off_only, cur_only = [], []   # (index, 정답, OFF신호, OFF마스크, 현행신호, 현행마스크)
    for i, (speech, ref) in enumerate(utts):
        mixed, truth = build(speech, rirs[i % len(rirs)], noises[i % len(noises)], SNR_DB)
        cur_sig = farfield_chain(mixed.copy(), gated=True)
        m_off = covered_frames(mixed, False)[: len(truth)]
        m_cur = covered_frames(cur_sig, True)[: len(truth)]

        # 발화 프레임을 얼마나 덮었는지로 '검출' 판정 (30% 미만이면 사실상 유실)
        cov_off = (m_off & truth).sum() / max(1, truth.sum())
        cov_cur = (m_cur & truth).sum() / max(1, truth.sum())
        if cov_off < 0.3 <= cov_cur:
            off_only.append((i, ref, mixed, m_off, cur_sig, m_cur))
        elif cov_cur < 0.3 <= cov_off:
            cur_only.append((i, ref, mixed, m_off, cur_sig, m_cur))

    print(f"SNR {SNR_DB:.0f} dB · 발화 {len(utts)}개")
    print(f"  현행만 검출(OFF 유실): {len(off_only)}개   ← 복구된 발화")
    print(f"  OFF만 검출(현행 유실): {len(cur_only)}개   ← 역행 사례\n")

    if off_only:
        with ThreadPoolExecutor(max_workers=8) as ex:
            texts = list(ex.map(
                lambda t: transcribe_detected(t[4], t[5], f"cur{t[0]}"), off_only))
        scores = [w for (_, ref, *_), hyp in zip(off_only, texts) if (w := wer(ref, hyp)) is not None]
        print("── 현행이 복구한 발화의 실제 전사 품질 ──")
        print(f"  평균 WER {np.mean(scores) * 100:.1f}% · 중앙값 {np.median(scores) * 100:.1f}%")
        print(f"  (참고: 같은 조건 전체 평균 WER은 45% 안팎 — 이보다 크게 나쁘면 '복구했지만 쓸모없음')\n")
        for (i, ref, *_), hyp, w in list(zip(off_only, texts, scores))[:5]:
            print(f"  [{i}] WER {w * 100:5.1f}%")
            print(f"      정답: {ref[:70]}")
            print(f"      전사: {hyp[:70]}")

    if cur_only:
        with ThreadPoolExecutor(max_workers=8) as ex:
            texts = list(ex.map(
                lambda t: transcribe_detected(t[2], t[3], f"off{t[0]}"), cur_only))
        print("\n── 현행이 놓친 발화 (OFF는 잡음) ──")
        for (i, ref, *_), hyp in list(zip(cur_only, texts))[:5]:
            print(f"  [{i}] 정답: {ref[:70]}")
            print(f"      OFF 전사: {hyp[:70]}")


def run_ami() -> None:
    """AMI 실측에서 팔끼리 갈린 발화를 전사 비교.

    LibriSpeech 조건에서는 두 팔 모두 발화를 통째로 놓치는 일이 없어(완전유실 0%)
    차등 대상이 나오지 않는다. 실제 유실이 발생하는 곳은 AMI(회의실 원거리 마이크)다.
    기준 전사는 같은 시각의 헤드셋 채널.
    """
    from ami_farfield_eval import HEADSETS, find_utterances, load, normalize

    ami = Path(os.environ.get("AMI_DIR", "."))
    meetings = os.environ.get("AMI_MEETINGS", "ES2002a,ES2002b,ES2003a").split(",")
    recovered, regressed = [], []

    for meeting in meetings:
        arr_path = ami / f"{meeting}.Array1-01.wav"
        if not arr_path.exists():
            continue
        array = normalize(load(arr_path))
        array = array[: len(array) // CHUNK * CHUNK]
        n_frames = len(array) // CHUNK
        m_off = covered_frames(array, False)[:n_frames]
        cur_sig = farfield_chain(array.copy(), gated=True)
        m_cur = covered_frames(cur_sig, True)[:n_frames]

        for h in HEADSETS:
            f = ami / f"{meeting}.Headset-{h}.wav"
            if not f.exists():
                continue
            head = normalize(load(f)[: len(array)])
            for u in find_utterances(head):
                a, b = u[0], min(u[1] + 1, n_frames)
                span = b - a
                if span <= 0:
                    continue
                cov_off = m_off[a:b].sum() / span
                cov_cur = m_cur[a:b].sum() / span
                item = (meeting, h, u, head, cur_sig, array)
                if cov_off < 0.3 <= cov_cur:
                    recovered.append(item)
                elif cov_cur < 0.3 <= cov_off:
                    regressed.append(item)

    print(f"AMI 차등 검증 — 회의 {len(meetings)}개")
    print(f"  현행만 검출(OFF 유실): {len(recovered)}개   ← 복구된 발화")
    print(f"  OFF만 검출(현행 유실): {len(regressed)}개   ← 역행 사례\n")

    def show(items, label, sig_idx):
        if not items:
            return
        with ThreadPoolExecutor(max_workers=8) as ex:
            refs = list(ex.map(
                lambda t: whisper(t[3][t[2][0] * CHUNK:(t[2][1] + 1) * CHUNK],
                                  f"ref{t[0]}{t[1]}{t[2][0]}"), items))
            hyps = list(ex.map(
                lambda t: whisper(t[sig_idx][t[2][0] * CHUNK:(t[2][1] + 1) * CHUNK],
                                  f"hyp{t[0]}{t[1]}{t[2][0]}"), items))
        scores = [w for r, h in zip(refs, hyps) if (w := wer(r, h)) is not None]
        print(f"── {label} (n={len(items)}) ──")
        if scores:
            print(f"  전사 WER 평균 {np.mean(scores) * 100:.1f}% · 중앙값 {np.median(scores) * 100:.1f}%")
            print(f"  (같은 코퍼스 전체 평균 WER ≈ 22% — 이보다 크게 나쁘면 '잡았지만 쓸모없음')")
        for r, hy in list(zip(refs, hyps))[:6]:
            print(f"    기준(헤드셋): {r[:66]}")
            print(f"    원거리 전사 : {hy[:66]}")
        print()

    show(recovered, "현행이 복구한 발화 — 원거리 채널 전사", 4)
    show(regressed, "현행이 놓친 발화 — OFF 채널 전사", 5)


if __name__ == "__main__":
    if "--ami" in sys.argv:
        run_ami()
    else:
        main()
