"""OpenInference 계측 테스트 — MEGA Loop readiness 요건.

MegaCode 확인(2026-07-21): `openinference.span.kind`는 metadata가 아니라
**OTel span attribute**로 넣어야 인식된다. input.value는 Langfuse native input
필드로 인식된다. 이 테스트는 그 두 가지가 지켜지는지 검증한다.
"""

from unittest.mock import MagicMock

import pytest

from src.observability.langfuse_tracer import LangfuseTracer, _OI_KIND


def _mk_obs():
    """OTel span을 감싼 관측 mock. set_attribute 호출을 캡처한다."""
    obs = MagicMock()
    obs._otel_span = MagicMock()
    obs._otel_span.is_recording.return_value = True
    obs.start_observation.return_value = _mk_child()
    return obs


def _mk_child():
    child = MagicMock()
    child._otel_span = MagicMock()
    child._otel_span.is_recording.return_value = True
    return child


def _kind_calls(otel_span):
    """otel_span.set_attribute 중 span.kind 호출들의 값 목록."""
    return [c.args[1] for c in otel_span.set_attribute.call_args_list
            if c.args and c.args[0] == _OI_KIND]


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
    t = LangfuseTracer()
    t._enabled = True
    t._client = MagicMock()
    t._roots = {}
    root = _mk_obs()
    t._client.start_observation.return_value = root
    return t, root


class TestRootInstrumentation:
    def test_root_kind_is_otel_attribute_chain(self):
        t, root = _enabled_tracer()
        t.start_call(_make_call())
        # span.kind는 OTel attribute로 (metadata 아님)
        assert _kind_calls(root._otel_span) == ["CHAIN"]

    def test_root_input_is_native_input_field(self):
        t, root = _enabled_tracer()
        t.start_call(_make_call())
        kwargs = t._client.start_observation.call_args.kwargs
        # input.value는 native input 필드로 (MEGA가 여기서 읽음)
        assert kwargs["input"]["source_language"] == "ko"
        # metadata엔 OpenInference 키가 없어야 (metadata는 무시됨)
        assert _OI_KIND not in kwargs["metadata"]
        assert "input.value" not in kwargs["metadata"]


class TestTurnInstrumentation:
    def test_turn_kind_llm_and_native_io(self):
        t, root = _enabled_tracer()
        call = _make_call()
        t._roots["c1"] = root

        t.record_turn(call, direction="caller_to_callee",
                      original_text="안녕하세요", translated_text="Hello")

        child = root.start_observation.return_value
        assert _kind_calls(child._otel_span) == ["LLM"]
        kwargs = root.start_observation.call_args.kwargs
        assert kwargs["input"] == "안녕하세요"       # native → input.value
        assert kwargs["output"] == "Hello"           # native → output.value
        assert _OI_KIND not in kwargs["metadata"]    # metadata엔 없음


class TestEventInstrumentation:
    def test_failure_event_error_status_and_guardrail(self):
        t, root = _enabled_tracer()
        t._roots["c1"] = root
        t.record_event(_make_call(), name="🛑 Hallucination blocked", is_error=True)

        child = root.start_observation.return_value
        assert root.start_observation.call_args.kwargs["level"] == "ERROR"  # OTel status=ERROR
        assert _kind_calls(child._otel_span) == ["GUARDRAIL"]

    def test_normal_event_default_and_chain(self):
        t, root = _enabled_tracer()
        t._roots["c1"] = root
        t.record_event(_make_call(), name="🎙 Speaker match")

        child = root.start_observation.return_value
        assert root.start_observation.call_args.kwargs["level"] == "DEFAULT"
        assert _kind_calls(child._otel_span) == ["CHAIN"]


class TestFlowSpanInstrumentation:
    def test_flow_span_kind_chain(self):
        t, root = _enabled_tracer()
        t._roots["c1"] = root
        with t.flow_span("wi.dispatch", call_id="c1", state="CLAIMED"):
            pass
        child = root.start_observation.return_value
        assert _kind_calls(child._otel_span) == ["CHAIN"]


class TestSafety:
    def test_set_span_kind_survives_missing_otel_span(self):
        """관측에 _otel_span이 없거나 recording 아니어도 예외 없이 통과."""
        from src.observability.langfuse_tracer import _set_span_kind
        _set_span_kind(MagicMock(spec=[]), "LLM")          # _otel_span 없음
        not_recording = MagicMock()
        not_recording._otel_span.is_recording.return_value = False
        _set_span_kind(not_recording, "LLM")               # recording 아님 → 스킵
        not_recording._otel_span.set_attribute.assert_not_called()

    def test_all_noop_when_disabled(self):
        t = LangfuseTracer()
        t._enabled = False
        call = _make_call()
        t.start_call(call)
        t.record_turn(call, direction="caller_to_callee", original_text="a", translated_text="b")
        t.record_event(call, name="x", is_error=True)
