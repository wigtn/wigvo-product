"""Echo Gate + Silence Injection + 오디오 에너지 게이트 테스트.

Echo Gate (Silence Injection):
  - TTS 전송 중 + 동적 cooldown 구간에서 Twilio 오디오를 무음(0xFF)으로 대체
  - 완전 차단 대신 무음 전송 → VAD가 speech_stopped을 정상 감지
  - Echo window 중 speech_started/stopped 이벤트 무시 (에코 반응 방지)

동적 Cooldown:
  - TTS 길이에 비례하는 cooldown = 남은 재생 시간 + 에코 왕복 마진(0.5s)
  - 짧은 TTS("네") → ~0.8s cooldown, 긴 TTS → ~3s cooldown

오디오 에너지 게이트:
  - mu-law 오디오 RMS 에너지 측정
  - 임계값 미만의 무음/소음 차단 (Whisper 환각 방지)
"""

import asyncio
import base64
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.realtime.audio_router import AudioRouter
from src.realtime.audio_utils import _ULAW_TO_LINEAR, ulaw_rms as _ulaw_rms
from src.realtime.pipeline.echo_gate import EchoGateManager
from src.realtime.sessions.session_b import SessionBHandler
from src.types import ActiveCall, CallMetrics, CallMode


def _make_call(**overrides) -> ActiveCall:
    defaults = dict(
        call_id="test-call",
        user_id="u1",
        mode=CallMode.RELAY,
        source_language="en",
        target_language="ko",
        target_phone="+821012345678",
        twilio_call_sid="CA_test",
    )
    defaults.update(overrides)
    return ActiveCall(**defaults)


def _make_router() -> AudioRouter:
    """최소한의 mock으로 AudioRouter 인스턴스를 생성한다."""
    call = _make_call()

    # DualSessionManager mock
    dual = MagicMock()
    dual.session_a = MagicMock()
    dual.session_a.on = MagicMock()
    dual.session_a.set_on_connection_lost = MagicMock()
    dual.session_a._send = AsyncMock()
    dual.session_b = MagicMock()
    dual.session_b.on = MagicMock()
    dual.session_b.set_on_connection_lost = MagicMock()
    dual.session_b._send = AsyncMock()
    dual.session_b.clear_input_buffer = AsyncMock()

    twilio_handler = MagicMock()
    twilio_handler.send_audio = AsyncMock()
    twilio_handler.send_clear = AsyncMock()

    app_ws_send = AsyncMock()

    with patch("src.realtime.pipeline.voice_to_voice.settings") as mock_settings:
        mock_settings.guardrail_enabled = False
        mock_settings.ring_buffer_capacity_slots = 100
        mock_settings.call_warning_ms = 480_000
        mock_settings.max_call_duration_ms = 600_000
        mock_settings.audio_energy_gate_enabled = False  # 테스트에서는 기본 비활성
        mock_settings.audio_energy_min_rms = 150.0
        mock_settings.echo_energy_threshold_rms = 400.0
        mock_settings.local_vad_enabled = False  # 테스트에서는 Server VAD 사용
        router = AudioRouter(
            call=call,
            dual_session=dual,
            twilio_handler=twilio_handler,
            app_ws_send=app_ws_send,
        )

    return router


class TestEchoGate:
    """Echo Gate: echo window 활성화/비활성화 + 동적 cooldown 테스트."""

    def test_echo_window_activates(self):
        """echo_gate._activate() 호출 시 in_echo_window = True."""
        router = _make_router()
        assert router.echo_gate.in_echo_window is False

        router.echo_gate._activate()

        assert router.echo_gate.in_echo_window is True

    @pytest.mark.asyncio
    async def test_echo_window_deactivates_after_dynamic_cooldown(self):
        """동적 cooldown 후 in_echo_window = False."""
        router = _make_router()

        # TTS 길이 시뮬레이션: 800 bytes = 0.1s of audio @ 8kHz
        router.echo_gate._tts_first_chunk_at = time.time()
        router.echo_gate._tts_total_bytes = 800

        router.echo_gate._activate()
        assert router.echo_gate.in_echo_window is True

        router.echo_gate.on_tts_done()
        # 동적 cooldown: remaining(0.1s) + margin(0.3s), capped at 1.2s
        await asyncio.sleep(1.0)

        assert router.echo_gate.in_echo_window is False

    def test_echo_cooldown_reset_on_new_tts(self):
        """새 TTS 시작 시 기존 쿨다운 타이머가 취소."""
        router = _make_router()

        old_task = MagicMock()
        old_task.done.return_value = False
        old_task.cancel = MagicMock()
        router.echo_gate._echo_cooldown_task = old_task

        router.echo_gate._activate()

        old_task.cancel.assert_called_once()
        assert router.echo_gate._echo_cooldown_task is None

    @pytest.mark.asyncio
    async def test_tts_activates_echo_window(self):
        """_on_session_a_tts 호출 시 echo window 활성화."""
        router = _make_router()
        router.interrupt = MagicMock()
        router.interrupt.is_recipient_speaking = False

        await router._on_session_a_tts(b"\x00\x01")

        assert router.echo_gate.in_echo_window is True

    @pytest.mark.asyncio
    async def test_done_starts_dynamic_cooldown(self):
        """응답 완료 시 동적 cooldown이 시작된다."""
        router = _make_router()

        # TTS 추적값 설정 (짧은 TTS)
        router.echo_gate._tts_first_chunk_at = time.time()
        router.echo_gate._tts_total_bytes = 400  # 0.05s of audio

        router.echo_gate._activate()
        await router._on_session_a_done()

        # cooldown task가 생성됨
        assert router.echo_gate._echo_cooldown_task is not None
        # 짧은 TTS → 빠른 cooldown (0.05 + 0.3 = 0.35s, capped at 1.2s)
        await asyncio.sleep(1.0)
        assert router.echo_gate.in_echo_window is False


