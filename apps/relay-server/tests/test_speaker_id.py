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

    @pytest.mark.asyncio
    async def test_reference_is_frozen_after_election(self):
        """선출 후에는 어떤 발화도 기준을 바꾸지 못한다.

        보강을 두면 되먹임으로 기준이 무너진다: 배경음이 섞인 발화가 기준에
        합쳐지면 기준이 흐려지고, 그러면 다음 본인 발화의 유사도가 떨어져 더
        흐린 샘플이 합쳐진다. 실측(2026-07-19 18:24)에서 본인 유사도가
        0.628→0.301로 단조 하락해 임계 0.30을 0.001 차이로 통과했다.
        """
        m = SpeakerMatcher()
        if await m.score(_tone(200)) is None:
            pytest.skip("모델 미탑재 환경")
        for _ in range(SpeakerMatcher.CANDIDATE_SEGMENTS):
            await m.score(_tone(200))
        assert m.enrolled is True

        frozen = m._reference.copy()
        # 기준과 비슷한 발화도, 전혀 다른 발화도 기준을 건드리면 안 된다
        for tone in (200, 200, 900, 1500):
            await m.score(_tone(tone))
            assert np.array_equal(m._reference, frozen), (
                f"{tone}Hz 발화 후 기준이 바뀌었다 — 보강이 되살아났다")


class TestEnforcement:
    """차단 판정과 오등록 대비 안전장치.

    잘못 차단하면 발화가 조용히 사라지고 사용자가 즉시 알아챈다 —
    실측(2026-07-19): "방금 말한 거 왜 번역 안 해?". 그래서 임계는 보수적으로
    잡고, 통과 없이 연속으로 차단되면 기준을 못 믿는 것으로 보고 스스로 끈다.
    """

    def _enrolled(self, reference):
        m = SpeakerMatcher()
        m._reference = np.asarray(reference, dtype=np.float32)
        m._reference /= np.linalg.norm(m._reference)
        m._enroll_count = 3
        return m

    def _score_with(self, m, similarity):
        """유사도를 직접 만들어 판정 로직만 검사한다.

        판정을 여기서 재구현하지 않고 프로덕션 _decide()를 그대로 부른다 —
        복제하면 사본만 통과하고 실제 코드의 회귀를 놓친다.
        """
        _is_other, block = m._decide(similarity)
        return block

    def test_other_speaker_is_blocked(self):
        from src.config import settings

        m = self._enrolled([1.0, 0.0, 0.0])
        assert self._score_with(m, settings.speaker_id_min_similarity - 0.1) is True

    def test_own_voice_passes(self):
        from src.config import settings

        m = self._enrolled([1.0, 0.0, 0.0])
        assert self._score_with(m, settings.speaker_id_min_similarity + 0.1) is False

    def test_disables_only_after_consecutive_blocks(self):
        """오등록이면 본인 발화조차 통과하지 못한다 — 그 신호는 '연속 차단'이다.
        실측(통화 B): 유튜브가 등록돼 본인이 -0.051~0.225로 전부 낮았다."""
        from src.config import settings

        m = self._enrolled([1.0, 0.0, 0.0])
        n = settings.speaker_id_abort_consecutive_blocks
        blocks = [self._score_with(m, 0.05) for _ in range(n)]
        assert m._enforce_disabled is True, "연속 차단이 이어지면 스스로 꺼져야 한다"
        assert blocks[-1] is False

    def test_alternating_traffic_never_disables(self):
        """실측(2026-07-19 18:00) 재현 — 유튜브와 번갈아 말한 통화.

        등록은 완벽했는데(본인 0.618~0.785, 유튜브 -0.032~0.174) 이전 비율
        방식은 4/7에서 오작동해 이후 유튜브가 전부 통과했다. 차단이 많은 것
        자체는 문제가 아니다.
        """
        m = self._enrolled([1.0, 0.0, 0.0])
        observed = [0.128, 0.777, 0.682, 0.096, 0.785, 0.174, 0.143, 0.510,
                    0.655, 0.683, 0.095, 0.037, 0.011, 0.641]
        results = [self._score_with(m, sim) for sim in observed]
        assert m._enforce_disabled is False, "정당한 차단이 많다고 꺼지면 안 된다"
        # 유튜브는 전부 차단, 본인은 전부 통과
        for sim, blocked in zip(observed, results):
            assert blocked == (sim < 0.30)

    def test_a_pass_resets_the_consecutive_counter(self):
        """본인 발화가 통과하면 기준이 살아 있다는 뜻 — 카운터를 초기화한다."""
        from src.config import settings

        m = self._enrolled([1.0, 0.0, 0.0])
        for _ in range(settings.speaker_id_abort_consecutive_blocks - 1):
            self._score_with(m, 0.05)
        self._score_with(m, 0.9)          # 본인 통과
        assert m._consecutive_blocks == 0
        self._score_with(m, 0.05)
        assert m._enforce_disabled is False
