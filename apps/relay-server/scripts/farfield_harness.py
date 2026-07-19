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

SCR = Path(os.environ.get("FARFIELD_WORKDIR", Path(__file__).parent))
SR = 16000
CHUNK = 1600  # 100ms
rng = np.random.default_rng(7)

SENTENCES = [
    "안녕하세요, 무엇을 도와드릴까요?",
    "배송은 보통 이틀 정도 걸립니다.",
    "추가 요금은 없습니다.",
    "성함과 연락처를 알려주시겠어요?",
    "잠시만 기다려 주시면 확인해 드리겠습니다.",
    "예약은 오전 열 시로 잡혀 있습니다.",
    "신분증을 지참하고 방문해 주셔야 합니다.",
    "해당 서류는 온라인으로도 발급받으실 수 있습니다.",
    "죄송합니다만 지금은 담당자가 자리에 없습니다.",
    "접수 번호는 문자로 발송해 드렸습니다.",
    "처리 기간은 영업일 기준 삼 일입니다.",
    "수수료는 오천 원이며 카드 결제도 가능합니다.",
    "주소지가 변경되셨다면 먼저 정정 신청을 하셔야 합니다.",
    "저희 사무실은 지하철 이호선 시청역 근처에 있습니다.",
    "운영 시간은 평일 아홉 시부터 여섯 시까지입니다.",
    "점심시간에는 창구 운영이 잠시 중단됩니다.",
    "필요하신 서류를 다시 한번 안내해 드릴게요.",
    "본인 확인이 되어야 다음 단계로 진행할 수 있습니다.",
    "혹시 대리인이 방문하실 예정이신가요?",
    "위임장과 인감증명서가 추가로 필요합니다.",
    "결과는 등록하신 이메일로 통보됩니다.",
    "신청이 정상적으로 접수되었습니다.",
    "보완이 필요한 부분이 있어 연락드렸습니다.",
    "기한 내에 회신 주시지 않으면 반려될 수 있습니다.",
    "관련 규정이 올해부터 변경되었습니다.",
    "자세한 내용은 홈페이지 공지사항을 참고해 주세요.",
    "통역이 필요하시면 말씀해 주시기 바랍니다.",
    "지금 말씀하신 내용을 다시 확인해 보겠습니다.",
    "다른 문의사항은 없으신가요?",
    "이용해 주셔서 감사합니다. 좋은 하루 되세요.",
    "신청서는 창구에서도 작성하실 수 있습니다.",
    "등록된 휴대폰 번호로 인증번호가 발송됩니다.",
    "발급받으신 서류는 삼 개월간 유효합니다.",
    "기존 자료는 저희 쪽에 보관되어 있습니다.",
    "확인해 보니 아직 접수 전 상태입니다.",
    "오후에는 대기 인원이 많은 편입니다.",
    "가급적 오전에 방문하시길 권해 드립니다.",
    "해당 민원은 온라인 신청이 더 빠릅니다.",
    "수령 방법은 방문과 등기 중 선택하실 수 있습니다.",
    "등기로 받으시면 이틀 정도 소요됩니다.",
    "정확한 주소를 다시 불러 주시겠어요?",
    "우편번호까지 함께 말씀해 주세요.",
    "말씀하신 내용으로 수정해 두었습니다.",
    "변경 사항은 즉시 반영됩니다.",
    "이전에 접수하신 건과 동일한 사안인가요?",
    "기존 접수 번호를 알고 계신가요?",
    "번호를 모르시면 성함으로 조회해 드리겠습니다.",
    "조회 결과가 두 건 있습니다.",
    "최근 접수 건을 기준으로 말씀드리겠습니다.",
    "현재 담당 부서에서 검토 중입니다.",
    "검토가 끝나면 별도로 안내드립니다.",
    "일정이 앞당겨질 수도 있습니다.",
    "취소를 원하시면 언제든 연락 주세요.",
    "취소 수수료는 발생하지 않습니다.",
    "환불은 결제하신 수단으로 처리됩니다.",
    "영업일 기준 오 일 이내에 입금됩니다.",
    "혹시 더 필요하신 안내가 있으신가요?",
    "제 설명이 이해되셨는지 확인차 여쭙습니다.",
    "천천히 말씀해 주셔도 괜찮습니다.",
    "다시 한번 말씀해 주시겠어요?",
    "잘 들리지 않아 죄송합니다.",
    "조금만 더 크게 말씀해 주시면 감사하겠습니다.",
    "지금 통역을 통해 안내드리고 있습니다.",
    "불편하신 점이 있으면 말씀해 주세요.",
    "외국인 등록증 번호가 필요합니다.",
    "여권 사본도 함께 제출해 주셔야 합니다.",
    "번역 공증이 된 서류여야 합니다.",
    "원본은 돌려드리니 걱정하지 않으셔도 됩니다.",
    "사본만 보관하고 원본은 반환해 드립니다.",
    "비용은 총 이만 삼천 원입니다.",
    "현금영수증 발행해 드릴까요?",
    "사업자 등록번호를 알려주시면 됩니다.",
    "결제는 창구에서 진행하시면 됩니다.",
    "카드 단말기가 잠시 점검 중입니다.",
    "계좌 이체도 가능합니다.",
    "입금자명을 신청자 성함으로 해 주세요.",
    "입금 확인 후 처리해 드리겠습니다.",
    "확인되는 대로 문자 드리겠습니다.",
    "연락처가 변경되면 꼭 알려주세요.",
    "안내 문자를 받지 못하셨다면 다시 발송해 드립니다.",
    "스팸함도 한번 확인해 보시겠어요?",
    "이메일 주소를 다시 확인해 주시겠습니까?",
    "철자를 하나씩 불러 주시면 받아 적겠습니다.",
    "네 정확히 입력되었습니다.",
    "그 부분은 규정상 어렵습니다.",
    "예외 적용이 가능한지 확인해 보겠습니다.",
    "담당자와 상의 후 다시 연락드리겠습니다.",
    "오늘 중으로 회신드릴 수 있을 것 같습니다.",
    "늦어도 내일 오전까지는 답변드리겠습니다.",
    "기다리게 해서 죄송합니다.",
    "불편을 드려 대단히 죄송합니다.",
    "최대한 빠르게 처리해 드리겠습니다.",
    "말씀하신 사항 잘 접수했습니다.",
    "추가로 궁금하신 점은 언제든 문의 주세요.",
    "상담 내용은 기록으로 남겨 두겠습니다.",
    "다음에 문의하실 때 참고하실 수 있습니다.",
    "저희 쪽 착오였습니다. 바로잡겠습니다.",
    "재발하지 않도록 조치하겠습니다.",
    "귀중한 의견 감사드립니다.",
    "안전하게 귀가하시기 바랍니다.",
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
    path = SCR / f"_seg_{seg[0]}_{seg[1]}_{os.getpid()}_{id(x)}.wav"
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
        finally:
            path.unlink(missing_ok=True)

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

    from concurrent.futures import ThreadPoolExecutor

    todo = []
    for seg in segs:
        overlaps = [i for i, (a, b, _) in enumerate(spans) if seg[0] <= b and a <= seg[1]]
        if not gate_pass(x, seg):
            if overlaps:
                n_gate_cut_real += 1
            continue
        todo.append((seg, overlaps))
    with ThreadPoolExecutor(max_workers=8) as ex:
        texts = list(ex.map(lambda t: whisper(x, t[0]), todo))
    for (seg, overlaps), text in zip(todo, texts):
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


# ---------- 무발화 할루시 테스트 ----------

def run_silence_arm(noise_audio, arm: str):
    """발화가 0인 오디오 → 커밋된 세그먼트의 전사는 전부 할루시(정답=무음).

    프로덕션에서 실제로 터진 유형("먹방끝", "구독과 좋아요")이 이 경로다.
    같이 반환하는 caught_by_guardrail은 서버측 사전(is_caller_hallucination)이
    그 텍스트를 걸러낼 수 있었는지 — 프론트에서 못 막았을 때의 최후 방어율.
    """
    from concurrent.futures import ThreadPoolExecutor
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.realtime.sessions.hallucination import is_caller_hallucination

    x = noise_audio.copy() if arm == "OFF" else farfield_chain(
        noise_audio.copy(), gated=(arm == "ON+게이트"))
    segs = [sg for sg in ClientVadSim(adaptive=(arm != "OFF")).commits(x) if gate_pass(x, sg)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        texts = [t for t in ex.map(lambda sg: whisper(x, sg), segs) if t and not t.startswith("<ERR")]
    return {
        "commits": len(segs),
        "halluc": len(texts),
        "caught": sum(1 for t in texts if is_caller_hallucination(t)),
        "texts": texts,
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
    # ---- 무발화 구간 할루시 (발화 0 → 어떤 텍스트든 할루시) ----
    n_sil = int(30 * SR)
    sil_conds = {
        "완전 무음": np.zeros(n_sil, dtype=np.float32),
        "조용한 방(팬 소음)": pink(n_sil, 0.003),
        "사무실 소음": pink(n_sil, 0.010),
        "옆자리 대화(babble)": babble(n_sil, 0.010),
    }
    print("\n\n══ 무발화 30초 구간 — 할루시 측정 (정답: 아무 텍스트도 안 나와야 함) ══\n")
    print(f"{'조건':22} {'체인':9} {'커밋':>4} {'할루시':>6} {'서버사전차단':>10}")
    print("─" * 58)
    sil_texts = []
    for cname, audio in sil_conds.items():
        for arm in ("OFF", "ON", "ON+게이트"):
            r = run_silence_arm(audio, arm)
            print(f"{cname:22} {arm:9} {r['commits']:4d} {r['halluc']:6d} {r['caught']:10d}")
            for t in r["texts"]:
                sil_texts.append((cname, arm, t))
        print()
    if sil_texts:
        print("── 무발화 구간에서 나온 텍스트(=할루시) ──")
        for c, a, t in sil_texts:
            print(f"  [{c} / {a}] {t[:70]}")

    if all_h:
        print("── 할루시 실물 ──")
        for c, arm, t in all_h:
            print(f"  [{c} / {arm}] {t[:70]}")


if __name__ == "__main__":
    main()
