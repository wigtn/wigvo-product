'use client';

import { useTranslations } from 'next-intl';
import { type Call } from '@/shared/types';
import { Phone, PhoneOff } from 'lucide-react';
import VoiceSignal from '@/components/call/VoiceSignal';

interface CallingStatusProps {
  call: Call | null;
  elapsed: number;
}

function formatElapsed(seconds: number): string {
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

export default function CallingStatus({ call, elapsed }: CallingStatusProps) {
  const t = useTranslations('callStatus');
  const isTerminal = call?.status === 'COMPLETED' || call?.status === 'FAILED';

  const statusLabel = (() => {
    switch (call?.status) {
      case 'PENDING': case 'CALLING': return t('connecting');
      case 'IN_PROGRESS': return t('delivering');
      case 'COMPLETED': case 'FAILED': return t('ended');
      default: return t('preparing');
    }
  })();

  return (
    <div className="flex flex-col items-center justify-center h-full gap-6 px-6">
      {!isTerminal ? (
        <div className="grid size-24 place-items-center rounded-[24px] border border-[#E2D9EA] bg-[#F6F0FB]">
          <div className="grid gap-2 text-center text-[#7B3BB6]">
            <Phone className="mx-auto size-6" strokeWidth={1.8} />
            <VoiceSignal active tone="purple" compact />
          </div>
        </div>
      ) : (
        <div className="flex size-20 items-center justify-center rounded-[20px] border border-[#E4E1E6] bg-[#F5F4F6]">
          <PhoneOff className="size-7 text-[#706A73]" />
        </div>
      )}

      {/* 상태 텍스트 */}
      <div className="text-center">
        <p className="text-sm font-medium mb-1 text-[#64748B]">
          {statusLabel}
          {!isTerminal && (
            <span className="ml-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[#9B51E0] align-middle" />
          )}
        </p>
        {call?.targetName && (
          <h2 className="text-lg font-bold text-[#0F172A] tracking-tight">
            {call.targetName}
          </h2>
        )}
        {call?.targetPhone && (
          <p className="mt-0.5 font-mono text-xs text-[#94A3B8]">{call.targetPhone}</p>
        )}
      </div>

      {/* 경과 시간 */}
      <div className="flex flex-col items-center gap-1">
        <span className="text-[10px] uppercase tracking-wider text-[#94A3B8] font-semibold">
          {t('elapsed')}
        </span>
        <span className="font-mono text-3xl font-bold tabular-nums tracking-tight text-[#0F172A]">
          {formatElapsed(elapsed)}
        </span>
      </div>

      {/* 간단한 단계 표시 */}
      {!isTerminal && (
        <div className="flex items-center gap-2">
          {[t('stepConnect'), t('stepDeliver'), t('stepComplete')].map((label, i) => {
            const stepIndex = (() => {
              const s = call?.status || 'PENDING';
              if (s === 'PENDING' || s === 'CALLING') return 0;
              if (s === 'IN_PROGRESS') return 1;
              return 2;
            })();
            const isActive = i === stepIndex;
            const isDone = i < stepIndex;

            return (
              <div key={label} className="flex items-center gap-2">
                {i > 0 && (
                  <div className={`w-6 h-px ${isDone ? 'bg-[#C9A5E9]' : 'bg-[#E4E1E6]'}`} />
                )}
                <div className="flex items-center gap-1.5">
                  <div
                    className={`w-2 h-2 rounded-full transition-colors ${
                      isActive
                        ? 'bg-[#9B51E0] animate-pulse'
                        : isDone
                          ? 'bg-[#7B3BB6]'
                          : 'bg-[#E4E1E6]'
                    }`}
                  />
                  <span className={`text-xs ${
                    isActive
                      ? 'font-medium text-[#211D24]'
                      : isDone
                        ? 'text-[#7B3BB6]'
                        : 'text-[#AAA4AC]'
                  }`}>
                    {label}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
