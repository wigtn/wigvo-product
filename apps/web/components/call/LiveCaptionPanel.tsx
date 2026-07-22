'use client';

import { useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import type { CaptionEntry } from '@/shared/call-types';

interface LiveCaptionPanelProps {
  captions: CaptionEntry[];
  translationState: 'idle' | 'processing' | 'done';
  expanded?: boolean;
  compact?: boolean;
}

export default function LiveCaptionPanel({
  captions,
  translationState,
  expanded = false,
  compact = false,
}: LiveCaptionPanelProps) {
  const t = useTranslations('call');
  const scrollRef = useRef<HTMLDivElement>(null);
  const displayCaptions = compact ? captions.slice(-3) : captions;

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [captions.length, translationState]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#F8F7F9]">
      {!compact && (
        <div className="flex min-h-11 shrink-0 items-center justify-between border-b border-[#E4E1E6] bg-white px-4 sm:px-5">
          <h3 className="text-xs font-bold text-[#211D24]">{t('captions')}</h3>
          {expanded && <span className="text-[11px] text-[#8A838D]">{t('captionDisplayRule')}</span>}
        </div>
      )}

      <div
        ref={scrollRef}
        className={`styled-scrollbar min-h-0 flex-1 overflow-y-auto ${compact ? 'space-y-2 px-4 py-3' : 'space-y-5 px-4 py-5 sm:px-6'}`}
      >
        {displayCaptions.length === 0 && (
          <div className="flex h-full min-h-32 items-center justify-center text-center">
            <p className="text-xs text-[#9A939E]">{t('captionEmpty')}</p>
          </div>
        )}

        {displayCaptions.map((entry) => {
          const isOutgoing = entry.speaker === 'user' || entry.speaker === 'ai';
          const isStage1 = entry.stage === 1;
          const speaker = entry.speaker === 'user'
            ? t('caption.you')
            : entry.speaker === 'ai'
              ? t('caption.ai')
              : t('caption.recipient');

          return (
            <article key={entry.id} className={`flex flex-col ${isOutgoing ? 'items-end' : 'items-start'}`}>
              <div className={`mb-1.5 flex items-center gap-1.5 text-[11px] ${isOutgoing ? 'pr-1' : 'pl-1'}`}>
                <strong className="font-bold text-[#403A43]">{speaker}</strong>
                {isStage1 && <span className="text-[#9A939E]">{t('caption.original')}</span>}
              </div>
              <div
                className={`w-fit max-w-[88%] rounded-2xl px-4 py-3 shadow-[0_1px_2px_rgba(31,26,34,0.04)] sm:max-w-[72%] ${
                  isOutgoing
                    ? 'rounded-tr-md bg-[#2E2932] text-white'
                    : 'rounded-tl-md border border-[#E4E1E6] bg-white text-[#211D24]'
                }`}
              >
                {entry.originalText && (
                  <p className={`mb-2 border-b pb-2 text-xs leading-relaxed ${isOutgoing ? 'border-white/15 text-[#C6BEC9]' : 'border-[#EEEAEF] text-[#8A838D]'}`}>
                    {entry.originalText}
                  </p>
                )}
                <p className={`${expanded && !compact ? 'text-[15px]' : 'text-sm'} font-medium leading-relaxed`}>{entry.text}</p>
              </div>
            </article>
          );
        })}

        {translationState === 'processing' && (
          <div className="flex items-center gap-2 pl-1 text-xs text-[#706A73]">
            <span className="size-1.5 animate-pulse rounded-full bg-[#9B51E0]" />
            {t('translating')}
          </div>
        )}
      </div>
    </div>
  );
}
