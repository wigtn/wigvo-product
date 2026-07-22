'use client';

import { useState, useCallback, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { Send } from 'lucide-react';

interface CallChatInputProps {
  onSend: (text: string) => void;
  onTypingStart?: () => void;
  disabled?: boolean;
}

export default function CallChatInput({ onSend, onTypingStart, disabled }: CallChatInputProps) {
  const t = useTranslations('call');
  const [textInput, setTextInput] = useState('');
  const typingSentRef = useRef(false);

  const quickReplies = [
    { label: t('quickReplyYes'), value: t('quickReplyYesValue') },
    { label: t('quickReplyNo'), value: t('quickReplyNoValue') },
    { label: t('quickReplyWait'), value: t('quickReplyWaitValue') },
    { label: t('quickReplyRepeat'), value: t('quickReplyRepeatValue') },
  ];

  const handleChange = useCallback(
    (value: string) => {
      setTextInput(value);
      if (value.length > 0 && !typingSentRef.current && onTypingStart) {
        typingSentRef.current = true;
        onTypingStart();
      }
    },
    [onTypingStart],
  );

  const handleSend = useCallback(
    (text?: string) => {
      const msg = text ?? textInput.trim();
      if (!msg) return;
      onSend(msg);
      setTextInput('');
      typingSentRef.current = false;
    },
    [textInput, onSend],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="shrink-0 border-t border-[#E4E1E6] bg-white">
      {/* Quick reply chips */}
      <div className="flex items-center gap-2 px-4 py-2 overflow-x-auto">
        {quickReplies.map((reply) => (
          <button
            key={reply.label}
            onClick={() => handleSend(reply.value)}
            disabled={disabled}
            className="shrink-0 rounded-full border border-[#E4E1E6] bg-[#F8F7F9] px-3 py-1.5 text-xs font-semibold text-[#5E5861] transition-colors hover:border-[#D8C9EA] hover:bg-[#F3EEF9] hover:text-[#6B2EAA] disabled:opacity-40"
          >
            {reply.label}
          </button>
        ))}
      </div>

      {/* Text input */}
      <div className="flex items-center gap-2 border-t border-[#EEEAEF] px-4 py-3">
        <input
          type="text"
          value={textInput}
          onChange={(e) => handleChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={t('sendMessage')}
          className="h-11 flex-1 rounded-[9px] border border-[#D1CCD4] px-3 text-base text-[#211D24] placeholder:text-[#9A939E] focus:border-[#9B51E0] focus:outline-none focus:ring-3 focus:ring-[#F3EEF9] disabled:opacity-40 md:text-sm"
        />
        <button
          onClick={() => handleSend()}
          disabled={!textInput.trim() || disabled}
          className="flex size-11 items-center justify-center rounded-[9px] bg-[#6B2EAA] text-white transition-colors hover:bg-[#51327E] disabled:opacity-40"
        >
          <Send className="size-4" />
        </button>
      </div>
    </div>
  );
}
