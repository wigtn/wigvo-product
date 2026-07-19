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
    async def test_enrolls_after_collecting_candidates(self):
        """계약 변경(2026-07-19): 첫 발화를 곧바로 기준으로 삼지 않는다 —
        배경음이 먼저 잡히면 그것이 응대자가 되기 때문이다(통화 B에서 실증)."""
        m = SpeakerMatcher()
        if await m.score(_tone(200)) is None:
            pytest.skip("모델 미탑재 환경")
        assert m.enrolled is False, "첫 발화만으로 등록하면 안 된다"

        for _ in range(SpeakerMatcher.CANDIDATE_SEGMENTS):
            await m.score(_tone(200))
        assert m.enrolled is True

        after = await m.score(_tone(200))
        assert -1.0 <= after["speaker_similarity"] <= 1.0

    @pytest.mark.asyncio
    async def test_score_is_a_valid_similarity(self):
        """배선 검증 — 판정 단계에서 유효 범위의 값이 나오는지.

        모델의 변별력 자체는 여기서 검증하지 않는다. ECAPA는 음성으로 학습돼
        합성 톤끼리는 임베딩이 뭉개지므로(둘 다 1.0), 단위 테스트로 주장할 수
        없는 성질이다. 변별력은 실제 음성으로 오프라인 검증한다 —
        실측: 본인 0.585~0.754 vs 유튜브 -0.051~0.306.
        """
        m = SpeakerMatcher()
        if await m.score(_tone(200)) is None:
            pytest.skip("모델 미탑재 환경")
        for _ in range(SpeakerMatcher.CANDIDATE_SEGMENTS):
            await m.score(_tone(200))
        result = await m.score(_tone(200))
        assert result["speaker_phase"] == "scoring"
        assert -1.0 <= result["speaker_similarity"] <= 1.0


class TestDeferredClusterEnrollment:
    """기준을 첫 발화가 아니라 '다수 화자'로 정한다.

    실측(2026-07-19 통화 B): 유튜브를 먼저 틀었더니 그것이 응대자로 등록됐고,
    이후 본인 발화가 전부 -0.051~0.225로 떨어졌다. 차단을 켰다면 응대자가
    통째로 막혔을 상황이다. 전제는 '통화에서 응대자가 가장 많이 말한다'이며
    실측 2통화 모두 성립했다(6:3, 4:3).
    """

    def _matcher_with(self, embeddings):
        """임베딩을 직접 주입해 선출 로직만 검사한다 (모델 호출 없이)."""
        m = SpeakerMatcher()
        m._candidates = [np.asarray(e, dtype=np.float32) / np.linalg.norm(e) for e in embeddings]
        return m

    def test_majority_speaker_wins_even_if_background_spoke_first(self):
        """배경음이 먼저 와도 다수인 응대자가 기준이 된다."""
        bg = [1.0, 0.0, 0.0]      # 배경 화자
        op = [0.0, 1.0, 0.0]      # 응대자
        m = self._matcher_with([bg, bg, op, op, op])   # 배경이 먼저, 응대자가 다수
        m._elect_reference()
        # 기준이 응대자 쪽에 붙어야 한다
        assert float(np.dot(m._reference, np.array(op, dtype=np.float32))) > 0.9
        assert float(np.dot(m._reference, np.array(bg, dtype=np.float32))) < 0.4
        assert m._enroll_count == 3

    def test_election_is_deferred_when_no_majority_exists(self):
        """후보가 전부 다른 화자면 선출을 보류한다.

        그대로 선출하면 무리가 1개가 되어 '첫 발화 = 기준'으로 되돌아간다 —
        고치려던 문제 그대로다.
        """
        m = self._matcher_with([[1, 0, 0], [0, 1, 0], [0, 0, 1]])
        assert m._elect_reference() == 0
        assert m.enrolled is False
        assert len(m._candidates) == 3, "후보는 버리지 않고 더 모은다"

    def test_backfill_scores_the_candidate_window(self):
        """후보 구간도 사후 채점한다 — 그냥 버리면 통화당 앞 N건이 통째로 빠진다."""
        op = [0.0, 1.0, 0.0]
        m = self._matcher_with([op, op, [1.0, 0.0, 0.0]])
        m._elect_reference()
        assert len(m._backfill) == 3
        assert m._backfill[0] > 0.9   # 응대자
        assert m._backfill[2] < 0.4   # 타인

    def test_reference_is_average_of_the_cluster(self):
        """한 발성에 묶이지 않도록 무리 전체를 평균한다."""
        a = [1.0, 0.1, 0.0]
        b = [1.0, 0.0, 0.1]
        c = [0.0, 0.0, 1.0]       # 다른 화자
        m = self._matcher_with([a, b, c, a, b])
        m._elect_reference()
        assert m._enroll_count == 4
        assert float(np.dot(m._reference, np.array(c, dtype=np.float32))) < 0.4

    @pytest.mark.asyncio
    async def test_no_scoring_before_reference_is_elected(self):
        """기준이 정해지기 전에는 판정하지 않는다 — 근거 없는 점수를 남기면
        나중에 분포를 볼 때 오염된다."""
        m = SpeakerMatcher()
        first = await m.score(_tone(200))
        if first is None:
            pytest.skip("모델 미탑재 환경")
        assert first["speaker_similarity"] is None
        assert first["speaker_phase"] == "collecting"

    @pytest.mark.asyncio
    async def test_scoring_starts_after_candidates_are_collected(self):
        m = SpeakerMatcher()
        if await m.score(_tone(200)) is None:
            pytest.skip("모델 미탑재 환경")
        for _ in range(SpeakerMatcher.CANDIDATE_SEGMENTS):
            r = await m.score(_tone(200))
        assert m.enrolled is True
        after = await m.score(_tone(200))
        assert after["speaker_phase"] == "scoring"
        assert after["speaker_similarity"] is not None