class TestSilenceInjection:
    """Silence Injection: echo window 중 무음 대체 + 이벤트 무시 테스트."""

    @pytest.mark.asyncio
    async def test_silence_injected_during_echo_window_low_energy(self):
        """echo window 중 저에너지 오디오(에코)가 무음(0xFF)으로 대체되어 Session B에 전송."""
        router = _make_router()
        router.session_b.send_recipient_audio = AsyncMock()
        router.echo_gate.in_echo_window = True

        audio = bytes([0xFE] * 160)  # 저에너지 오디오 (에코 수준)
        await router.handle_twilio_audio(audio)

        # 무음(0xFF)이 Session B에 전송됨
        router.session_b.send_recipient_audio.assert_called_once()
        sent_b64 = router.session_b.send_recipient_audio.call_args[0][0]
        sent_bytes = base64.b64decode(sent_b64)
        assert all(b == 0xFF for b in sent_bytes)
        assert len(sent_bytes) == 160

    @pytest.mark.asyncio
    async def test_first_high_energy_absorbed_as_echo(self):
        """echo window 중 첫 번째 고에너지 → PSTN 에코로 흡수, 게이트 유지."""
        router = _make_router()
        router.session_b.send_recipient_audio = AsyncMock()
        router.echo_gate.in_echo_window = True

        audio = bytes([0x10] * 160)
        await router.handle_twilio_audio(audio)

        assert router.echo_gate.in_echo_window is True
        router.session_b.send_recipient_audio.assert_called_once()
        sent_b64 = router.session_b.send_recipient_audio.call_args[0][0]
        sent_bytes = base64.b64decode(sent_b64)
        assert sent_bytes == b"\xff" * 160

    @pytest.mark.asyncio
    async def test_second_high_energy_breaks_echo_gate(self):
        """echo window 중 두 번째 고에너지 → 진짜 발화, 게이트 해제 + 원본 전달."""
        router = _make_router()
        router.session_b.send_recipient_audio = AsyncMock()
        router.echo_gate.in_echo_window = True

        audio = bytes([0x10] * 160)
        await router.handle_twilio_audio(audio)  # 첫 번째: 흡수
        router.session_b.send_recipient_audio.reset_mock()

        await router.handle_twilio_audio(audio)  # 두 번째: break
        assert router.echo_gate.in_echo_window is False
        router.session_b.send_recipient_audio.assert_called_once()
        sent_b64 = router.session_b.send_recipient_audio.call_args[0][0]
        sent_bytes = base64.b64decode(sent_b64)
        assert sent_bytes == audio

    @pytest.mark.asyncio
    async def test_real_audio_passes_outside_echo_window(self):
        """echo window 외 → 실제 오디오가 Session B에 전송."""
        router = _make_router()
        router.session_b.send_recipient_audio = AsyncMock()
        router.echo_gate.in_echo_window = False

        audio = bytes([0x10] * 160)

        with patch("src.realtime.pipeline.voice_to_voice.settings") as mock_settings:
            mock_settings.audio_energy_gate_enabled = False
            await router.handle_twilio_audio(audio)

        router.session_b.send_recipient_audio.assert_called_once()
        sent_b64 = router.session_b.send_recipient_audio.call_args[0][0]
        sent_bytes = base64.b64decode(sent_b64)
        assert sent_bytes == audio

    @pytest.mark.asyncio
    async def test_speech_started_breaks_echo_window(self):
        """echo window 중 speech_started는 게이트를 해제하고 정상 처리된다."""
        router = _make_router()
        router.echo_gate.in_echo_window = True

        router.first_message = MagicMock()
        router.first_message.on_recipient_speech_detected = AsyncMock()
        router.call.first_message_sent = False

        await router._on_recipient_started()

        # echo window 해제 + 정상 처리
        assert router.echo_gate.in_echo_window is False
        router.first_message.on_recipient_speech_detected.assert_called_once()

    @pytest.mark.asyncio
    async def test_speech_stopped_processed_during_echo_window(self):
        """echo window 중에도 speech_stopped는 정상 처리된다."""
        router = _make_router()
        router.echo_gate.in_echo_window = True

        router.interrupt = MagicMock()
        router.interrupt.on_recipient_speech_stopped = AsyncMock()
        router.context_manager = MagicMock()
        router.context_manager.inject_context = AsyncMock()

        await router._on_recipient_stopped()

        # echo window 중에도 정상 처리
        router.interrupt.on_recipient_speech_stopped.assert_called_once()
        router.context_manager.inject_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_speech_processed_outside_echo_window(self):
        """echo window 외 speech_started는 정상 처리됨."""
        router = _make_router()
        router.echo_gate.in_echo_window = False

        router.first_message = MagicMock()
        router.first_message.on_recipient_speech_detected = AsyncMock()
        router.call.first_message_sent = False

        await router._on_recipient_started()

        router.first_message.on_recipient_speech_detected.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_output_suppression_during_echo_window(self):
        """echo window가 output_suppressed를 토글하지 않음."""
        router = _make_router()

        router.echo_gate._activate()

        assert router.echo_gate.in_echo_window is True
        # output_suppressed는 토글되지 않아야 함
        assert router.session_b.output_suppressed is not True


