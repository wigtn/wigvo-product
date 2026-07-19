"""화자 식별 — '이 발화가 응대자 본인인가'를 판정한다.

왜 필요한가:
  옆자리 대화·재생 음성이 통역에 섞여 들어간다. 게다가 그런 입력은 깨진
  번역이 아니라 **유창한 창작**으로 나온다(실측: 유튜브 뉴스 "내년도 최저임금이
  …" → "our final delivery timing will be one hour later"). 상대는 그걸 믿는다.

왜 레벨로는 안 되는가:
  절대 임계(250·2000)는 모두 발동 0건이었고, 상대 임계도 '멀리서 크게'와
  '가까이서 조용히'를 구분하지 못한다. 크기는 마이크 게인·거리·목소리가
  뒤섞인 값이라 보편 기준이 없다. 우리가 답해야 할 질문은 "가까운가"가 아니라
  **"본인인가"** 다.

모델: WeSpeaker ECAPA-TDNN512 (ONNX 24MB). onnxruntime은 Silero VAD가 이미
      쓰고 있어 새 런타임 의존성이 없다. CAM++와 비교했으나 전처리를 각
      모델 규격에 맞춘 뒤에도 ECAPA가 낫고 2배 빨랐다(잔향 조건 +0.633 vs +0.348).

⚠️ 섀도 모드: 지금은 유사도를 계산해 기록만 하고 어떤 판단도 하지 않는다.
   실제 사람 목소리 기준의 분포를 모으기 전에 차단을 켜면, 임계를 잘못 잡아
   본인 발화를 통째로 막을 수 있다.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

try:
    import onnxruntime as ort
except Exception:  # onnxruntime 미설치 시 전체 no-op (통화 경로에 영향 없음)
    ort = None

logger = logging.getLogger(__name__)

_MODEL_PATH = Path(__file__).resolve().parent / "models" / "speaker_ecapa_tdnn512.onnx"
_EPS = np.finfo(np.float32).eps
SR = 16000

# 추론은 GIL을 놓는 ONNX 연산이므로 별도 스레드에서 돌린다 (Silero와 같은 방식).
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="spk-embed")


# --- kaldi 호환 fbank (WeSpeaker 학습 규격) -----------------------------------
# 전처리가 어긋나면 임베딩 품질이 그대로 깎인다. 실제로 규격을 맞추기 전과 후에
# 모델 순위가 뒤바뀌었다.

def _hamming(n: int) -> np.ndarray:
    """WeSpeaker(ECAPA) 학습 규격. CAM++로 바꾸려면 povey 윈도우가 필요하다 —
    전처리가 어긋나면 모델 순위가 뒤바뀔 만큼 영향이 크다."""
    return (0.54 - 0.46 * np.cos(2 * np.pi * np.arange(n) / (n - 1))).astype(np.float32)


def _mel_banks(n_mels: int, n_fft: int, sr: int, low: float = 20.0) -> np.ndarray:
    n_bins = n_fft // 2 + 1
    fft_freqs = np.arange(n_bins) * (sr / n_fft)

    def hz2mel(f):
        return 1127.0 * np.log(1.0 + f / 700.0)

    mel_pts = np.linspace(hz2mel(low), hz2mel(sr / 2), n_mels + 2)
    mel_freqs = hz2mel(fft_freqs)
    fb = np.zeros((n_mels, n_bins), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = mel_pts[i], mel_pts[i + 1], mel_pts[i + 2]
        up = (mel_freqs - left) / (center - left)
        down = (right - mel_freqs) / (right - center)
        fb[i] = np.maximum(0.0, np.minimum(up, down))
    return fb


_MEL_FB = _mel_banks(80, 512, SR)
_WINDOW = _hamming(400)


def _fbank(wav: np.ndarray) -> np.ndarray:
    """(T, 80) log-mel. kaldi: 프레임별 DC 제거 → preemphasis 0.97 → hamming → CMN."""
    win_len, hop, n_fft = 400, 160, 512
    x = wav.astype(np.float32)
    if len(x) < win_len:
        x = np.pad(x, (0, win_len - len(x)))
    n_frames = 1 + (len(x) - win_len) // hop
    idx = np.arange(win_len)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = x[idx].astype(np.float32)
    frames = frames - frames.mean(axis=1, keepdims=True)
    prev = np.concatenate([frames[:, :1], frames[:, :-1]], axis=1)
    frames = (frames - 0.97 * prev) * _WINDOW
    spec = np.abs(np.fft.rfft(frames, n=n_fft, axis=1)) ** 2
    feat = np.log(np.maximum(spec @ _MEL_FB.T, _EPS)).astype(np.float32)
    return feat - feat.mean(axis=0, keepdims=True)


# --- 세션별 화자 판정 ---------------------------------------------------------

_session: object = None
_session_lock = threading.Lock()


def _get_session():
    global _session
    if ort is None:
        return None
    with _session_lock:
        if _session is None:
            if not _MODEL_PATH.exists():
                logger.warning("[SpeakerID] 모델 없음 (%s) — 비활성", _MODEL_PATH)
                _session = False
            else:
                try:
                    opts = ort.SessionOptions()
                    # 세션은 프로세스 전역 하나이고 동시 추론은 _EXECUTOR(2)로
                    # 제한된다. 스레드를 1로 두어 통화가 몰릴 때 ONNX 내부
                    # 병렬화가 이벤트루프 코어를 뺏지 않게 한다.
                    opts.intra_op_num_threads = 1
                    _session = ort.InferenceSession(
                        str(_MODEL_PATH), sess_options=opts,
                        providers=["CPUExecutionProvider"],
                    )
                    logger.info("[SpeakerID] ECAPA-TDNN512 로드 완료")
                except Exception:
                    logger.exception("[SpeakerID] 모델 로드 실패 — 비활성")
                    _session = False
    return _session or None


def _embed_sync(pcm: np.ndarray) -> np.ndarray | None:
    sess = _get_session()
    if sess is None:
        return None
    try:
        e = sess.run(None, {"feats": _fbank(pcm)[None]})[0][0]
        return e / (np.linalg.norm(e) + 1e-9)
    except Exception:
        logger.exception("[SpeakerID] 임베딩 실패")
        return None


class SpeakerMatcher:
    """통화 1건의 화자 기준을 관리한다.

    첫 발화(충분한 길이)를 응대자 기준으로 등록하고, 이후 발화의 유사도를
    돌려준다. 섀도 모드에서는 이 값을 기록만 하고 판단에 쓰지 않는다.
    """

    #: 등록·판정에 필요한 최소 발화 길이. 너무 짧으면 임베딩이 불안정하다.
    MIN_SECONDS = 1.0
    #: 기준을 정하기 전에 모아둘 발화 수. 첫 발화를 곧바로 기준으로 삼으면
    #: 배경음이 먼저 잡힐 때 그것이 '응대자'가 된다 — 실측(2026-07-19 통화 B,
    #: 유튜브를 먼저 튼 조건)에서 유튜브가 등록돼 이후 본인 발화가 전부
    #: -0.051~0.225로 떨어졌다. 차단을 켰다면 응대자가 통째로 막혔을 상황이다.
    CANDIDATE_SEGMENTS = 3
    #: 같은 화자로 묶는 기준. 실측 분포(같은 화자 0.585~0.754,
    #: 다른 화자 -0.051~0.306)의 사이에서 보수적으로 잡는다.
    SAME_SPEAKER_SIMILARITY = 0.40
    #: 기준 확정 후 합산 기준. SAME_SPEAKER_SIMILARITY와 값은 같지만 의미가 다르다
    #: — 이쪽은 '이미 정해진 기준과 같은 사람인가'이고, 저쪽은 '후보끼리 같은
    #: 사람인가'다. 실측 분포가 더 쌓이면 갈라질 수 있어 별도 상수로 둔다.
    ENROLL_MIN_SIMILARITY = 0.40
    ENROLL_SEGMENTS = 5

    def __init__(self) -> None:
        self._reference: np.ndarray | None = None
        self._enrolled_at: float = 0.0
        self._enroll_count: int = 0
        #: 기준 확정 전에 모으는 후보 임베딩
        self._candidates: list[np.ndarray] = []
        #: 선출 시점에 계산한 후보 구간의 사후 점수 (기록용)
        self._backfill: list[float] = []

    @property
    def enrolled(self) -> bool:
        return self._reference is not None

    def _elect_reference(self) -> int:
        """후보 중 '가장 많은 동료를 가진' 화자를 응대자로 정한다.

        전제: 통화에서 응대자가 가장 많이 말한다. 배경음(방송·옆자리)은
        간헐적이므로 같은 화자끼리 묶이는 무리가 더 작다. 실측 2통화 모두
        본인이 다수였다(6:3, 4:3).

        Returns: 기준에 합산된 후보 수
        """
        n = len(self._candidates)
        mat = np.stack(self._candidates)          # 이중 루프 대신 행렬곱 한 번
        sims = mat @ mat.T
        neighbors = (sims >= self.SAME_SPEAKER_SIMILARITY).sum(axis=1)
        if int(neighbors.max()) < 2:
            # 후보가 전부 서로 다른 화자다. 이 상태로 선출하면 무리가 1개가 되어
            # '첫 발화 = 기준'으로 되돌아간다 — 고치려던 문제 그대로다.
            # 다수가 드러날 때까지 보류하고 후보를 더 모은다.
            logger.info("[SpeakerID] 후보 %d개가 모두 상이 — 선출 보류", n)
            return 0
        anchor = int(np.argmax(neighbors))
        members = [c for c, s in zip(self._candidates, sims[anchor])
                   if s >= self.SAME_SPEAKER_SIMILARITY]
        merged = np.sum(members, axis=0)
        self._reference = merged / (np.linalg.norm(merged) + 1e-9)
        self._enroll_count = len(members)
        self._enrolled_at = time.time()
        # 후보 구간의 점수를 사후에 남긴다. 그냥 버리면 통화당 앞 N건이 통째로
        # 빠지는데, 실측 통화가 7~10발화라 절반 가까이 손실이다.
        self._backfill = [round(float(np.dot(self._reference, c)), 3)
                          for c in self._candidates]
        self._candidates.clear()
        logger.info(
            "[SpeakerID] 응대자 기준 확정 — 후보 %d개 중 %d개로 (다수 화자 선출)",
            n, len(members),
        )
        return len(members)

    async def score(self, pcm16: bytes) -> dict | None:
        """세그먼트를 채점한다. 반환은 기록용 dict (None이면 처리 불가).

        커밋 직전 세그먼트마다 1회만 호출한다 — 프레임 단위로 돌리면 Silero보다
        무거운 모델을 50배 빈도로 돌리게 되어 감당할 수 없다.
        """
        if _get_session() is None or not pcm16:
            return None
        pcm = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        if len(pcm) < SR * self.MIN_SECONDS:
            return None

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        emb = await loop.run_in_executor(_EXECUTOR, _embed_sync, pcm)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if emb is None:
            return None
        base = {"speaker_embed_ms": round(elapsed_ms, 1)}

        # --- 기준 확정 전: 후보만 모은다 (이 구간은 판정하지 않는다) ---
        if self._reference is None:
            self._candidates.append(emb)
            if len(self._candidates) < self.CANDIDATE_SEGMENTS:
                logger.info("[SpeakerID] 후보 수집 %d/%d (%.0fms)",
                            len(self._candidates), self.CANDIDATE_SEGMENTS, elapsed_ms)
                return {**base, "speaker_similarity": None, "speaker_enrolled": False,
                        "speaker_phase": "collecting",
                        "speaker_candidates": len(self._candidates)}
            members = self._elect_reference()
            if members == 0:  # 선출 보류 — 후보를 더 모은다
                return {**base, "speaker_similarity": None, "speaker_enrolled": False,
                        "speaker_phase": "collecting",
                        "speaker_candidates": len(self._candidates)}
            return {**base, "speaker_similarity": None, "speaker_enrolled": True,
                    "speaker_phase": "elected", "speaker_enroll_count": members,
                    "speaker_backfill": self._backfill}

        # --- 기준 확정 후: 유사도 판정 ---
        similarity = float(np.dot(self._reference, emb))
        if (self._enroll_count < self.ENROLL_SEGMENTS
                and similarity >= self.ENROLL_MIN_SIMILARITY):
            n = self._enroll_count
            merged = self._reference * n + emb
            self._reference = merged / (np.linalg.norm(merged) + 1e-9)
            self._enroll_count = n + 1
            logger.info("[SpeakerID] 유사도 %.3f — 기준 보강 %d개 (%.0fms)",
                        similarity, self._enroll_count, elapsed_ms)
        else:
            logger.info("[SpeakerID] 유사도 %.3f (%.0fms)", similarity, elapsed_ms)

        return {**base, "speaker_similarity": round(similarity, 3),
                "speaker_enrolled": False, "speaker_phase": "scoring",
                "speaker_enroll_count": self._enroll_count}
