"""OpenInference 계측 테스트 — MEGA Loop readiness 요건.

MEGA Loop는 트레이스를 OpenInference 규약(`openinference.span.kind`, `input.value`)으로
읽는다. 우리 네이티브 Langfuse 계측엔 이 키가 없어 readiness가 막혔다(root input 없음,
span kind 없음). 트레이서가 span별로 이 키를 심는지 검증한다.
"""

import json
from unittest.mock import MagicMock

import pytest

from src.observability.langfuse_tracer import (
    LangfuseTracer,
    _OI_INPUT,
    _OI_KIND,
    _OI_OUTPUT,
)


def _make_call(call_id="c1"):
    call = MagicMock()
    call.call_id = call_id
    call.call_sid = "CA123"
    call.communication_mode = MagicMock(value="voice_to_voice")
    call.inbound = True
    call.tenant_id = "t1"
    call.source_language = "ko"
    call.target_language = "en"
    return call


def _enabled_tracer():
    """mock client를 단 활성 트레이서. root/child의 start_observation을 캡처한다."""
    t = LangfuseTracer()
    t._enabled = True
    t._client = MagicMock()
    t._roots = {}
    # _client.start_observation()가 반환하는 root observation도 mock
    root = MagicMock()
    t._client.start_observation.return_value = root
    return t, root


class TestRootInstrumentation:
    def test_root_has_chain_kind_and_input_value(self):
        t, _ = _enabled_tracer()
        call = _make_call()
        t.start_call(call)

        kwargs = t._client.start_observation.call_args.kwargs
        meta = kwargs["metadata"]
        assert meta[_OI_KIND] == "CHAIN"  # 루트는 비-LLM 체인
        # input.value는 진입 기술자 JSON — MEGA Loop가 root input으로 읽음
        entry = json.loads(meta[_OI_INPUT])
        assert entry["mode"] == "voice_to_voice"
        assert entry["flow"] == "inbound"
        assert entry["source_language"] == "ko"
        # 네이티브 input도 함께 세팅
        assert kwargs["input"]["target_language"] == "en"


class TestTurnInstrumentation:
    def test_turn_has_llm_kind_and_io_value(self):
        t, root = _enabled_tracer()
        call = _make_call()
        t._roots["c1"] = root

        t.record_turn(
            call,
            direction="caller_to_callee",
            original_text="안녕하세요",
            translated_text="Hello",
        )

        kwargs = root.start_observation.call_args.kwargs
        assert kwargs["as_type"] == "generation"
        meta = kwargs["metadata"]
        assert meta[_OI_KIND] == "LLM"  # 번역 턴은 LLM 스텝
        assert meta[_OI_INPUT] == "안녕하세요"
        assert meta[_OI_OUTPUT] == "Hello"


class TestEventInstrumentation:
    def test_failure_event_is_error_and_guardrail(self):
        t, root = _enabled_tracer()
        call = _make_call()
        t._roots["c1"] = root

        t.record_event(call, name="🛑 Hallucination blocked", is_error=True)

        kwargs = root.start_observation.call_args.kwargs
        assert kwargs["level"] == "ERROR"  # 실패 신호 → MEGA Loop 감지
        assert kwargs["metadata"][_OI_KIND] == "GUARDRAIL"

    def test_normal_event_is_default_and_chain(self):
        t, root = _enabled_tracer()
        call = _make_call()
        t._roots["c1"] = root

        t.record_event(call, name="🎙 Speaker match")

        kwargs = root.start_observation.call_args.kwargs
        assert kwargs["level"] == "DEFAULT"  # 정상 필터는 실패 아님
        assert kwargs["metadata"][_OI_KIND] == "CHAIN"


class TestFlowSpanInstrumentation:
    def test_flow_span_has_chain_kind(self):
        t, root = _enabled_tracer()
        t._roots["c1"] = root

        with t.flow_span("wi.dispatch", call_id="c1", state="CLAIMED"):
            pass

        kwargs = root.start_observation.call_args.kwargs
        assert kwargs["metadata"][_OI_KIND] == "CHAIN"


def test_all_still_noop_when_disabled():
    """키 없으면 계측 추가와 무관하게 전체 no-op."""
    t = LangfuseTracer()
    t._enabled = False
    call = _make_call()
    # 예외 없이 조용히 통과해야 한다
    t.start_call(call)
    t.record_turn(call, direction="caller_to_callee", original_text="a", translated_text="b")
    t.record_event(call, name="x", is_error=True)
