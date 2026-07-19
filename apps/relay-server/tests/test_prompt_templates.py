"""프롬프트 템플릿 계약 테스트."""

from src.prompt.templates import POLITENESS_RULES


class TestNoGenderedAddress:
    """원문에 없는 성별 호칭을 덧붙이도록 지시하지 않는다.

    한국어는 성별을 거의 표시하지 않는다. 'sir'/'ma'am'을 쓰라고 지시하면 모델이
    목소리로 성별을 추측해 원문에 없는 정보를 덧붙이고, 틀리면 상대를 잘못된
    성별로 부르게 된다 — 의료·행정 창구에서 특히 민감하다.
    실측(2026-07-19): "잘 들리시나요?" → "Ma'am, can you hear me well?"
    """

    def test_ko_en_does_not_request_gendered_address(self):
        rule = POLITENESS_RULES[("ko", "en")]
        assert "Do NOT add gendered address" in rule
        assert "Use 'sir', 'ma'am'" not in rule

    def test_ko_en_still_requires_polite_register(self):
        """성별 호칭만 빼고 공손함 요구는 유지한다."""
        assert "polite" in POLITENESS_RULES[("ko", "en")].lower()

    def test_en_ko_address_terms_are_gender_neutral(self):
        """반대 방향의 호칭(사장님/선생님)은 성중립이므로 그대로 둔다."""
        rule = POLITENESS_RULES[("en", "ko")]
        assert "사장님" in rule and "선생님" in rule