class TestSessionBOutputSuppression:
    """SessionB output_suppressed + pending output 큐 테스트."""

    def _make_handler(self) -> tuple[SessionBHandler, ActiveCall]:
        session_mock = MagicMock()
        session_mock.on = MagicMock()
        session_mock.create_response = AsyncMock()  # silence timeout 안전
        call = _make_call()
        handler = SessionBHandler(
            session=session_mock,
            call=call,
            on_translated_audio=AsyncMock(),
            on_caption=AsyncMock(),
            on_original_caption=AsyncMock(),
        )
        return handler, call

    @pytest.mark.asyncio
    async def test_audio_queued_when_suppressed(self):
        """억제 중 오디오가 큐에 저장됨."""
        handler, _ = self._make_handler()
        handler.output_suppressed = True

        audio_b64 = base64.b64encode(b"\x00\x01\x02").decode()
        await handler._handle_audio_delta({"delta": audio_b64})

        assert len(handler._pending_output) == 1
        assert handler._pending_output[0][0] == "audio"
        handler._on_translated_audio.assert_not_called()

    @pytest.mark.asyncio
    async def test_caption_queued_when_suppressed(self):
        """억제 중 캡션이 큐에 저장됨."""
        handler, _ = self._make_handler()
        handler.output_suppressed = True

        await handler._handle_transcript_delta({"delta": "번역 텍스트"})

        assert len(handler._pending_output) == 1
        assert handler._pending_output[0] == ("caption", ("recipient", "번역 텍스트"))
        handler._on_caption.assert_not_called()

    @pytest.mark.asyncio
    async def test_transcript_always_saved_during_suppression(self):
        """억제 중에도 transcript는 항상 저장됨."""
        handler, call = self._make_handler()
        handler.output_suppressed = True

        await handler._handle_transcript_done({"transcript": "번역 완료"})

        assert len(call.transcript_bilingual) == 1
        assert call.transcript_bilingual[0].original_text == "번역 완료"

    @pytest.mark.asyncio
    async def test_speech_started_fires_during_suppression(self):
        """억제 중에도 수신자 발화 시작 이벤트가 발생함."""
        handler, _ = self._make_handler()
        handler._on_recipient_speech_started = AsyncMock()
        handler.output_suppressed = True

        await handler._handle_speech_started({})

        assert handler.is_recipient_speaking is True
        handler._on_recipient_speech_started.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_pending_output(self):
        """flush_pending_output이 큐를 올바르게 배출함."""
        handler, _ = self._make_handler()
        handler.output_suppressed = True

        audio_b64 = base64.b64encode(b"\x00\x01").decode()
        await handler._handle_audio_delta({"delta": audio_b64})
        await handler._handle_transcript_delta({"delta": "텍스트"})

        assert len(handler._pending_output) == 2

        handler.output_suppressed = False
        await handler.flush_pending_output()

        assert len(handler._pending_output) == 0
        handler._on_translated_audio.assert_called_once()
        handler._on_caption.assert_called_once_with("recipient", "텍스트")

    @pytest.mark.asyncio
    async def test_original_caption_queued_when_suppressed(self):
        """억제 중 원문 캡션이 큐에 저장됨."""
        handler, _ = self._make_handler()
        handler.output_suppressed = True

        await handler._handle_input_transcription_completed({"transcript": "원문"})

        assert len(handler._pending_output) == 1
        assert handler._pending_output[0] == ("original_caption", ("recipient", "원문"))
        handler._on_original_caption.assert_not_called()

    def test_output_suppressed_toggle(self):
        """output_suppressed 프로퍼티 토글."""
        handler, _ = self._make_handler()
        assert handler.output_suppressed is False

        handler.output_suppressed = True
        assert handler.output_suppressed is True

        handler.output_suppressed = False
        assert handler.output_suppressed is False


