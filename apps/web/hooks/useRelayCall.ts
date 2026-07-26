'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  WsMessageType,
  getModeUIConfig,
  type CallMode,
  type CaptionEntry,
  type CommunicationMode,
  type RelayWsMessage,
} from '@/shared/call-types';
import { useRelayWebSocket } from './useRelayWebSocket';
import { useClientVad } from './useClientVad';
import { useWebAudioPlayer } from './useWebAudioPlayer';
import { useRelayCallStore, type CallMetrics, type EventLogEntry } from './useRelayCallStore';

// --- Pipeline Event Log helpers (module scope for stable reference) ---
const PIPELINE_STAGE_TAG_MAP: Record<string, { tag: string; color: string }> = {
  echo_gate: { tag: 'Echo Gate', color: 'text-orange-400' },
  energy_gate: { tag: 'Energy Gate', color: 'text-cyan-400' },
  silero_vad: { tag: 'Silero VAD', color: 'text-violet-400' },
};

function pushEventLog(entry: Omit<EventLogEntry, 'id' | 'timestamp'>) {
  useRelayCallStore.getState().addEventLog(entry);
}

type CallStatus = 'idle' | 'connecting' | 'waiting' | 'connected' | 'ended';
type TranslationState = 'idle' | 'processing' | 'done';

interface ActiveCaptionTurn {
  id: string;
  speaker: CaptionEntry['speaker'];
  hasOriginal: boolean;
}

function appendOriginalText(current: string | undefined, next: string): string {
  if (!current) return next;
  if (current.endsWith(' ') || next.startsWith(' ')) return current + next;
  return `${current} ${next}`;
}

interface UseRelayCallReturn {
  callStatus: CallStatus;
  translationState: TranslationState;
  captions: CaptionEntry[];
  callDuration: number;
  callMode: CallMode;
  startCall: (callId: string, relayWsUrl: string, mode: CallMode) => void;
  endCall: () => void;
  sendText: (text: string) => void;
  sendTypingState: () => void;
  toggleMute: () => void;
  isMuted: boolean;
  isRecording: boolean;
  isRecipientSpeaking: boolean;
  isPlaying: boolean;
  error: string | null;
}

