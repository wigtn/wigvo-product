"""LibriSpeech + 실측 RIR + 실제 소음 far-field 평가 (표준 SNR 스윕).

AMI(실제 near/far 동시녹음)와 상보적인 두 번째 데이터셋. 이쪽의 강점:
  - **사람이 작성한 정답 전사**가 있어 기준이 Whisper 추정에 의존하지 않는다
  - 실측 RIR(OpenSLR RIRS_NOISES, 실제 방에서 측정한 임펄스 응답)을 쓰므로
    합성 하네스의 임의 파라미터(RT60 0.4s 등) 의존이 사라진다
  - 거리/잔향/SNR을 통제할 수 있어 **표준 SNR dB 스윕** 비교가 가능하다

데이터:
  LibriSpeech test-clean  https://www.openslr.org/resources/12/test-clean.tar.gz
  RIRS_NOISES             https://www.openslr.org/resources/28/rirs_noises.zip

실행:
  LIBRI_DIR=... RIRS_DIR=... OPENAI_API_KEY=... uv run python scripts/librispeech_farfield_eval.py
"""
from __future__ import annotations

import os
import random
import re
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from farfield_harness import CHUNK, SR, ClientVadSim, farfield_chain, gate_pass  # noqa: E402

LIBRI = Path(os.environ.get("LIBRI_DIR", "./LibriSpeech/test-clean"))
RIRS = Path(os.environ.get("RIRS_DIR", "./RIRS_NOISES"))
N_UTTS = int(os.environ.get("N_UTTS", "120"))
SNR_DBS = [float(x) for x in os.environ.get("SNR_DBS", "20,10,5").split(",")]

rng = random.Random(11)
_client = None


def load_any(path: Path) -> np.ndarray:
    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr != SR:  # 선형 보간 리샘플 (RIR/소음 자산이 8k·48k로 섞여 있다)
        idx = np.linspace(0, len(x) - 1, int(len(x) * SR / sr))
        x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    return x


def load_utterances(n: int) -> list[tuple[np.ndarray, str]]:
    """LibriSpeech 발화 + 공식 정답 전사."""
    items: list[tuple[Path, str]] = []
    for trans in sorted(LIBRI.rglob("*.trans.txt")):
        for line in trans.read_text().splitlines():
            uid, _, text = line.partition(" ")
            flac = trans.parent / f"{uid}.flac"
            if flac.exists():
                items.append((flac, text))
    rng.shuffle(items)
    out = []
    for flac, text in items:
        x = load_any(flac)
        if 2.0 <= len(x) / SR <= 15.0:
            out.append((x, text))
        if len(out) >= n:
            break
    return out


def load_assets() -> tuple[list[np.ndarray], list[np.ndarray]]:
    rirs = sorted((RIRS / "real_rirs_isotropic_noises").glob("*.wav"))
    noises = sorted((RIRS / "pointsource_noises").glob("*.wav"))
    rng.shuffle(rirs)
    rng.shuffle(noises)
    return ([load_any(p) for p in rirs[:12]], [load_any(p) for p in noises[:12]])


def make_farfield(speech: np.ndarray, rir: np.ndarray, noise: np.ndarray, snr_db: float):
    """실측 RIR 컨볼루션 + 지정 SNR로 실제 소음 혼합."""
    rev = np.convolve(speech, rir)[: len(speech)].astype(np.float32)
    p = np.sqrt(np.mean(rev**2)) + 1e-9
    rev = rev / p * 0.05  # 발화 레벨 정규화 (브라우저 AGC 대응)

    if len(noise) < len(rev):
        noise = np.tile(noise, int(np.ceil(len(rev) / len(noise))))
    noise = noise[: len(rev)]
    npow = np.sqrt(np.mean(noise**2)) + 1e-9
    target_noise_rms = 0.05 / (10 ** (snr_db / 20))
    mixed = rev + noise / npow * target_noise_rms

    pad = np.zeros(int(0.8 * SR), dtype=np.float32)  # VAD 온셋/오프셋 여유
    return np.clip(np.concatenate([pad, mixed, pad]), -1, 1)


def whisper(x: np.ndarray, tag: str) -> str:
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI()
    path = Path(os.environ.get("WORKDIR", ".")) / f"_ls_{tag}.wav"
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


def words(t: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", t.lower()).split()


def wer(ref: str, hyp: str) -> float | None:
    r, h = words(ref), words(hyp)
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


ARMS = [("OFF (파필드 없음)", None), ("ON (#1 원안)", False), ("ON+게이트 (현행)", True)]


def eval_one(item, rirs, noises, snr_db, arm_gated, idx):
    speech, ref = item
    ff = make_farfield(speech, rirs[idx % len(rirs)], noises[idx % len(noises)], snr_db)
    sig = ff if arm_gated is None else farfield_chain(ff.copy(), gated=arm_gated)

    commits = [c for c in ClientVadSim(adaptive=(arm_gated is not None)).commits(sig)]
    kept = [c for c in commits if gate_pass(sig, c)]
    if not kept:
        return {"wer": None, "lost": 1}
    a, b = min(c[0] for c in kept), max(c[1] for c in kept)
    hyp = whisper(sig[a * CHUNK:(b + 1) * CHUNK], f"{snr_db}_{arm_gated}_{idx}")
    return {"wer": wer(ref, hyp), "lost": 0}


def main() -> None:
    utts = load_utterances(N_UTTS)
    rirs, noises = load_assets()
    print(f"LibriSpeech 발화 {len(utts)}개 · 실측 RIR {len(rirs)}종 · 실제 소음 {len(noises)}종")
    print(f"정답 전사: 공식 라벨 (Whisper 추정 아님)\n")

    print(f"{'SNR':>6}  {'체인':24} {'WER%':>7} {'중앙값':>7} {'발화유실':>8}")
    print("─" * 60)
    for snr in SNR_DBS:
        for name, gated in ARMS:
            with ThreadPoolExecutor(max_workers=12) as ex:
                res = list(ex.map(
                    lambda t: eval_one(t[1], rirs, noises, snr, gated, t[0]),
                    enumerate(utts),
                ))
            sc = [r["wer"] for r in res if r["wer"] is not None]
            lost = sum(r["lost"] for r in res)
            m = float(np.mean(sc)) * 100 if sc else float("nan")
            md = float(np.median(sc)) * 100 if sc else float("nan")
            print(f"{snr:5.0f}dB  {name:24} {m:7.1f} {md:7.1f} {lost:8d}")
        print()


if __name__ == "__main__":
    main()