class TestUlawRmsAndEnergyGate:
    """mu-law RMS 에너지 계산 + 오디오 에너지 게이트 테스트."""

    def test_ulaw_decode_table_silence(self):
        """mu-law 0xFF, 0x7F는 무음(0)으로 디코딩."""
        assert _ULAW_TO_LINEAR[0xFF] == 0
        assert _ULAW_TO_LINEAR[0x7F] == 0

    def test_ulaw_decode_table_range(self):
        """디코딩 테이블이 256개 엔트리를 가짐."""
        assert len(_ULAW_TO_LINEAR) == 256

    def test_ulaw_rms_silence(self):
        """무음 바이트(0xFF)의 RMS는 0."""
        silence = bytes([0xFF] * 160)
        assert _ulaw_rms(silence) == 0.0

    def test_ulaw_rms_empty(self):
        """빈 오디오의 RMS는 0."""
        assert _ulaw_rms(b"") == 0.0

    def test_ulaw_rms_loud_audio(self):
        """큰 소리 오디오는 높은 RMS 값."""
        loud = bytes([0x00] * 160)
        rms = _ulaw_rms(loud)
        assert rms > 1000

    def test_ulaw_rms_mixed(self):
        """혼합 오디오는 중간 RMS."""
        mixed = bytes([0xFF] * 80 + [0x00] * 80)
        rms = _ulaw_rms(mixed)
        assert 0 < rms < _ulaw_rms(bytes([0x00] * 160))

    @pytest.mark.asyncio
    async def test_energy_gate_drops_silence(self):
        """에너지 게이트 활성 시 무음 오디오가 드롭됨 (legacy Server VAD path)."""
        router = _make_router()
        router.session_b.send_recipient_audio = AsyncMock()

        silence = bytes([0xFF] * 160)

        with patch("src.realtime.pipeline.voice_to_voice.settings") as mock_settings:
            mock_settings.audio_energy_gate_enabled = True
            mock_settings.audio_energy_min_rms = 150.0
            await router.handle_twilio_audio(silence)

        # 무음은 드롭됨 (Local VAD 비활성 시 legacy path)
        router.session_b.send_recipient_audio.assert_not_called()

    @pytest.mark.asyncio
    async def test_energy_gate_passes_speech(self):
        """에너지 게이트 활성 시 발화 오디오는 Session B에 전달됨."""
        router = _make_router()
        router.session_b.send_recipient_audio = AsyncMock()

        speech = bytes([0x10] * 160)

        with patch("src.realtime.pipeline.voice_to_voice.settings") as mock_settings:
            mock_settings.audio_energy_gate_enabled = True
            mock_settings.audio_energy_min_rms = 150.0
            await router.handle_twilio_audio(speech)

        router.session_b.send_recipient_audio.assert_called_once()

    @pytest.mark.asyncio
    async def test_energy_gate_disabled_passes_all(self):
        """에너지 게이트 비활성 시 모든 오디오가 Session B에 전달됨."""
        router = _make_router()
        router.session_b.send_recipient_audio = AsyncMock()

        silence = bytes([0xFF] * 160)

        with patch("src.realtime.pipeline.voice_to_voice.settings") as mock_settings:
            mock_settings.audio_energy_gate_enabled = False
            await router.handle_twilio_audio(silence)

        router.session_b.send_recipient_audio.assert_called_once()


