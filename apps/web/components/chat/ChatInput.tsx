'use client';

import { useState, useRef, useCallback, useImperativeHandle, forwardRef } from 'react';
import { useTranslations } from 'next-intl';
import { ArrowUp } from 'lucide-react';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export interface ChatInputHandle {
  focus: () => void;
}

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(function ChatInput(
  {
    onSend,
    disabled = false,
    placeholder,
  },
  ref
) {
  const t = useTranslations('chat');
  const resolvedPlaceholder = placeholder ?? t('inputPlaceholder');
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useImperativeHandle(ref, () => ({
    focus: () => {
      requestAnimationFrame(() => textareaRef.current?.focus());
    },
  }));

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;

    onSend(trimmed);
    setValue('');

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
  }, [value, disabled, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    const textarea = e.target;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
  };

  const canSend = !disabled && value.trim().length > 0;

  return (
    <div className="border-t border-[#E4E1E6] bg-white px-4 py-3 pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))]">
      <div className="flex items-end gap-2 rounded-[9px] border border-[#D1CCD4] bg-white px-3 py-2 transition-all focus-within:border-[#9B51E0] focus-within:ring-3 focus-within:ring-[#F3EEF9]">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={resolvedPlaceholder}
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none bg-transparent py-1 text-sm text-[#211D24] placeholder:text-[#9A939E] focus:outline-none disabled:cursor-not-allowed disabled:opacity-40"
        />
        <button
          onClick={handleSend}
          disabled={!canSend}
          className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200 ${
            canSend
              ? 'bg-[#6B2EAA] hover:bg-[#51327E] text-white shadow-sm'
              : 'bg-[#E4E1E6] text-[#AAA3AE] cursor-not-allowed'
          }`}
        >
          <ArrowUp className="size-4" />
        </button>
      </div>
    </div>
  );
});

export default ChatInput;
