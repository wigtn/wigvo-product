'use client';

import { Phone } from 'lucide-react';

interface CallStatusBarProps {
  callStatus: 'idle' | 'connecting' | 'waiting' | 'connected' | 'ended';
  callDuration: number;
  targetName?: string | null;
  callMode: 'agent' | 'relay';
}

function formatDuration(seconds: number): string {
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

function getStatusLabel(status: CallStatusBarProps['callStatus']): string {
  switch (status) {
    case 'idle':
      return '\uB300\uAE30\uC911';
    case 'connecting':
      return '\uC5F0\uACB0 \uC911';
    case 'waiting':
      return '\uC5F0\uACB0 \uC911';
    case 'connected':
      return '\uC5F0\uACB0\uB428';
    case 'ended':
      return '\uC885\uB8CC';
  }
}

export default function CallStatusBar({
  callStatus,
  callDuration,
  targetName,
  callMode,
}: CallStatusBarProps) {
  const isActive = callStatus === 'connected' || callStatus === 'waiting';

  return (
    <div className="flex min-h-[72px] items-center justify-between gap-4 border-b border-[#E4E1E6] bg-white px-4 sm:px-5">
      <div className="flex min-w-0 items-center gap-3">
        <div
          className={`flex size-10 shrink-0 items-center justify-center rounded-full ${
            isActive ? 'bg-[#EDF6F1]' : 'bg-[#F0EEF1]'
          }`}
        >
          <Phone
            className={`size-4 ${
              isActive ? 'text-[#247353]' : 'text-[#8A838D]'
            }`}
          />
        </div>
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            {targetName && (
              <span className="truncate text-sm font-bold text-[#211D24] sm:text-base">
                {targetName}
              </span>
            )}
            <span
              className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-bold ${
                callMode === 'agent'
                  ? 'bg-[#F3EEF9] text-[#6B2EAA]'
                  : 'bg-[#EEEAF0] text-[#625D65]'
              }`}
            >
              {callMode === 'agent' ? 'AI AGENT' : 'RELAY'}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-1.5">
            {isActive && (
              <span className="inline-block size-1.5 animate-pulse rounded-full bg-[#247353]" />
            )}
            <span className="text-xs text-[#706A73]">
              {getStatusLabel(callStatus)}
            </span>
          </div>
        </div>
      </div>

      <span className="shrink-0 font-mono text-base font-bold tabular-nums text-[#211D24] sm:text-lg">
        {formatDuration(callDuration)}
      </span>
    </div>
  );
}