class TestEchoGateOnEvent:
    """EchoGateManager on_event 콜백 테스트 — PIPELINE_EVENT 전송 검증."""

    def _make_gate(self) -> tuple[EchoGateManager, list[tuple[str, str, dict]]]:
        """on_event 콜백이 연결된 EchoGateManager 생성."""
        events: list[tuple[str, str, dict]] = []

        async def on_event(stage: str, event: str, data: dict) -> None:
            events.append((stage, event, data))

        session_b = MagicMock()
        session_b.clear_input_buffer = AsyncMock()
        gate = EchoGateManager(
            session_b=session_b,
            local_vad=None,
            call_metrics=CallMetrics(),
            echo_margin_s=0.3,
            max_echo_window_s=1.0,
            on_event=on_event,
        )
        return gate, events

    @pytest.mark.asyncio
    async def test_activate_fires_event(self):
        """Echo window 활성화 시 'activate' 이벤트 발생."""
        gate, events = self._make_gate()
        gate._activate()
        await asyncio.sleep(0)  # let create_task run
        assert len(events) == 1
        assert events[0] == ("echo_gate", "activate", {})

    @pytest.mark.asyncio
    async def test_activate_fires_only_once(self):
        """이미 활성 상태에서 _activate() 재호출 시 이벤트 중복 발생하지 않음."""
        gate, events = self._make_gate()
        gate._activate()
        gate._activate()  # 중복 호출
        await asyncio.sleep(0)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_deactivate_fires_event(self):
        """Echo window 즉시 해제 시 'deactivate' 이벤트 발생."""
        gate, events = self._make_gate()
        gate._activate()
        await asyncio.sleep(0)
        events.clear()

        gate._deactivate()
        await asyncio.sleep(0)
        assert len(events) == 1
        assert events[0] == ("echo_gate", "deactivate", {})

    @pytest.mark.asyncio
    async def test_deactivate_not_fired_when_not_active(self):
        """비활성 상태에서 _deactivate() 호출 시 이벤트 발생하지 않음."""
        gate, events = self._make_gate()
        gate._deactivate()
        await asyncio.sleep(0)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_first_breakthrough_fires_echo_absorbed_event(self):
        """Echo window 중 첫 번째 고에너지 → 'echo_absorbed' 이벤트 발생."""
        gate, events = self._make_gate()
        gate._activate()
        await asyncio.sleep(0)
        events.clear()

        loud_audio = bytes([0x00] * 160)
        with patch("src.realtime.pipeline.echo_gate.settings") as mock_settings:
            mock_settings.echo_energy_threshold_rms = 400.0
            result = gate.filter_audio(loud_audio)
        await asyncio.sleep(0)

        stage_events = [e[1] for e in events]
        assert "echo_absorbed" in stage_events
        assert "breakthrough" not in stage_events
        assert result == b"\xff" * 160  # silence

    @pytest.mark.asyncio
    async def test_second_breakthrough_fires_event(self):
        """Echo window 중 두 번째 고에너지 → 'breakthrough' 이벤트 발생."""
        gate, events = self._make_gate()
        gate._activate()
        await asyncio.sleep(0)

        loud_audio = bytes([0x00] * 160)
        with patch("src.realtime.pipeline.echo_gate.settings") as mock_settings:
            mock_settings.echo_energy_threshold_rms = 400.0
            gate.filter_audio(loud_audio)  # 첫 번째: 흡수
            events.clear()
            result = gate.filter_audio(loud_audio)  # 두 번째: break
        await asyncio.sleep(0)

        stage_events = [e[1] for e in events]
        assert "breakthrough" in stage_events
        assert "deactivate" in stage_events
        bt_event = next(e for e in events if e[1] == "breakthrough")
        assert "rms" in bt_event[2]
        # 계약 변경(2026-07-19): 첫 돌파를 폐기하지 않고 보류했다가 진짜 발화로
        # 판별되면 함께 복원한다 — 폐기하면 인터럽트한 발화의 시작이 사라진다.
        assert result == loud_audio + loud_audio

    @pytest.mark.asyncio
    async def test_settling_start_fires_event(self):
        """Cooldown 완료 후 settling 시작 시 'settling_start' 이벤트 발생."""
        gate, events = self._make_gate()
        gate._tts_first_chunk_at = time.time()
        gate._tts_total_bytes = 160  # 짧은 TTS (0.02s)
        gate._activate()
        await asyncio.sleep(0)
        events.clear()

        with patch("src.realtime.pipeline.echo_gate.settings") as mock_settings:
            mock_settings.echo_settling_min_s = 0.1
            mock_settings.echo_settling_max_s = 0.5
            mock_settings.echo_settling_tts_ratio = 0.5
            gate._start_cooldown()
            # Cooldown: remaining(~0) + margin(0.3) = 0.3s, capped at 1.0
            await asyncio.sleep(0.5)

        stage_events = [e[1] for e in events]
        assert "settling_start" in stage_events
        settling_event = next(e for e in events if e[1] == "settling_start")
        assert "duration_s" in settling_event[2]

    @pytest.mark.asyncio
    async def test_settling_break_fires_event(self):
        """Settling 중 발화 감지 시 'settling_break' 이벤트 발생."""
        gate, events = self._make_gate()
        # settling 상태 강제 설정
        gate._settling_until = time.time() + 5.0
        gate._settling_started_at = time.time()
        gate._settling_broken = False

        await gate.break_settling()
        await asyncio.sleep(0)

        stage_events = [e[1] for e in events]
        assert "settling_break" in stage_events

    @pytest.mark.asyncio
    async def test_no_event_when_callback_is_none(self):
        """on_event=None일 때 이벤트 발생하지 않음 (기존 동작 보장)."""
        session_b = MagicMock()
        session_b.clear_input_buffer = AsyncMock()
        gate = EchoGateManager(
            session_b=session_b,
            local_vad=None,
            call_metrics=CallMetrics(),
        )
        # 에러 없이 실행되어야 함
        gate._activate()
        gate._deactivate()
        await asyncio.sleep(0)


