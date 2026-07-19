"""AMI 실측 far-field 평가 — 같은 발화의 near(헤드셋) vs far(원거리 마이크) 대조.

합성 하네스(farfield_harness.py)의 한계였던 "합성 파라미터 의존"을 제거한다.
AMI Meeting Corpus는 같은 발화를 헤드셋과 원거리 마이크로 **동시 녹음**하므로,
동일 발화에 대해 far-field 처리 유무를 직접 비교할 수 있다.

  헤드셋(IHM)      → Whisper 전사 = 기준(reference)
  원거리(Array1-01) → [체인 OFF / ON / ON+게이트] → Whisper 전사 = 가설(hypothesis)
  지표: WER (표준 단어 오류율)

준비:
  BASE=https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/ES2002a/audio
  curl -O $BASE/ES2002a.Headset-0.wav ; curl -O $BASE/ES2002a.Array1-01.wav

실행:
  AMI_DIR=... OPENAI_API_KEY=... uv run python scripts/ami_farfield_eval.py
"""
from __future__ import annotations

import os
import re
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from farfield_harness import (  # noqa: E402  (같은 체인·VAD 구현을 공유)
    CHUNK,
    SR,
    ClientVadSim,
    farfield_chain,
    gate_pass,
)

AMI = Path(os.environ.get("AMI_DIR", "."))
MEETINGS = os.environ.get("AMI_MEETINGS", "ES2002a,ES2002b,ES2003a").split(",")
HEADSETS = [0, 1, 2, 3]  # 화자 4명 전원
MAX_UTTS = int(os.environ.get("AMI_MAX_UTTS", "150"))

_client = None


def load(path: Path) -> np.ndarray:
    w = wave.open(str(path), "rb")
    assert w.getframerate() == SR and w.getnchannels() == 1, "16kHz mono 필요"
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    w.close()
    return x


def normalize(x: np.ndarray, target_speech_rms: float = 0.05) -> np.ndarray:
    """채널별 레벨 정규화 — 브라우저 autoGainControl(프로덕션에서 항상 ON) 대응.

    AMI 원본은 매우 낮은 레벨(헤드셋 p99 RMS ≈ 0.003)로 녹음돼 있어 그대로 쓰면
    far-field 성능이 아니라 녹음 게인 차이를 재게 된다. 각 채널의 발화 수준
    (p99 프레임 RMS)을 표준 발화 레벨로 맞춘 뒤 비교한다.
    """
    n = len(x) // CHUNK
    rms = np.array([np.sqrt(np.mean(x[i * CHUNK:(i + 1) * CHUNK] ** 2)) for i in range(n)])
    speech_level = float(np.percentile(rms, 99)) + 1e-9
    return np.clip(x * (target_speech_rms / speech_level), -1, 1)


def find_utterances(headset: np.ndarray) -> list[tuple[int, int]]:
    """헤드셋(깨끗) 채널에서 화자 본인 발화 구간을 찾는다.

    헤드셋에도 다른 화자 소리가 새어 들어오므로(bleed), 본인 발화만 남도록
    임계를 높게 잡는다. 1.5~15초 구간만 채택 — 너무 짧으면 WER이 불안정하고
    너무 길면 far 채널에서 다른 화자와 섞인다.
    """
    n = len(headset) // CHUNK
    rms = np.array([
        np.sqrt(np.mean(headset[f * CHUNK:(f + 1) * CHUNK] ** 2)) for f in range(n)
    ])
    thresh = max(0.02, float(np.percentile(rms[rms > 0.005], 60)) if (rms > 0.005).any() else 0.02)
    speaking = rms > thresh

    utts: list[tuple[int, int]] = []
    start = None
    silence = 0
    for f in range(n):
        if speaking[f]:
            if start is None:
                start = f
            silence = 0
        elif start is not None:
            silence += 1
            if silence >= 5:  # 500ms 무음 → 발화 종료
                dur = (f - silence - start) * 0.1
                if 1.5 <= dur <= 15.0:
                    utts.append((start, f - silence))
                start = None
    return utts


