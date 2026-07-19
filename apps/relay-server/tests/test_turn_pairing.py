"""원문↔번역 페어링 — 발화가 겹쳐도 짝이 어긋나지 않아야 한다.

실측(2026-07-19 09:41): 단일 슬롯 구조라 번역 #1이 끝나기 전에 STT #2가
도착하면 슬롯이 덮어써져 번역 #1이 STT #2의 원문과 묶였다. Langfuse에
"Thank you." → "일단 보기만 하려고 하는데요." 같은 쌍이 기록됐고, 그 데이터로
돌린 오역 채점(50% 훼손)이 통째로 무효가 됐다.

품질 측정의 입력이므로 여기가 어긋나면 이후 모든 분석이 오염된다.
"""

import time

import pytest

from src.realtime.sessions.session_a import SessionAHandler, _STT_PAIR_MAX_AGE_S


class _Bare(SessionAHandler):
    """페어링 로직만 떼어내 검사한다 (세션/네트워크 의존 없이)."""

    def __init__(self):  # noqa: D107 — 상위 __init__의 외부 의존을 우회
        from collections import deque

        self._pending_user_stt = deque(maxlen=8)


def test_pairs_in_order_when_utterances_overlap():
    """STT 두 건이 연속 도착해도 번역은 각자의 원문과 짝지어진다."""
    h = _Bare()
    h.set_last_user_stt("What time is it now?")
    h.set_last_user_stt("Thank you.")

    assert h._take_user_stt() == "What time is it now?"
    assert h._take_user_stt() == "Thank you."


def test_no_pending_returns_empty_for_fallback():
    """대기열이 비면 빈 문자열 — 호출부가 번역문으로 대체(fallback)한다."""
    assert _Bare()._take_user_stt() == ""


def test_stale_entries_are_dropped_not_shifted():
    """짝을 잃은 오래된 원문은 폐기한다 — 남기면 이후 번역이 한 칸씩 밀린다."""
    h = _Bare()
    h._pending_user_stt.append((time.time() - (_STT_PAIR_MAX_AGE_S + 1), "짝 잃은 원문"))
    h.set_last_user_stt("현재 발화")

    assert h._take_user_stt() == "현재 발화"


def test_queue_is_bounded():
    """대기열이 무한히 자라지 않는다 (번역이 오지 않는 상황 방어)."""
    h = _Bare()
    for i in range(50):
        h.set_last_user_stt(f"utterance {i}")
    assert len(h._pending_user_stt) <= 8
    # 가장 오래된 것부터 밀려나므로 최근 발화가 남는다
    assert h._take_user_stt() == "utterance 42"