class TestEnforcement:
    """차단 판정과 오등록 대비 안전장치.

    잘못 차단하면 발화가 조용히 사라지고 사용자가 즉시 알아챈다 —
    실측(2026-07-19): "방금 말한 거 왜 번역 안 해?". 그래서 임계는 보수적으로
    잡고, 차단이 과반을 넘으면 기준을 못 믿는 것으로 보고 스스로 끈다.
    """

    def _enrolled(self, reference):
        m = SpeakerMatcher()
        m._reference = np.asarray(reference, dtype=np.float32)
        m._reference /= np.linalg.norm(m._reference)
        m._enroll_count = 3
        return m

    def _score_with(self, m, similarity):
        """유사도를 직접 만들어 판정 로직만 검사한다."""
        from src.config import settings
        m._scored += 1
        is_other = similarity < settings.speaker_id_min_similarity
        block = settings.speaker_id_enforce and not m._enforce_disabled and is_other
        if block:
            m._blocked += 1
            if (m._scored >= settings.speaker_id_abort_min_scored
                    and m._blocked / m._scored > settings.speaker_id_abort_block_ratio):
                m._enforce_disabled = True
                block = False
        return block

    def test_other_speaker_is_blocked(self):
        from src.config import settings

        m = self._enrolled([1.0, 0.0, 0.0])
        assert self._score_with(m, settings.speaker_id_min_similarity - 0.1) is True

    def test_own_voice_passes(self):
        from src.config import settings

        m = self._enrolled([1.0, 0.0, 0.0])
        assert self._score_with(m, settings.speaker_id_min_similarity + 0.1) is False

    def test_enforcement_disables_itself_when_blocking_everything(self):
        """등록이 오염되면 본인 발화가 전부 차단된다 — 실측(통화 B)에서 재현된
        상황이다. 조용한 전면 차단만은 막는다."""
        m = self._enrolled([1.0, 0.0, 0.0])
        blocks = [self._score_with(m, 0.05) for _ in range(6)]
        assert m._enforce_disabled is True, "차단 과다 시 스스로 꺼져야 한다"
        assert blocks[-1] is False, "해제 후에는 통과시켜야 한다"

    def test_does_not_disable_on_a_few_early_blocks(self):
        """초반 몇 건이 타인이라고 곧바로 꺼지면 안 된다."""
        from src.config import settings

        m = self._enrolled([1.0, 0.0, 0.0])
        for _ in range(settings.speaker_id_abort_min_scored - 1):
            self._score_with(m, 0.05)
        assert m._enforce_disabled is False
