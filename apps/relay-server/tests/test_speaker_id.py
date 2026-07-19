"""화자 식별 — 섀도 모드 동작과 레벨 무관성.

레벨 기반 게이트(절대 250·2000, 상대 비율)는 모두 실패했다. 크기는 마이크
게인·거리·목소리가 뒤섞인 값이라 '멀리서 크게'와 '가까이서 조용히'를 가르지
못한다. 화자 임베딩은 그 질문 자체를 '본인인가'로 바꾼다.
"""

import numpy as np
import pytest

from src.realtime.speaker_id import SR, SpeakerMatcher, _fbank


def _tone(freq: float, seconds: float = 2.0, amp: float = 0.2) -> bytes:
    """합성 신호 (PCM16 bytes). 임베딩 값 자체가 아니라 배선을 검증한다."""
    t = np.arange(int(SR * seconds)) / SR
    x = amp * (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 2.5 * t))
    return (x * 32767).astype("<i2").tobytes()


class TestFbank:
    def test_shape_is_80_mel(self):
        feat = _fbank(np.frombuffer(_tone(200), dtype="<i2").astype(np.float32) / 32768)
        assert feat.shape[1] == 80

    def test_frame_rate_is_100hz(self):
        """10ms hop — kaldi 규격. 어긋나면 모델 입력 길이가 달라진다."""
        feat = _fbank(np.frombuffer(_tone(200, 1.0), dtype="<i2").astype(np.float32) / 32768)
        assert 95 <= feat.shape[0] <= 100

    def test_level_invariance(self):
        """CMN 덕분에 음량이 변해도 특징이 거의 같아야 한다 —
        레벨 무관 판정의 근거."""
        x = np.frombuffer(_tone(200), dtype="<i2").astype(np.float32) / 32768
        loud, quiet = _fbank(x), _fbank(x * 0.1)
        assert np.abs(loud - quiet).max() < 0.05


class TestSpeakerMatcher:
    @pytest.mark.asyncio
    async def test_short_segment_is_skipped(self):
        """너무 짧으면 임베딩이 불안정해 채점하지 않는다."""
        m = SpeakerMatcher()
        assert await m.score(_tone(200, 0.3)) is None
        assert m.enrolled is False

    @pytest.mark.asyncio
    async def test_empty_input_is_safe(self):
        assert await SpeakerMatcher().score(b"") is None

    @pytest.mark.asyncio
    async def test_first_segment_enrolls_then_scores(self):
        m = SpeakerMatcher()
        first = await m.score(_tone(200))
        if first is None:
            pytest.skip("모델 미탑재 환경")
        assert first["speaker_enrolled"] is True
        assert m.enrolled is True

        second = await m.score(_tone(200))
        assert second["speaker_enrolled"] is False
        assert -1.0 <= second["speaker_similarity"] <= 1.0

    @pytest.mark.asyncio
    async def test_same_signal_scores_higher_than_different(self):
        """같은 소리 vs 다른 소리 — 판정 방향이 맞는지."""
        m = SpeakerMatcher()
        if await m.score(_tone(200)) is None:
            pytest.skip("모델 미탑재 환경")
        same = (await m.score(_tone(200)))["speaker_similarity"]
        diff = (await m.score(_tone(700)))["speaker_similarity"]
        assert same > diff
