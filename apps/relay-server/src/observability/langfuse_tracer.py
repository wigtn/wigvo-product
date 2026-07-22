"""Langfuse 기반 통화 추적 — 발신자↔수신자 양방향 대화 흐름 모니터링.

매핑:
  Trace             = 통화 1건 (call_id)
  child observation = 각 발화 턴 (방향 태그: caller→callee / callee→caller)

턴이 timestamp 순으로 쌓이므로 Langfuse trace 타임라인이 곧 대화의
오고-가는 흐름이 된다. 데모 중 부스 모니터에 띄워 실시간으로 보여줄 수 있다.

안전성:
  - Langfuse 키가 없거나 패키지가 미설치면 전체 no-op (통화 경로에 영향 없음).
  - 모든 메서드는 예외를 격리한다 — 추적 실패가 통화를 깨뜨리지 않는다.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from src.config import settings

if TYPE_CHECKING:
    from src.types import ActiveCall

logger = logging.getLogger(__name__)

# OpenInference 의미 규약 — MEGA Loop(및 Arize/Phoenix)가 트레이스를 읽는 표준.
#
# ⚠️ MegaCode 확인(2026-07-21): `openinference.span.kind`는 metadata가 아니라
# **OTel span attribute**로 넣어야 인식된다(metadata에 넣으면 무시됨). 유효값은
# LLM / CHAIN / TOOL / AGENT / GUARDRAIL 등. OTel의 SpanKind와는 다른 별도 문자열.
# input.value / output.value는 Langfuse native input/output 필드로 이미 인식되므로
# 그건 metadata에 중복으로 안 넣는다(start_observation(input=…, output=…)로 충분).
_OI_KIND = "openinference.span.kind"


def _set_span_kind(obs, kind: str) -> None:
    """관측의 OTel span attribute로 openinference.span.kind를 직접 세팅한다.

    Langfuse 관측 객체는 내부에 OTel span(_otel_span)을 감싼다. metadata가 아니라
    이 attribute에 넣어야 MEGA Loop readiness가 span kind를 인식한다(MegaCode 확인).
    내부 API라 방어적으로 감싼다 — 실패해도 추적이 통화를 깨지 않는다.
    """
    try:
        span = getattr(obs, "_otel_span", None)
        if span is not None and span.is_recording():
            span.set_attribute(_OI_KIND, kind)
    except Exception:
        logger.debug("openinference.span.kind attribute 세팅 실패 (무시)", exc_info=True)

# 방향 → trace 타임라인에 표시될 사람이 읽기 쉬운 라벨
DIRECTION_LABELS = {
    "caller_to_callee": "🗣️ Caller → Callee",
    "callee_to_caller": "📞 Callee → Caller",
}


_ENV_ALLOWED = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")


def _resolve_environment() -> str:
    """관측 환경 이름을 정한다 (부하 트래픽을 실사용과 분리하기 위한 태그).

    load_test_mode가 켜져 있으면 설정값과 무관하게 "load-test"로 강제한다 —
    하네스를 돌리는 쪽이 환경변수를 빠뜨려도 실사용 데이터가 오염되지 않아야 한다.
    Langfuse는 소문자/숫자/`.-_`만 허용하고 "langfuse" 접두사를 예약한다.
    """
    if settings.load_test_mode:
        return "load-test"
    env = (settings.langfuse_environment or "").strip().lower()
    if not _ENV_ALLOWED.match(env) or env.startswith("langfuse"):
        logger.warning(
            "LANGFUSE_ENVIRONMENT=%r 이 형식에 맞지 않아 'production'으로 대체", env
        )
        return "production"
    return env


class LangfuseTracer:
    """통화별 Langfuse trace 라이프사이클을 관리하는 싱글톤.

    키 미설정 시 self._enabled=False 로 모든 동작이 no-op 이 된다.
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._enabled: bool = False
        # call_id → 루트 observation(=trace) 핸들. 턴은 여기에 자식으로 붙는다.
        self._roots: dict[str, Any] = {}
        self._init_client()

    def _init_client(self) -> None:
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            logger.info("Langfuse 추적 비활성화 (키 없음) — no-op 모드")
            return
        try:
            from langfuse import Langfuse  # 지연 import: 키 있을 때만 의존

            environment = _resolve_environment()
            self._client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
                environment=environment,
            )
            self._enabled = True
            logger.info(
                "Langfuse 추적 활성화 (host=%s, environment=%s)",
                settings.langfuse_host,
                environment,
            )
        except Exception:
            logger.warning("Langfuse 초기화 실패 — 추적 비활성화", exc_info=True)
            self._client = None
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start_call(self, call: "ActiveCall") -> None:
        """통화 시작 시 루트 trace 를 생성한다."""
        if not self._enabled or not call.call_id:
            return
        if call.call_id in self._roots:
            return
        try:
            mode = call.communication_mode.value if call.communication_mode else "unknown"
            flow = "inbound" if call.inbound else "outbound"
            # 진입 기술자 — MEGA Loop가 "이 트레이스에 뭐가 들어왔나"를 잡는 input.value.
            # 실제 진입은 실시간 오디오라 그대로 replay는 불가하지만, 파이프라인을 규정하는
            # 통화 파라미터를 진입값으로 남겨 readiness의 root-input 요건을 충족한다.
            entry = {
                "mode": mode,
                "flow": flow,
                "source_language": call.source_language,
                "target_language": call.target_language,
            }
            # 루트 observation 이름이 곧 trace 이름이 된다.
            root = self._client.start_observation(
                name=f"📞 WIGVO Call · {call.source_language}↔{call.target_language} · {mode}",
                # native input = MEGA Loop가 읽는 input.value (진입값)
                input=entry,
                metadata={
                    "call_id": call.call_id,
                    "call_sid": call.call_sid,
                    "mode": mode,
                    # 필수 필드 (MEGA Loop 데이터셋 슬라이싱 키)
                    "flow": flow,
                    "tenant_id": str(call.tenant_id),
                    "source_language": call.source_language,
                    "target_language": call.target_language,
                },
            )
            # OpenInference: 루트는 비-LLM 체인 (OTel attribute로)
            _set_span_kind(root, "CHAIN")
            self._roots[call.call_id] = root
            # trace 레벨 input (deprecated API지만 v4에서 동작)
            try:
                root.set_trace_io(
                    input={
                        "mode": mode,
                        "source_language": call.source_language,
                        "target_language": call.target_language,
                    }
                )
            except Exception:
                logger.debug("Langfuse set_trace_io(input) 실패 (무시)", exc_info=True)
        except Exception:
            logger.warning("Langfuse start_call 실패", exc_info=True)

    def record_turn(
        self,
        call: "ActiveCall",
        *,
        direction: str,
        original_text: str,
        translated_text: str,
        language: str = "",
        latency_ms: float | None = None,
        latency_breakdown: dict[str, float] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str | None = None,
        stages: dict[str, Any] | None = None,
    ) -> None:
        """Record a single utterance turn as a child generation on the trace.

        direction: "caller_to_callee" | "callee_to_caller"
        stages: pipeline-stage signals (echo gate, VAD, STT, guardrail, ...)
                surfaced under "stage.*" metadata keys.
        """
        if not self._enabled or not call.call_id:
            return
        try:
            root = self._roots.get(call.call_id)
            if root is None:
                # Lazily create the trace even if start_call was missed.
                self.start_call(call)
                root = self._roots.get(call.call_id)
                if root is None:
                    return

            label = DIRECTION_LABELS.get(direction, direction)
            metadata: dict[str, Any] = {"direction": direction}
            if language:
                metadata["language"] = language
            # span.kind는 아래 obs 생성 후 OTel attribute로 세팅. input.value/output.value는
            # native input/output(아래 start_observation)로 MEGA Loop가 인식한다.

            # Per-stage latency under "latency.*"
            if latency_ms is not None:
                metadata["latency.total_ms"] = round(latency_ms, 1)
            if latency_breakdown:
                for key, val in latency_breakdown.items():
                    if val is not None:
                        metadata[f"latency.{key}"] = round(float(val), 1)

            # Pipeline-stage decisions under "stage.*"
            if stages:
                for key, val in stages.items():
                    if val is not None:
                        metadata[f"stage.{key}"] = val

            usage = None
            if input_tokens or output_tokens:
                usage = {
                    "input": input_tokens,
                    "output": output_tokens,
                    "total": input_tokens + output_tokens,
                }

            obs = root.start_observation(
                name=label,
                as_type="generation",
                input=original_text,
                output=translated_text,
                model=model,
                usage_details=usage,
                metadata=metadata,
            )
            # OpenInference: 번역 턴 = STT→번역 LLM 스텝 (OTel attribute)
            _set_span_kind(obs, "LLM")
            obs.end()
        except Exception:
            logger.warning("Langfuse record_turn failed", exc_info=True)

    def record_event(
        self,
        call: "ActiveCall",
        *,
        name: str,
        metadata: dict[str, Any] | None = None,
        is_error: bool = False,
    ) -> None:
        """Record a discrete pipeline moment (hallucination blocked, echo gate
        block, interrupt/barge-in) as an event observation on the trace.

        is_error=True면 span을 ERROR 레벨 + GUARDRAIL kind로 남긴다 — MEGA Loop가
        실패 신호로 감지하도록(§10 Detection gap: 실패 span은 ERROR여야 잘 잡힌다).
        """
        if not self._enabled or not call.call_id:
            return
        try:
            root = self._roots.get(call.call_id)
            if root is None:
                return
            obs = root.start_observation(
                name=name,
                as_type="event",
                # level=ERROR면 Langfuse가 OTel span status도 ERROR로 세팅한다
                # (MegaCode: 오류 span은 ERROR status여야 잘 감지됨).
                level="ERROR" if is_error else "DEFAULT",
                metadata=dict(metadata or {}),
            )
            # OpenInference span kind (OTel attribute)
            _set_span_kind(obs, "GUARDRAIL" if is_error else "CHAIN")
            obs.end()
        except Exception:
            logger.warning("Langfuse record_event failed", exc_info=True)

    # --- Flow tracing seam (PoC refactor · FR-5.1) ---
    # 비즈니스 로직 흐름(제어 흐름)을 스팬으로 잡는다. 각 WI가 자기 흐름을 이걸로 감싼다.
    # ⚠ PII 금지: transcript·전화번호·이름·프롬프트 등 '내용'은 attr로 넘기지 말 것.
    #   (§7 Langfuse 프라이버시 게이트 준수 — _safe_attrs가 위험 키를 드롭한다.)
    _PII_DENYLIST = (
        "transcript", "text", "content", "message", "utterance",
        "translation", "prompt", "phone", "audio", "speech",
    )

    def _safe_attrs(self, attrs: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, val in attrs.items():
            if any(bad in key.lower() for bad in self._PII_DENYLIST):
                logger.warning("flow_span: PII 가능성 attr 드롭 — %r", key)
                continue
            safe[key] = val
        return safe

    @contextmanager
    def flow_span(self, name: str, *, call_id: str = "", **attrs: Any):
        """비즈니스 흐름 스팬 (제어 흐름 전용).

        키 없으면 no-op, 통화 root가 있으면 그 아래 자식으로, 없으면 독립 스팬으로.
        추적 실패는 통화를 깨지 않는다(본문 예외는 그대로 전파, 추적 예외는 격리).
        attr은 id·state·duration·수치만 — _safe_attrs가 PII 키를 드롭한다.
        """
        obs = None
        if self._enabled:
            try:
                safe = self._safe_attrs(attrs)
                root = self._roots.get(call_id) if call_id else None
                if root is not None:
                    obs = root.start_observation(name=name, as_type="span", metadata=safe)
                elif self._client is not None:
                    obs = self._client.start_observation(name=name, metadata=safe)
                if obs is not None:
                    _set_span_kind(obs, "CHAIN")  # OpenInference: 제어 흐름 스팬
            except Exception:
                logger.warning("Langfuse flow_span 시작 실패 (무시)", exc_info=True)
                obs = None
        try:
            yield obs
        finally:
            if obs is not None:
                try:
                    obs.end()
                except Exception:
                    logger.debug("Langfuse flow_span end 실패 (무시)", exc_info=True)

    def end_call(self, call: "ActiveCall") -> None:
        """통화 종료 시 trace 를 마감하고 flush 한다."""
        if not self._enabled:
            return
        try:
            root = self._roots.pop(call.call_id, None)
            if root is not None:
                metrics = call.call_metrics
                summary = {
                    "turn_count": getattr(metrics, "turn_count", None),
                    "cost_usd": round(call.cost_tokens.cost_usd, 6),
                    "total_tokens": call.cost_tokens.total,
                    "hallucinations_blocked": getattr(metrics, "hallucinations_blocked", None),
                }
                try:
                    root.update(output=summary)
                    root.set_trace_io(output=summary)
                except Exception:
                    logger.debug("Langfuse end trace 요약 실패 (무시)", exc_info=True)
                root.end()
            self._client.flush()
        except Exception:
            logger.warning("Langfuse end_call 실패", exc_info=True)


# 모듈 import 시 1회 생성되는 싱글톤. 키가 없으면 즉시 no-op 모드.
tracer = LangfuseTracer()