class TestEchoGateDisabled:
    """echo_gate_enabled=False (핸드셋 모드) — 게이트가 오디오를 전혀 억제하지 않음."""

    def _make_gate(self, enabled: bool):
        session_b = MagicMock()
        session_b.clear_input_buffer = AsyncMock()
        return EchoGateManager(
            session_b=session_b,
            local_vad=None,
            call_metrics=CallMetrics(),
            echo_margin_s=0.3,
            max_echo_window_s=1.0,
            enabled=enabled,
        )

    def test_disabled_activate_does_not_open_window(self):
        """enabled=False면 _activate()가 echo window를 열지 않는다."""
        gate = self._make_gate(enabled=False)
        gate._activate()
        assert gate.in_echo_window is False
        assert gate.is_suppressing is False

    def test_disabled_filter_passes_loud_audio(self):
        """enabled=False면 activate 이후에도 고에너지 오디오가 그대로 통과(삭제 안 됨)."""
        gate = self._make_gate(enabled=False)
        gate._activate()  # no-op
        loud_audio = bytes([0x00] * 160)  # 고 RMS
        with patch("src.realtime.pipeline.echo_gate.settings") as mock_settings:
            mock_settings.echo_energy_threshold_rms = 400.0
            result = gate.filter_audio(loud_audio)
        assert result == loud_audio  # silence(0xFF)로 대체되지 않음

    @pytest.mark.asyncio
    async def test_disabled_on_tts_done_starts_no_settling(self):
        """enabled=False면 on_tts_done()이 cooldown/settling을 시작하지 않는다."""
        gate = self._make_gate(enabled=False)
        gate.on_tts_chunk(160)   # _activate no-op
        gate.on_tts_done()       # _start_cooldown 스킵
        await asyncio.sleep(0)
        assert gate.in_echo_window is False
        assert gate.is_suppressing is False
        assert gate.should_process_vad(10.0) is True  # VAD 항상 통과

    def test_enabled_control_absorbs_loud_audio(self):
        """대조군: enabled=True(기본)면 window 중 첫 고에너지는 흡수(silence)된다."""
        gate = self._make_gate(enabled=True)
        gate._activate()
        loud_audio = bytes([0x00] * 160)
        with patch("src.realtime.pipeline.echo_gate.settings") as mock_settings:
            mock_settings.echo_energy_threshold_rms = 400.0
            result = gate.filter_audio(loud_audio)
        assert result == b"\xff" * 160  # 흡수됨


