'use client';

import { useTranslations } from 'next-intl';
import type { Message } from '@/shared/types';
import { cn } from '@/lib/utils';

interface ChatMessageProps {
  message: Message;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const t = useTranslations('chat');
  const isUser = message.role === 'user';

  return (
    <div
      className={cn('flex w-full mb-4', isUser ? 'justify-end' : 'justify-start')}
    >
      <div
        className={cn(
          'max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap sm:max-w-[72%]',
          isUser
            ? 'rounded-br-md bg-[#2E2932] text-white'
            : 'surface-card rounded-bl-md text-[#312C35] shadow-sm'
        )}
      >
        {!isUser && (
          <div className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#6B2EAA]">
            {t('aiAssistant')}
          </div>
        )}
        {message.content}
      </div>
    </div>
  );
}
