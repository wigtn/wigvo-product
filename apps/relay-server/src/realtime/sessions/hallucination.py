"""환각 판별 — 발신자(Session A)·수신자(Session B) 공용 텍스트 휴리스틱 (모델 무관).

session_b가 수신자 측에서 쓰던 필터 철학을 발신자 측에도 적용하기 위한 공용 함수.
오탐 위험이 낮은(절대 정상 발화일 수 없는) 패턴만 담는다: 구조적 노이즈(자음 스팸·반복·
단일문자), 토큰 3회+ 반복, 자막/아웃트로 크레딧.

⚠️ 짧은 인사/공손("감사합니다", "Thank you", "안녕하세요")은 발신자가 실제로 말할 수 있어
   여기엔 넣지 않는다 (정상 발화 오탐 방지). 필요 시 별도 정책으로 분리한다.
"""

from __future__ import annotations

import re

# 동일 토큰 3회 이상 연속 반복
_REPETITION_RE = re.compile(r"(\b\S+\b)(\s+\1){2,}", re.IGNORECASE)

# 블록리스트 비교 전 제거할 구두점
_PUNCT_STRIP = str.maketrans("", "", "!?。！？…·.")

# 자막/아웃트로 크레딧 — 통화에서 절대 정상 발화가 아님 (짧은 인사/공손은 의도적으로 제외)
_CREDIT_BLOCKLIST = frozenset(
    {
        "mbc 뉴스 이덕영입니다",
        "mbc뉴스 이덕영입니다",
        "시청해주셔서 감사합니다",
        "시청해 주셔서 감사합니다",
        "영상을 시청해주셔서 감사합니다",
        "끝까지 시청해주셔서 감사합니다",
        "끝까지 시청해 주셔서 감사합니다",
        "구독과 좋아요 부탁드립니다",
        "thanks for watching",
        "thanks for listening",
        "please subscribe",
        "like and subscribe",
        "see you next time",
        "see you in the next video",
    }
)

# 위 블록리스트는 완전일치라, Whisper가 크레딧을 문장에 섞어 뱉으면 통과한다.
# 실제 관측(far-field 평가, 5 dB SNR): "Thank you for watching and I'll see you
# in the next video." → 위 항목 두 개를 포함하는데도 완전일치가 아니라 미차단.
# 그래서 '통화에서 절대 나올 수 없는' 문구만 부분일치로 따로 본다.
# ⚠️ "see you next time"·"thank you"처럼 정상 발화일 수 있는 표현은 넣지 않는다.
_CREDIT_SUBSTRINGS = (
    "thanks for watching",
    "thank you for watching",
    "for watching this video",
    "in the next video",
    "please subscribe",
    "like and subscribe",
    "시청해주셔서",
    "시청해 주셔서",
    "구독과 좋아요",
)


def _normalize(text: str) -> str:
    return text.strip().translate(_PUNCT_STRIP).lower()


def is_structural_noise(text: str) -> bool:
    """자음 스팸·짧은 패턴 반복·단일 문자 = 구조적 노이즈 (절대 정상 발화 아님)."""
    stripped = text.strip()
    if not stripped:
        return False  # 빈 텍스트는 노이즈로 보지 않음(그냥 무시)
    non_space = stripped.replace(" ", "")

    # 1. 한글 자음만 (U+3131~U+314E)
    if non_space and all("ㄱ" <= c <= "ㅎ" for c in non_space):
        return True
    # 2. 짧은 패턴 반복 (패턴 1~6자, 3회 이상)
    for plen in range(1, min(7, len(non_space) // 2 + 1)):
        pat = non_space[:plen]
        reps = len(non_space) // plen
        if reps >= 3 and pat * reps == non_space[: plen * reps]:
            return True
    # 3. 단일 문자
    if len(non_space) <= 1:
        return True
    return False


def is_caller_hallucination(text: str) -> bool:
    """발신자(Session A) 출력에 적용할 안전한 환각 판별.

    절대 정상일 수 없는 패턴만: 구조적 노이즈 + 토큰 3회+ 반복 + 자막 크레딧.
    """
    if not text or not text.strip():
        return False
    if is_structural_noise(text):
        return True
    if _REPETITION_RE.search(text):
        return True
    normalized = _normalize(text)
    if normalized in _CREDIT_BLOCKLIST:
        return True
    if any(s in normalized for s in _CREDIT_SUBSTRINGS):
        return True
    return False