class TestPreActivateProtectsRecipientSpeech:
    """진행 중인 수신자 발화를 pre_activate가 죽이지 않아야 한다.

    실측(2026-07-19 통화): 08:10:38 수신자 발화 시작 → 08:10:39 에코창 활성
    → 침묵 주입으로 발화가 잘려 그 통화의 수신자측 번역이 0건이었다.
    아직 보내지도 않은 TTS의 에코일 수 없으므로(인과적으로 불가능) 창을 열면 안 된다.
    """

    def _make_gate(self, vad_speaking: bool):
        session_b = MagicMock()
        session_b.clear_input_buffer = AsyncMock()
        local_vad = MagicMock()
        local_vad.is_speaking = vad_speaking
        return EchoGateManager(
            session_b=session_b,
            local_vad=local_vad,
            call_metrics=CallMetrics(),
            echo_margin_s=0.3,
            max_echo_window_s=1.0,
        )

    def test_skips_when_recipient_is_speaking(self):
        gate = self._make_gate(vad_speaking=True)
        gate.pre_activate()
        assert gate.in_echo_window is False
        assert gate.is_suppressing is False

    @pytest.mark.asyncio
    async def test_activates_when_recipient_is_silent(self):
        gate = self._make_gate(vad_speaking=False)
        gate.pre_activate()  # watchdog 태스크 생성 → 이벤트루프 필요
        assert gate.in_echo_window is True
        gate._pre_activate_timeout.cancel()

    @pytest.mark.asyncio
    async def test_activates_when_no_local_vad(self):
        """local_vad가 없는 구성(핸드셋 등)에서는 기존 동작을 유지한다."""
        session_b = MagicMock()
        session_b.clear_input_buffer = AsyncMock()
        gate = EchoGateManager(
            session_b=session_b,
            local_vad=None,
            call_metrics=CallMetrics(),
            echo_margin_s=0.3,
            max_echo_window_s=1.0,
        )
        gate.pre_activate()
        assert gate.in_echo_window is True
        gate._pre_activate_timeout.cancel()

    def test_is_speaking_is_a_property_on_real_localvad(self):
        """MagicMock만으로는 계약 변경을 못 잡는다.

        is_speaking이 속성에서 메서드로 바뀌면 실코드에서는 bound method가
        항상 truthy라 모든 pre_activate가 skip되어 에코 억제가 전면 무력화된다.
        """
        from src.realtime.local_vad import LocalVAD

        assert isinstance(LocalVAD.is_speaking, property)

    def test_timeout_defaults_to_setting(self):
        """TTS가 오지 않을 때 수신자를 막는 시간 — 설정값을 따른다."""
        from src.config import settings

        assert settings.echo_pre_activate_timeout_s <= 3.0, (
            "이 창이 열려 있는 동안 수신자 음성이 침묵으로 대체되므로 길면 안 된다"
        )


class TestTemporalInvariant:
    """에코창보다 먼저 시작된 발화는 억제하지 않는다 (인과적으로 에코일 수 없음).

    pre_activate의 skip은 '창을 아예 열지 않는' 빠른 경로일 뿐이라
    (a) 이미 열려 있는 창, (b) 판독 직후 시작된 발화를 막지 못한다.
    두 경우 모두 filter_audio의 시간 불변식이 프레임 단위로 처리한다.
    """

    def _make_gate(self, speech_started_at: float):
        session_b = MagicMock()
        session_b.clear_input_buffer = AsyncMock()
        local_vad = MagicMock()
        local_vad.speech_started_at = speech_started_at
        local_vad.is_speaking = speech_started_at > 0
        return EchoGateManager(
            session_b=session_b,
            local_vad=local_vad,
            call_metrics=CallMetrics(),
            echo_margin_s=0.3,
            max_echo_window_s=1.0,
        )

    def test_speech_started_before_window_passes_through(self):
        """TTS 재생 중 barge-in: 발화가 창보다 먼저 시작됐으면 원본 통과."""
        gate = self._make_gate(speech_started_at=time.time() - 1.0)
        gate._activate()  # 창이 나중에 열림
        quiet = b"\xff" * 160  # 저에너지 — 원래라면 침묵으로 대체될 프레임
        assert gate.filter_audio(quiet) == quiet
        loud = bytes([0x00] * 160)
        assert gate.filter_audio(loud) == loud  # 첫 돌파 흡수 로직도 타지 않는다

    def test_speech_started_after_window_is_suppressed(self):
        """창이 열린 뒤 감지된 소리는 에코일 수 있으므로 기존 억제 경로를 탄다."""
        gate = self._make_gate(speech_started_at=0.0)
        gate._activate()
        gate._local_vad.speech_started_at = time.time()  # 창 이후 시작
        quiet = b"\xff" * 160
        assert gate.filter_audio(quiet) == b"\xff" * 160

    def test_no_speech_is_suppressed_normally(self):
        gate = self._make_gate(speech_started_at=0.0)
        gate._activate()
        quiet = bytes([0x7F] * 160)
        assert gate.filter_audio(quiet) == b"\xff" * len(quiet)

    def test_window_reopen_resets_reference_time(self):
        """창이 새로 열리면 기준 시각도 갱신 — 이전 창 기준으로 통과시키면 안 된다."""
        gate = self._make_gate(speech_started_at=0.0)
        gate._activate()
        first_open = gate._echo_window_opened_at
        gate._in_echo_window = False
        time.sleep(0.01)
        gate._activate()
        assert gate._echo_window_opened_at > first_open