def whisper(x: np.ndarray, seg: tuple[int, int], tag: str) -> str:
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI()
    s = x[seg[0] * CHUNK:(seg[1] + 1) * CHUNK]
    path = AMI / f"_ami_{tag}_{seg[0]}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(s, -1, 1) * 32767).astype("<i2").tobytes())
    try:
        with open(path, "rb") as f:
            r = _client.audio.transcriptions.create(model="whisper-1", file=f, language="en")
        return (r.text or "").strip()
    except Exception as e:
        return f"<ERR {e}>"
    finally:
        path.unlink(missing_ok=True)


def norm_words(t: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", t.lower()).split()


def wer(ref: str, hyp: str) -> float | None:
    r, h = norm_words(ref), norm_words(hyp)
    if not r:
        return None
    d = np.arange(len(h) + 1)
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev = cur
    return d[len(h)] / len(r)


def collect(meeting: str) -> tuple[np.ndarray, list[tuple[np.ndarray, tuple[int, int]]]]:
    """한 회의에서 (원거리 신호, [(해당화자 헤드셋, 발화구간)]) 수집."""
    array = load(AMI / f"{meeting}.Array1-01.wav")
    pairs = []
    for h in HEADSETS:
        f = AMI / f"{meeting}.Headset-{h}.wav"
        if not f.exists():
            continue
        head = load(f)
        n = min(len(head), len(array))
        head = normalize(head[:n])
        for u in find_utterances(head):
            pairs.append((head, u))
    return normalize(array[: len(array) // CHUNK * CHUNK]), pairs


def main() -> None:
    tasks = []  # (회의, 원거리신호, 헤드셋신호, 구간)
    arrays: dict[str, np.ndarray] = {}
    for m in MEETINGS:
        if not (AMI / f"{m}.Array1-01.wav").exists():
            continue
        arr, pairs = collect(m)
        arrays[m] = arr
        for head, u in pairs:
            tasks.append((m, head, u))
    if not tasks:
        print("발화 구간을 찾지 못했습니다")
        return
    if len(tasks) > MAX_UTTS:
        idx = np.linspace(0, len(tasks) - 1, MAX_UTTS).astype(int)
        tasks = [tasks[i] for i in idx]

    total_s = sum((u[1] - u[0]) for _, _, u in tasks) * 0.1
    print(f"회의 {len(arrays)}개 · 화자 {len(HEADSETS)}명 · 발화 {len(tasks)}개 · 총 {total_s:.0f}s\n")

    with ThreadPoolExecutor(max_workers=12) as ex:
        refs = list(ex.map(lambda t: whisper(t[1], t[2], "ref"), tasks))

    print(f"{'체인':26} {'WER%':>7} {'중앙값':>7} {'미검출':>7} {'게이트잘림':>8}")
    print("─" * 62)
    for name, gated in (("OFF (파필드 없음)", None), ("ON (#1 원안)", False), ("ON+게이트 (현행)", True)):
        sigs = {m: (a if gated is None else farfield_chain(a.copy(), gated=gated))
                for m, a in arrays.items()}
        with ThreadPoolExecutor(max_workers=12) as ex:
            hyps = list(ex.map(lambda t: whisper(sigs[t[0]], t[2], "hyp"), tasks))

        commits = {m: ClientVadSim(adaptive=(gated is not None)).commits(sg)
                   for m, sg in sigs.items()}
        undetected = gate_cut = 0
        for m, _, u in tasks:
            hit = [c for c in commits[m] if c[0] <= u[1] and u[0] <= c[1]]
            if not hit:
                undetected += 1
            elif not any(gate_pass(sigs[m], c) for c in hit):
                gate_cut += 1

        sc = [w for r, h in zip(refs, hyps) if (w := wer(r, h)) is not None]
        mean_w = float(np.mean(sc)) * 100 if sc else float("nan")
        med_w = float(np.median(sc)) * 100 if sc else float("nan")
        print(f"{name:26} {mean_w:7.1f} {med_w:7.1f} {undetected:7d} {gate_cut:8d}")

    print(f"\n기준(헤드셋) 전사 예시: {refs[0][:80]}")


if __name__ == "__main__":
    main()
