"""OpenInference 계측 테스트 — MEGA Loop readiness 요건.

실측 확정(2026-07-25): MEGA는 Langfuse REST 관측의
`metadata.attributes["openinference.span.kind"]` (metadata 하위 attributes)를 읽는다.
이는 OTLP/OpenInference 계측이 OTel span attribute로 보냈을 때 Langfuse가 저장하는
바로 그 위치다. 네이티브 SDK로도 metadata를 attributes 하위에 중첩하면 동일 JSON이 나온다.
top-level metadata[key]나 _otel_span.set_attribute()는 그 위치에 안 뜬다(MEGA 안 읽음).

이 테스트는 span.kind가 metadata.attributes에, input/output이 native 필드에 실리는지 검증한다.
"""

from unittest.mock import MagicMock

from src.observability.langfuse_tracer import LangfuseTracer, _OI_KIND


def _span_kind(kwargs) -> str | None:
    """start_observation kwargs의 metadata.attributes에서 span.kind를 꺼낸다."""
    md = kwargs.get("metadata") or {}
    attrs = md.get("attributes") if isinstance(md, dict) else None
    return attrs.get(_OI_KIND) if isinstance(attrs, dict) else None


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
    root = MagicMock()
    t._client.start_observation.return_value = root
    return t, root


class TestRootInstrumentation:
    def test_root_kind_in_metadata_attributes(self):
        t, root = _enabled_tracer()
        t.start_call(_make_call())
        kwargs = t._client.start_observation.call_args.kwargs
        assert _span_kind(kwargs) == "CHAIN"          # metadata.attributes에
        assert _OI_KIND not in kwargs["metadata"]      # top-level metadata엔 없음

    def test_root_input_is_native_field(self):
        t, root = _enabled_tracer()
        t.start_call(_make_call())
        kwargs = t._client.start_observation.call_args.kwargs
        assert kwargs["input"]["source_language"] == "ko"   # native input


class TestTurnInstrumentation:
    def test_turn_kind_llm_and_native_io(self):
        t, root = _enabled_tracer()
        call = _make_call()
        t._roots["c1"] = root
        t.record_turn(call, direction="caller_to_callee",
                      original_text="안녕하세요", translated_text="Hello")
        kwargs = root.start_observation.call_args.kwargs
        assert _span_kind(kwargs) == "LLM"
        assert kwargs["input"] == "안녕하세요"       # native → input.value
        assert kwargs["output"] == "Hello"           # native → output.value


class TestEventInstrumentation:
    def test_failure_event_error_status_and_guardrail(self):
        t, root = _enabled_tracer()
        t._roots["c1"] = root
        t.record_event(_make_call(), name="🛑 Hallucination blocked", is_error=True)
        kwargs = root.start_observation.call_args.kwargs
        assert kwargs["level"] == "ERROR"            # OTel span status ERROR
        assert _span_kind(kwargs) == "GUARDRAIL"

    def test_normal_event_default_and_chain(self):
        t, root = _enabled_tracer()
        t._roots["c1"] = root
        t.record_event(_make_call(), name="🎙 Speaker match")
        kwargs = root.start_observation.call_args.kwargs
        assert kwargs["level"] == "DEFAULT"
        assert _span_kind(kwargs) == "CHAIN"

    def test_event_preserves_caller_metadata(self):
        t, root = _enabled_tracer()
        t._roots["c1"] = root
        t.record_event(_make_call(), name="x", metadata={"reason": "echo"})
        kwargs = root.start_observation.call_args.kwargs
        assert kwargs["metadata"]["reason"] == "echo"   # 기존 metadata 보존
        assert _span_kind(kwargs) == "CHAIN"


class TestFlowSpanInstrumentation:
    def test_flow_span_kind_chain(self):
        t, root = _enabled_tracer()
        t._roots["c1"] = root
        with t.flow_span("wi.dispatch", call_id="c1", state="CLAIMED"):
            pass
        kwargs = root.start_observation.call_args.kwargs
        assert _span_kind(kwargs) == "CHAIN"


class TestSafety:
    def test_all_noop_when_disabled(self):
        t = LangfuseTracer()
        t._enabled = False
        call = _make_call()
        t.start_call(call)
        t.record_turn(call, direction="caller_to_callee", original_text="a", translated_text="b")
        t.record_event(call, name="x", is_error=True)
