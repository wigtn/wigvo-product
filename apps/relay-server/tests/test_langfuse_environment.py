"""관측 환경 분리 — 부하 트래픽이 실사용 데이터를 오염시키지 않아야 한다.

배경: 프로덕션 Langfuse에 통화 300건이 쌓였는데 297건이 비용 0원인 부하
트래픽이었고 실사용은 3건뿐이었다. 같은 환경에 섞이면 품질 기준선도,
MEGA Loop에 넘길 평가셋도 신뢰할 수 없다.
"""

import pytest

from src.config import settings
from src.observability.langfuse_tracer import _resolve_environment


@pytest.fixture(autouse=True)
def restore_settings():
    env, load = settings.langfuse_environment, settings.load_test_mode
    yield
    settings.langfuse_environment, settings.load_test_mode = env, load


def test_default_is_production():
    settings.load_test_mode = False
    settings.langfuse_environment = "production"
    assert _resolve_environment() == "production"


def test_load_test_mode_overrides_configured_environment():
    """하네스를 돌리는 쪽이 환경변수를 빠뜨려도 실사용 데이터가 오염되면 안 된다."""
    settings.langfuse_environment = "production"
    settings.load_test_mode = True
    assert _resolve_environment() == "load-test"


def test_custom_environment_is_passed_through():
    settings.load_test_mode = False
    settings.langfuse_environment = "staging"
    assert _resolve_environment() == "staging"


@pytest.mark.parametrize("bad", ["Prod Env!", "langfuse-internal", "", "-leading", "a" * 41])
def test_invalid_environment_falls_back_to_production(bad):
    """Langfuse 형식(소문자·숫자·.-_, langfuse 접두사 예약) 위반 시 안전한 기본값."""
    settings.load_test_mode = False
    settings.langfuse_environment = bad
    assert _resolve_environment() == "production"
