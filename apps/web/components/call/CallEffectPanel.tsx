'use client';

import { useCallback, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { Bot, Loader2, MessageSquare, Mic, MicOff, PhoneOff } from 'lucide-react';
import { useRelayCallStore } from '@/hooks/useRelayCallStore';
import { useDashboard } from '@/hooks/useDashboard';
import CallingStatus from './CallingStatus';
import CallStatusBar from './CallStatusBar';
import CallSummaryPanel from './CallSummaryPanel';
import VoiceSignal from './VoiceSignal';
import type { CommunicationMode } from '@/shared/call-types';
import { isDemoMode } from '@/lib/demo';

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

export default function CallEffectPanel() {
  const t = useTranslations('call');
  const tc = useTranslations('common');
  const { callingCommunicationMode, resetDashboard } = useDashboard();
  const {
    callData: call,
    callDataLoading: loading,
    callDataError: pollError,
    refetchCallData,
    callStatus,
    callDuration,
    callMode,
    isMuted,
    isRecording,
    isRecipientSpeaking,
    isPlaying,
    error,
    endCall,
    toggleMute,
  } = useRelayCallStore();

  const prevCallStatusRef = useRef(callStatus);
  useEffect(() => {
    if (callStatus === 'ended' && prevCallStatusRef.current !== 'ended') refetchCallData?.();
    prevCallStatusRef.current = callStatus;
  }, [callStatus, refetchCallData]);

  const communicationMode = callingCommunicationMode ?? 'voice_to_voice';
  const BadgeIcon = modeBadgeIcon[communicationMode];
  const badgeLabel = t(`modeBadge.${COMM_MODE_KEYS[communicationMode]}`);

  const handleNewChat = useCallback(() => {
    localStorage.removeItem('currentConversationId');
    localStorage.removeItem('currentCommunicationMode');
    localStorage.removeItem('currentSourceLang');
    localStorage.removeItem('currentTargetLang');
    resetDashboard();
    window.location.href = '/outbound';
  }, [resetDashboard]);

  const demoModeActive = isDemoMode();
  const isRealtimeMode = demoModeActive || call?.callMode === 'agent' || call?.callMode === 'relay';
  const hasRelayWsUrl = demoModeActive || Boolean(call?.relayWsUrl);

  if (!isRealtimeMode || !hasRelayWsUrl) {
    if (loading && !call) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3">
          <Loader2 className="size-6 animate-spin text-[#6B2EAA]" />
          <p className="text-sm text-[#706A73]">{t('loadingCallInfo')}</p>
        </div>
      );
    }
    if (pollError) {
      return (
        <div className="flex h-full items-center justify-center px-6 text-center">
          <div>
            <p className="mb-3 text-sm text-[#A83C3C]">{pollError}</p>
            <button type="button" onClick={() => window.location.reload()} className="text-sm font-semibold text-[#6B2EAA] underline">{tc('retry')}</button>
          </div>
        </div>
      );
    }
    return <div className="flex h-full items-center justify-center"><CallingStatus call={call} elapsed={callDuration} /></div>;
  }

  const isTerminal = !demoModeActive && (call?.status === 'COMPLETED' || call?.status === 'FAILED');
  const endedAtBootstrap = demoModeActive && callStatus === 'ended' && callDuration === 0;
  const isActive = (callStatus !== 'ended' || endedAtBootstrap) && !isTerminal;
  const isEnded = !endedAtBootstrap && (callStatus === 'ended' || isTerminal);

  if (isEnded && call) return <CallSummaryPanel call={call} onNewChat={handleNewChat} />;

  const state = (() => {
    if (isRecipientSpeaking) return { label: t('recipientSpeaking'), hint: t('recipientSpeakingHint'), active: true, tone: 'purple' as const };
    if (isMuted) return { label: t('muted'), hint: t('mutedHint'), active: false, tone: 'neutral' as const };
    if (isRecording) return { label: t('speaking'), hint: t('operatorSpeakingHint'), active: true, tone: 'green' as const };
    if (communicationMode === 'full_agent') return { label: t('aiHandling'), hint: t('aiHandlingHint'), active: isPlaying, tone: 'purple' as const };
    return { label: t('listening'), hint: t('listeningHint'), active: isPlaying, tone: 'purple' as const };
  })();

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <CallStatusBar callStatus={callStatus} callDuration={callDuration} targetName={call?.targetName} callMode={callMode} />

      {error && <div className="border-b border-[#EECACA] bg-[#FAECEB] px-4 py-2 text-xs text-[#A83C3C]">{error}</div>}

      <div className="flex min-h-0 flex-1 flex-col items-center justify-center bg-[#F8F7F9] px-6 py-8 text-center">
        <div className="w-full max-w-sm rounded-2xl border border-[#E4DAEF] bg-white px-6 py-7 shadow-[0_8px_22px_rgba(31,26,34,.045)]">
          <div className="mx-auto flex h-20 w-48 items-center justify-center rounded-[22px] border border-[#E4DAEF] bg-[#F8F4FC]">
            <VoiceSignal active={state.active} tone={state.tone} />
          </div>
          <p className="mt-5 text-base font-bold text-[#211D24]">{state.label}</p>
          <p className="mt-1.5 text-xs leading-5 text-[#706A73]">{state.hint}</p>

          <div className="mt-5 flex items-center justify-center gap-2 border-t border-[#EEEAEF] pt-4 text-xs text-[#706A73]">
            <BadgeIcon className="size-3.5 text-[#6B2EAA]" />
            <span className="font-semibold">{badgeLabel}</span>
          </div>
        </div>

        {communicationMode === 'full_agent' && (
          <div className="mt-4 flex w-full max-w-sm items-center gap-3 rounded-xl border border-[#E4E1E6] bg-white px-4 py-3 text-left">
            <span className="grid size-9 shrink-0 place-items-center rounded-[9px] bg-[#2E2932] text-white"><Bot className="size-4" /></span>
            <div className="min-w-0"><p className="text-xs font-bold text-[#211D24]">{t('aiHandling')}</p><p className="mt-0.5 text-[11px] text-[#706A73]">{t('aiNoIntervention')}</p></div>
            <span className="ml-auto size-2 shrink-0 animate-pulse rounded-full bg-[#247353]" />
          </div>
        )}
      </div>

      {isActive && (
        <div className="flex shrink-0 items-center gap-2 border-t border-[#E4E1E6] px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))]">
          {communicationMode === 'voice_to_voice' && (
            <button
              type="button"
              onClick={() => toggleMute?.()}
              className={`inline-flex h-11 items-center gap-2 rounded-[9px] border px-4 text-xs font-bold transition-colors ${
                isMuted
                  ? 'border-[#EECACA] bg-[#FAECEB] text-[#A83C3C] hover:bg-[#F6DEDC]'
                  : 'border-[#D1CCD4] bg-white text-[#5E5861] hover:border-[#D8C9EA] hover:bg-[#F3EEF9] hover:text-[#6B2EAA]'
              }`}
            >
              {isMuted ? <MicOff className="size-4" /> : <Mic className="size-4" />}
              {isMuted ? t('unmute') : t('mute')}
            </button>
          )}
          <button
            type="button"
            onClick={() => endCall?.()}
            className="ml-auto inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-[9px] bg-[#A83C3C] px-4 text-sm font-bold text-white transition-colors hover:bg-[#8F3030]"
          >
            <PhoneOff className="size-4" />
            {t('endCall')}
          </button>
        </div>
      )}
    </div>
  );
}
