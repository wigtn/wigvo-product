'use client';

import { useTranslations } from 'next-intl';
import type { CaptionEntry } from '@/shared/call-types';
import { cn } from '@/lib/utils';

interface CaptionMessageProps {
  entry: CaptionEntry;
}

export default function CaptionMessage({ entry }: CaptionMessageProps) {
  const t = useTranslations('call.caption');
  const isUser = entry.speaker === 'user';
  const isAi = entry.speaker === 'ai';
  const isStage1 = entry.stage === 1;

  const speakerLabel =
    isUser ? t('you')
    : isAi ? t('ai')
    : t('recipient');

  return (
    <div className={cn('mb-3 flex w-full', isUser || isAi ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[82%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed sm:max-w-[72%]',
          isUser || isAi
            ? 'rounded-br-md bg-[#2E2932] text-white'
            : isStage1
              ? 'rounded-bl-md border border-[#E4E1E6] bg-[#F0EEF1] text-[#8A838D]'
              : 'rounded-bl-md border border-[#E4E1E6] bg-white text-[#312C35] shadow-sm',
          !entry.isFinal && 'opacity-60',
        )}
      >
        <div className={cn(
          'text-[10px] font-medium mb-1 uppercase tracking-wider',
          isUser || isAi ? 'text-white/60' : 'text-[#8A838D]',
        )}>
          {speakerLabel}
        </div>
        <p className={cn(isStage1 ? 'text-xs' : 'text-sm')}>
          {entry.text}
        </p>
      </div>
    </div>
  );
}
