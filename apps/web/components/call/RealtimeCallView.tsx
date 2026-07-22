'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Bot, MessageSquare, Mic, MicOff, PhoneOff, Send } from 'lucide-react';
import type { CallMode, CommunicationMode } from '@/shared/call-types';
import { useRelayCall } from '@/hooks/useRelayCall';
import CallStatusBar from './CallStatusBar';
import LiveCaptionPanel from './LiveCaptionPanel';
import VoiceSignal from './VoiceSignal';

interface RealtimeCallViewProps {
  callId: string;
  relayWsUrl: string;
  callMode: CallMode;
  communicationMode?: CommunicationMode;
  targetName?: string | null;
  onCallEnd?: () => void;
  wsProtocols?: string[];
  refreshWsProtocols?: () => Promise<string[]>;
  showRemoteSpeakingEffect?: boolean;
}

const modeBadgeIcon: Record<CommunicationMode, typeof Mic> = {
  voice_to_voice: Mic,
  text_to_voice: MessageSquare,
  full_agent: Bot,
};

const COMM_MODE_KEYS: Record<CommunicationMode, string> = {
  voice_to_voice: 'voiceToVoice',
  text_to_voice: 'textToVoice',
  full_agent: 'fullAgent',
};

export default function RealtimeCallView({
  callId,
  relayWsUrl,
  callMode,
  communicationMode = 'voice_to_voice',
  targetName,
  onCallEnd,
  wsProtocols,
  refreshWsProtocols,
  showRemoteSpeakingEffect = false,
}: RealtimeCallViewProps) {
  const t = useTranslations('call');
  const relay = useRelayCall(communicationMode, wsProtocols, refreshWsProtocols);
  const startCall = relay.startCall;
  const [textInput, setTextInput] = useState('');
  const endedRef = useRef(false);
  const lastTextActionRef = useRef<{ value: string; at: number } | null>(null);

  const BadgeIcon = modeBadgeIcon[communicationMode];
  const badgeLabel = t(`modeBadge.${COMM_MODE_KEYS[communicationMode]}`);
  const showRecipientSpeaking = showRemoteSpeakingEffect && relay.isRecipientSpeaking;
  const isActive = relay.callStatus !== 'ended';

  useEffect(() => {
    endedRef.current = false;
    startCall(callId, relayWsUrl, callMode);
  }, [callId, relayWsUrl, callMode, startCall]);

  const handleEndCall = useCallback(() => {
    if (endedRef.current) return;
    endedRef.current = true;
    relay.endCall();
    onCallEnd?.();
  }, [relay, onCallEnd]);

  const handleSendText = useCallback((text?: string) => {
    const message = text ?? textInput.trim();
    if (!message) return;
    const now = Date.now();
    const last = lastTextActionRef.current;
    if (last?.value === message && now - last.at < 500) return;
    lastTextActionRef.current = { value: message, at: now };
    relay.sendText(message);
    setTextInput('');
  }, [textInput, relay]);

  const handleKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      handleSendText();
    }
  }, [handleSendText]);

  const quickReplies = [
    { label: t('quickReplyYes'), value: t('quickReplyYesValue') },
    { label: t('quickReplyNo'), value: t('quickReplyNoValue') },
    { label: t('quickReplyWait'), value: t('quickReplyWaitValue') },
    { label: t('quickReplyRepeat'), value: t('quickReplyRepeatValue') },
  ];

  const signalState = (() => {
    if (showRecipientSpeaking) {
      return { active: true, tone: 'purple' as const, label: t('recipientSpeaking'), hint: t('recipientSpeakingHint') };
    }
    if (relay.isMuted) {
      return { active: false, tone: 'neutral' as const, label: t('muted'), hint: t('mutedHint') };
    }
    if (relay.isRecording) {
      return { active: true, tone: 'green' as const, label: t('speaking'), hint: t('operatorSpeakingHint') };
    }
    if (communicationMode === 'full_agent') {
      return { active: relay.isPlaying, tone: 'purple' as const, label: t('aiHandling'), hint: t('aiHandlingHint') };
    }
    return { active: relay.isPlaying, tone: 'purple' as const, label: t('listening'), hint: t('listeningHint') };
  })();

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-[#E4E1E6] bg-white">
      <CallStatusBar
        callStatus={relay.callStatus}
        callDuration={relay.callDuration}
        targetName={targetName}
        callMode={callMode}
      />

      <div className="flex min-h-[62px] items-center justify-between gap-3 border-b border-[#E4E1E6] bg-[#FBFAFC] px-4 sm:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-[#F3EEF9] text-[#6B2EAA]">
            <BadgeIcon className="size-4" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-xs font-bold text-[#211D24]">{badgeLabel}</p>
            <p className="mt-0.5 truncate text-[11px] text-[#706A73]">{signalState.hint}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3" role="status" aria-live="polite">
          <div className="hidden text-right sm:block">
            <p className="text-xs font-bold text-[#51327E]">{signalState.label}</p>
          </div>
          <VoiceSignal active={signalState.active} tone={signalState.tone} compact />
        </div>
      </div>

      {relay.error && (
        <div className="border-b border-[#EECACA] bg-[#FAECEB] px-4 py-2 text-xs text-[#A83C3C]">{relay.error}</div>
      )}

      <div className="min-h-0 flex-1">
        <LiveCaptionPanel captions={relay.captions} translationState={relay.translationState} expanded />
      </div>

      {isActive && communicationMode === 'text_to_voice' && (
        <div className="shrink-0 border-t border-[#E4E1E6] bg-white">
          <div className="flex gap-2 overflow-x-auto px-4 py-2.5">
            {quickReplies.map((reply) => (
              <button
                key={reply.label}
                type="button"
                onClick={() => handleSendText(reply.value)}
                className="shrink-0 rounded-full border border-[#E4E1E6] bg-[#F8F7F9] px-3 py-1.5 text-xs font-semibold text-[#5E5861] transition-colors hover:border-[#D8C9EA] hover:bg-[#F3EEF9] hover:text-[#6B2EAA]"
              >
                {reply.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 border-t border-[#EEEAEF] px-4 py-3">
            <input
              type="text"
              value={textInput}
              onChange={(event) => setTextInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('sendMessage')}
              className="h-11 min-w-0 flex-1 rounded-[9px] border border-[#D1CCD4] bg-white px-3 text-base text-[#211D24] outline-none placeholder:text-[#9A939E] focus:border-[#9B51E0] focus:ring-3 focus:ring-[#F3EEF9] md:text-sm"
            />
            <button
              type="button"
              onClick={() => handleSendText()}
              disabled={!textInput.trim()}
              className="grid size-11 shrink-0 place-items-center rounded-[9px] bg-[#6B2EAA] text-white transition-colors hover:bg-[#51327E] disabled:bg-[#D8D3DA]"
              aria-label={t('sendMessage')}
            >
              <Send className="size-4" />
            </button>
          </div>
        </div>
      )}

      {isActive && communicationMode === 'full_agent' && (
        <div className="shrink-0 border-t border-[#E4E1E6] bg-[#FBFAFC] px-4 py-2 text-center text-xs text-[#706A73]">
          {t('aiNoIntervention')}
        </div>
      )}

      {isActive && (
        <div className="flex shrink-0 items-center gap-2 border-t border-[#E4E1E6] bg-white px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))]">
          {communicationMode === 'voice_to_voice' && (
            <button
              type="button"
              onClick={relay.toggleMute}
              className={`inline-flex h-11 items-center gap-2 rounded-[9px] border px-3 text-xs font-bold transition-colors sm:px-4 ${
                relay.isMuted
                  ? 'border-[#EECACA] bg-[#FAECEB] text-[#A83C3C] hover:bg-[#F6DEDC]'
                  : 'border-[#D1CCD4] bg-white text-[#5E5861] hover:border-[#D8C9EA] hover:bg-[#F3EEF9] hover:text-[#6B2EAA]'
              }`}
            >
              {relay.isMuted ? <MicOff className="size-4" /> : <Mic className="size-4" />}
              {relay.isMuted ? t('unmute') : t('mute')}
            </button>
          )}
          <button
            type="button"
            onClick={handleEndCall}
            className="ml-auto inline-flex h-11 min-w-32 items-center justify-center gap-2 rounded-[9px] border border-[#A83C3C] bg-[#A83C3C] px-4 text-sm font-bold text-white transition-colors hover:border-[#8F3030] hover:bg-[#8F3030]"
          >
            <PhoneOff className="size-4" />
            {t('endCall')}
          </button>
        </div>
      )}
    </div>
  );
}