class TestVadNotFrozenDuringEchoWindow:
    """echo window가 VAD 상태를 얼려 speech_stopped을 막지 않아야 한다.

    실측(2026-07-19): 08:55:45 발화 시작 → 창 반복 개방으로 VAD가 SPEAKING에
    고정 → 08:56:00 "VAD stuck" 15초 타임아웃 → 빈 버퍼 커밋 오류 →
    그 턴 e2e 17,982ms. 억제 지점 세 곳(filter_audio / is_suppressing /
    should_process_vad)이 같은 불변식을 봐야 한다.
    """

    def _make_gate(self, speech_started_at: float):
        session_b = MagicMock()
        session_b.clear_input_buffer = AsyncMock()
        local_vad = MagicMock()
        local_vad.speech_started_at = speech_started_at
        local_vad.is_speaking = speech_started_at > 0
        return EchoGateManager(
            session_b=session_b,
            local_vad=local_vad,
            call_metrics=CallMetrics(),
            echo_margin_s=0.3,
            max_echo_window_s=1.0,
        )

    def test_vad_keeps_processing_when_speech_predates_window(self):
        """진행 중이던 발화는 창 안에서도 VAD 처리가 계속돼야 종료를 감지한다."""
        gate = self._make_gate(speech_started_at=time.time() - 1.0)
        gate._activate()
        assert gate.should_process_vad(50.0) is True

    def test_vad_suppressed_when_speech_starts_after_window(self):
        """창 이후 감지된 소리는 에코일 수 있으므로 기존 억제를 유지한다."""
        gate = self._make_gate(speech_started_at=0.0)
        gate._activate()
        gate._local_vad.speech_started_at = time.time()
        assert gate.should_process_vad(50.0) is False

    def test_all_three_suppression_points_agree(self):
        """세 경로가 같은 판정을 내야 한다 — 하나만 어긋나면 수정이 무효화된다."""
        gate = self._make_gate(speech_started_at=time.time() - 1.0)
        gate._activate()
        audio = b"\xfe" * 160
        assert gate.should_process_vad(50.0) is True      # VAD 처리 계속
        assert gate.is_suppressing is False               # 파이프라인 통과
        assert gate.filter_audio(audio) == audio          # 원본 전달

    def test_preexisting_exemption_expires(self):
        """VAD가 stuck이어도 면제가 무한히 이어지면 안 된다 (에코 억제 복귀)."""
        from src.config import settings

        gate = self._make_gate(
            speech_started_at=time.time() - (settings.echo_preexisting_speech_max_s + 1)
        )
        gate._activate()
        assert gate.should_process_vad(50.0) is False
        assert gate.is_suppressing is True


class TestBargeInOnsetPreserved:
    """인터럽트한 발화의 시작 부분이 사라지지 않아야 한다.

    기존 로직은 echo window 중 첫 고에너지 프레임을 'PSTN 에코겠지' 하고 폐기했다.
    에코라면 맞지만, 진짜로 끼어든 발화라면 그 시작이 통째로 사라진다.
    실측(2026-07-19 통화): 4회 폐기, 사용자 보고 "인터럽트하면 그 내용이 아예
    안 들린다". 요약의 interrupts=0은 오디오가 버려져 인식조차 못 한 결과다.
    """

    def _make_gate(self):
        session_b = MagicMock()
        session_b.clear_input_buffer = AsyncMock()
        return EchoGateManager(
            session_b=session_b,
            local_vad=None,
            call_metrics=CallMetrics(),
            echo_margin_s=0.3,
            max_echo_window_s=1.0,
        )

    def test_onset_is_restored_when_speech_continues(self):
        """연속 고에너지 = 진짜 발화 → 보류했던 시작 부분을 함께 내보낸다."""
        gate = self._make_gate()
        gate._activate()
        onset = bytes([0x00] * 160)   # 고에너지 (발화 시작)
        second = bytes([0x01] * 160)  # 고에너지 (계속)

        assert gate.filter_audio(onset) == b"\xff" * 160  # 1프레임은 보류(아직 미판별)
        out = gate.filter_audio(second)
        assert out == onset + second, "인터럽트 시작 부분이 복원돼야 한다"

    def test_onset_is_dropped_when_it_was_echo(self):
        """돌파 후 조용해짐 = 에코였다 → 보류분 폐기(에코 누출 방지)."""
        gate = self._make_gate()
        gate._activate()
        gate.filter_audio(bytes([0x00] * 160))     # 보류
        quiet = bytes([0x7F] * 160)                 # 저에너지
        assert gate.filter_audio(quiet) == b"\xff" * 160
        assert gate._held_onset == b""

    def test_new_window_clears_stale_onset(self):
        """창이 새로 열리면 이전 보류분은 폐기한다 (다른 발화에 섞이면 안 됨)."""
        gate = self._make_gate()
        gate._activate()
        gate.filter_audio(bytes([0x00] * 160))
        assert gate._held_onset != b""
        gate._in_echo_window = False
        gate._activate()
        assert gate._held_onset == b""