export function useRelayCall(
  communicationMode: CommunicationMode = 'voice_to_voice',
  wsProtocols?: string[],
  refreshWsProtocols?: () => Promise<string[]>,
): UseRelayCallReturn {
  const [callStatus, setCallStatus] = useState<CallStatus>('idle');
  const [translationState, setTranslationState] = useState<TranslationState>('idle');
  const [captions, setCaptions] = useState<CaptionEntry[]>([]);
  const [callDuration, setCallDuration] = useState(0);
  const [callMode, setCallMode] = useState<CallMode>('agent');
  const [isMuted, setIsMuted] = useState(false);
  const [isRecipientSpeaking, setIsRecipientSpeaking] = useState(false);
  const [wsUrl, setWsUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const durationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recipientSpeakingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const userSpeakingRef = useRef(false);
  const wsRef = useRef<{ disconnect: () => void } | null>(null);

  // Mode UI config
  const modeConfig = getModeUIConfig(communicationMode);

  // Audio player
  const player = useWebAudioPlayer();

  // Caption counter for unique IDs
  const captionCounterRef = useRef(0);

  // 한 발화의 원문과 번역문은 도착 순서와 관계없이 같은 버블에 합친다.
  const outboundTurnRef = useRef<ActiveCaptionTurn | null>(null);
  const inboundTurnRef = useRef<ActiveCaptionTurn | null>(null);
  const localTurnPendingRef = useRef(false);

  const stopRecipientSpeaking = useCallback(() => {
    if (recipientSpeakingTimerRef.current) {
      clearTimeout(recipientSpeakingTimerRef.current);
      recipientSpeakingTimerRef.current = null;
    }
    setIsRecipientSpeaking(false);
  }, []);

  const markRecipientSpeaking = useCallback(() => {
    if (recipientSpeakingTimerRef.current) {
      clearTimeout(recipientSpeakingTimerRef.current);
    }
    setIsRecipientSpeaking(true);
    // Safety reset in case a speech_end event is lost during a reconnect.
    recipientSpeakingTimerRef.current = setTimeout(() => {
      recipientSpeakingTimerRef.current = null;
      setIsRecipientSpeaking(false);
    }, 10_000);
  }, []);

  // Handle incoming WS messages
  const handleMessage = useCallback(
    (msg: RelayWsMessage) => {
      switch (msg.type) {
        case WsMessageType.CAPTION:
        case WsMessageType.CAPTION_ORIGINAL:
        case WsMessageType.CAPTION_TRANSLATED: {
          const stage = msg.type === WsMessageType.CAPTION_ORIGINAL ? 1
            : msg.type === WsMessageType.CAPTION_TRANSLATED ? 2
            : (msg.data.stage as 1 | 2 | undefined);

          const rawRole = (msg.data.role as string) ?? (msg.data.speaker as string) ?? 'recipient';
          const ROLE_TO_SPEAKER: Record<string, CaptionEntry['speaker']> = {
            assistant: 'ai', user: 'user', recipient: 'recipient', ai: 'ai',
          };
          const speaker: CaptionEntry['speaker'] = ROLE_TO_SPEAKER[rawRole] ?? 'recipient';
          const rawDirection = (msg.data.direction as string) ?? 'unknown';
          const direction = rawDirection === 'inbound' || rawDirection === 'outbound'
            ? rawDirection
            : speaker === 'recipient' ? 'inbound' : 'outbound';
          const text = (msg.data.text as string) ?? '';
          if (!text) break;

          const isOriginal = stage === 1
            || (direction === 'outbound' && rawRole === 'user');
          const turnRef = direction === 'inbound' ? inboundTurnRef : outboundTurnRef;

          let turnSpeaker: CaptionEntry['speaker'];
          if (direction === 'inbound') {
            turnSpeaker = 'recipient';
          } else if (communicationMode === 'full_agent') {
            turnSpeaker = rawRole === 'user' ? 'user' : 'ai';
          } else if (
            rawRole === 'user'
            || localTurnPendingRef.current
            || turnRef.current?.speaker === 'user'
          ) {
            // 직접 통화에서 Session A의 assistant 캡션은 내 발화의 번역문이다.
            turnSpeaker = 'user';
          } else {
            // 로컬 발화 없이 시작된 첫 안내 등 시스템 생성 발화만 AI로 표시한다.
            turnSpeaker = 'ai';
          }

          const canReclassifyAiTurn =
            direction === 'outbound'
            && turnRef.current?.speaker === 'ai'
            && turnSpeaker === 'user'
            && localTurnPendingRef.current;

          if (
            !turnRef.current
            || (turnRef.current.speaker !== turnSpeaker && !canReclassifyAiTurn)
          ) {
            captionCounterRef.current += 1;
            const id = `caption-${captionCounterRef.current}`;
            const newTurn: ActiveCaptionTurn = {
              id,
              speaker: turnSpeaker,
              hasOriginal: isOriginal,
            };
            turnRef.current = newTurn;
            const entry: CaptionEntry = {
              id,
              speaker: turnSpeaker,
              text: isOriginal ? '' : text,
              originalText: isOriginal ? text : undefined,
              language: (msg.data.language as string) ?? '',
              isFinal: false,
              timestamp: Date.now(),
              stage: isOriginal ? 1 : 2,
            };
            setCaptions((prev) => [...prev, entry]);
            break;
          }

          if (canReclassifyAiTurn && turnRef.current) {
            turnRef.current = { ...turnRef.current, speaker: 'user' };
          }
          if (isOriginal && turnRef.current) {
            turnRef.current = { ...turnRef.current, hasOriginal: true };
          }

          const activeTurn = turnRef.current;
          if (!activeTurn) break;

          setCaptions((prev) => prev.map((entry) => {
            if (entry.id !== activeTurn.id) return entry;
            const nextOriginal = isOriginal
              ? appendOriginalText(entry.originalText, text)
              : entry.originalText;
            const nextText = isOriginal ? entry.text : entry.text + text;
            return {
              ...entry,
              speaker: activeTurn.speaker,
              text: nextText,
              originalText: nextOriginal,
              language: (msg.data.language as string) || entry.language,
              stage: nextText ? 2 : 1,
            };
          }));
          break;
        }

        case WsMessageType.RECIPIENT_AUDIO: {
          // audioOutput이 false인 모드: 수신자 음성은 재생하지 않음
          if (!modeConfig.audioOutput) break;
          const audio = msg.data.audio as string;
          if (audio) {
            player.play(audio);
          }
          break;
        }

        case WsMessageType.CALL_STATUS: {
          const status = (msg.data.status as string) ?? (msg.data.message as string);
          pushEventLog({ tag: 'Call', message: status ?? 'unknown', color: 'text-blue-400' });
          if (status === 'ringing' || status === 'waiting') {
            setCallStatus('waiting');
          } else if (status === 'connected' || status === 'in-progress') {
            setCallStatus('connected');
          } else if (status === 'ended' || status === 'completed' || status === 'failed') {
            setCallStatus('ended');
            stopRecipientSpeaking();
            // Server confirmed call ended — clean up resources
            player.stop();
            if (durationTimerRef.current) {
              clearInterval(durationTimerRef.current);
              durationTimerRef.current = null;
            }
            // Delay disconnect so any final messages can arrive
            setTimeout(() => {
              wsRef.current?.disconnect();
              setWsUrl(null);
            }, 300);
          }
          break;
        }

        case WsMessageType.TRANSLATION_STATE: {
          const state = msg.data.state as string;
          if (state === 'processing' || state === 'done' || state === 'caption_done') {
            pushEventLog({ tag: 'Session A', message: state, color: 'text-green-400' });
          }
          if (state === 'caption_done') {
            // 원문이 늦게 도착할 수 있어 번역만 있는 턴은 다음 speech_start까지 유지한다.
            if (inboundTurnRef.current?.hasOriginal) {
              inboundTurnRef.current = null;
            }
          } else if (state === 'done') {
            // 시스템 안내/완성된 로컬 턴은 닫고, 원문 지연 중인 로컬 턴만 잠시 유지한다.
            if (
              outboundTurnRef.current?.speaker === 'ai'
              || outboundTurnRef.current?.hasOriginal
            ) {
              outboundTurnRef.current = null;
            }
            localTurnPendingRef.current = false;
            setTranslationState('done');
          } else if (state) {
            setTranslationState(state as TranslationState);
          }
          break;
        }

        case WsMessageType.INTERRUPT_ALERT: {
          pushEventLog({ tag: 'Interrupt', message: 'Recipient speaking', color: 'text-red-400' });
          markRecipientSpeaking();
          // Clear playback queue when recipient is speaking
          player.clearQueue();
          break;
        }

        case WsMessageType.METRICS:
          useRelayCallStore.getState().syncState({ metrics: msg.data as unknown as CallMetrics });
          break;

        case WsMessageType.GUARDRAIL_TRIGGERED: {
          const level = (msg.data.level as string) ?? '';
          pushEventLog({ tag: 'Guardrail', message: `L${level} triggered`, color: 'text-yellow-400' });
          break;
        }

        case WsMessageType.SESSION_RECOVERY: {
          const recoveryType = (msg.data.type as string) ?? 'unknown';
          pushEventLog({ tag: 'Recovery', message: recoveryType, color: 'text-cyan-400' });
          break;
        }

        case WsMessageType.PIPELINE_EVENT: {
          const stage = msg.data.stage as string;
          const event = msg.data.event as string;
          if (stage === 'silero_vad') {
            if (event === 'speech_start') {
              inboundTurnRef.current = null;
              markRecipientSpeaking();
            } else if (event === 'speech_end') {
              stopRecipientSpeaking();
            }
          }
          const { tag, color } = PIPELINE_STAGE_TAG_MAP[stage] ?? { tag: stage, color: 'text-gray-400' };
          const rms = msg.data.rms != null ? ` (RMS: ${msg.data.rms})` : '';
          const peakRms = msg.data.peak_rms != null ? ` (peak: ${msg.data.peak_rms})` : '';
          const extra = msg.data.duration_s != null ? ` ${(msg.data.duration_s as number).toFixed(1)}s` : '';
          const totalS = msg.data.total_s != null ? ` ${(msg.data.total_s as number).toFixed(1)}s` : '';
          pushEventLog({ tag, message: `${event}${rms}${peakRms}${extra}${totalS}`, color });
          break;
        }

        case WsMessageType.ERROR: {
          const message = (msg.data.message as string) ?? 'Unknown error';
          setError(message);
          break;
        }

        default:
          break;
      }
    },
    [player, modeConfig.audioOutput, communicationMode, markRecipientSpeaking, stopRecipientSpeaking],
  );

  // WebSocket connection
  const ws = useRelayWebSocket({
    url: wsUrl,
    onMessage: handleMessage,
    autoConnect: true,
    protocols: wsProtocols,
    refreshProtocols: refreshWsProtocols,
  });
  useEffect(() => {
    wsRef.current = ws;
  }, [ws]);

  // Update callStatus when ws connects
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (ws.status === 'connected' && callStatus === 'connecting') {
        setCallStatus('waiting');
      } else if (ws.status === 'error') {
        setError('WebSocket connection failed');
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [ws.status, callStatus]);

  // Client VAD — active only when audioInput is enabled and not muted
  const vadEnabled = modeConfig.audioInput && !isMuted && wsUrl !== null && ws.status === 'connected';

  const { isSpeaking } = useClientVad({
    onSpeechAudio: (base64Audio: string) => {
      if (!userSpeakingRef.current) {
        userSpeakingRef.current = true;
        outboundTurnRef.current = null;
        localTurnPendingRef.current = true;
        player.stop();
      }
      ws.sendAudioChunk(base64Audio);
    },
    onSpeechCommitted: () => {
      userSpeakingRef.current = false;
      ws.sendVadState('committed');
    },
    enabled: vadEnabled,
  });

  // Call duration timer
  useEffect(() => {
    if (callStatus === 'connected') {
      durationTimerRef.current = setInterval(() => {
        setCallDuration((prev) => prev + 1);
      }, 1000);
    }

    return () => {
      if (durationTimerRef.current) {
        clearInterval(durationTimerRef.current);
        durationTimerRef.current = null;
      }
    };
  }, [callStatus]);

  const startCall = useCallback(
    (callId: string, relayWsUrl: string, mode: CallMode) => {
      setCallMode(mode);
      setCallStatus('connecting');
      setCaptions([]);
      setCallDuration(0);
      setError(null);
      setTranslationState('idle');
      setIsMuted(false);
      stopRecipientSpeaking();
      captionCounterRef.current = 0;
      outboundTurnRef.current = null;
      inboundTurnRef.current = null;
      localTurnPendingRef.current = false;
      setWsUrl(relayWsUrl);
    },
    [stopRecipientSpeaking],
  );

  const endCall = useCallback(() => {
    // Send END_CALL first, then wait briefly before disconnecting
    // to ensure the message is delivered to the relay server.
    const sent = ws.sendEndCall();
    player.stop();
    setCallStatus('ended');
    stopRecipientSpeaking();

    if (durationTimerRef.current) {
      clearInterval(durationTimerRef.current);
      durationTimerRef.current = null;
    }

    if (sent) {
      // Give the server time to receive END_CALL and process Twilio hangup
      setTimeout(() => {
        ws.disconnect();
        setWsUrl(null);
      }, 500);
    } else {
      // WebSocket was not open — disconnect immediately
      ws.disconnect();
      setWsUrl(null);
    }
  }, [ws, player, stopRecipientSpeaking]);

  const sendText = useCallback(
    (text: string) => {
      outboundTurnRef.current = null;
      localTurnPendingRef.current = true;
      ws.sendText(text);
      // 낙관적 로컬 캡션은 추가하지 않는다. relay가 입력 텍스트를 outbound 'user' 캡션으로
      // 에코하므로(보투보의 STT 캡션과 동일 경로), 로컬까지 넣으면 발신자 화면에 중복 표시된다.
    },
    [ws],
  );

  const sendTypingState = useCallback(() => {
    ws.sendTypingState();
  }, [ws]);

  const toggleMute = useCallback(() => {
    setIsMuted((prev) => !prev);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (durationTimerRef.current) {
        clearInterval(durationTimerRef.current);
      }
      if (recipientSpeakingTimerRef.current) {
        clearTimeout(recipientSpeakingTimerRef.current);
      }
    };
  }, []);

  return {
    callStatus,
    translationState,
    captions,
    callDuration,
    callMode,
    startCall,
    endCall,
    sendText,
    sendTypingState,
    toggleMute,
    isMuted,
    isRecording: vadEnabled && isSpeaking,
    isRecipientSpeaking,
    isPlaying: player.isPlaying,
    error,
  };
}
