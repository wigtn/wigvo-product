'use client';

import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { ACTIVE_LANGUAGES } from '@/shared/call-types';

interface LanguageDropdownProps {
  value: string;
  onChange: (code: string) => void;
  disabled?: boolean;
}

export default function LanguageDropdown({ value, onChange, disabled = false }: LanguageDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const tLang = useTranslations('langNames');

  const selected = ACTIVE_LANGUAGES.find((l) => l.code === value);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Close on Escape
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setIsOpen(false);
    }
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen]);

  const getLabel = (code: string, fallback: string) => {
    try {
      return tLang(code);
    } catch {
      return fallback;
    }
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => !disabled && setIsOpen((o) => !o)}
        disabled={disabled}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className="flex h-11 w-full items-center justify-between rounded-[9px] border border-[#D8D4DC] bg-white px-3 text-sm font-semibold text-[#1E1E28] transition-colors hover:border-[#BEB8C4] hover:bg-[#FAF9FB] focus:border-[#1E1E28] focus:outline-none focus-visible:!outline-[#1E1E28] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="flex items-center gap-2">
          <span className="grid h-6 min-w-7 place-items-center rounded-[6px] bg-[#F1EFF2] px-1.5 text-[9px] font-black tracking-[0.06em] text-[#4D4852]">
            {selected?.code.toUpperCase()}
          </span>
          <span>{getLabel(selected?.code ?? '', selected?.label ?? '')}</span>
        </span>
        <ChevronDown className={`size-4 text-[#918B98] transition-transform duration-150 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div
          role="listbox"
          className="absolute left-0 right-0 top-full z-50 mt-1.5 origin-top overflow-hidden rounded-[10px] border border-[#E0DCE4] bg-white p-1 shadow-[0_12px_30px_rgba(21,21,30,0.14)]"
        >
          {ACTIVE_LANGUAGES.map((lang) => {
            const isSelected = lang.code === value;
            return (
              <button
                key={lang.code}
                type="button"
                role="option"
                aria-selected={isSelected}
                onClick={() => {
                  onChange(lang.code);
                  setIsOpen(false);
                }}
                className={`flex h-9 w-full items-center justify-between rounded-[7px] px-2.5 text-sm transition-colors focus-visible:!outline-[#1E1E28] ${
                  isSelected
                    ? 'bg-[#F1EFF2] font-semibold text-[#1E1E28]'
                    : 'text-[#686375] hover:bg-[#F7F5F8] hover:text-[#1E1E28]'
                }`}
              >
                <span className="flex items-center gap-2">
                  <span className="grid h-6 min-w-7 place-items-center rounded-[6px] bg-white px-1.5 text-[9px] font-black tracking-[0.06em] text-[#4D4852]">
                    {lang.code.toUpperCase()}
                  </span>
                  <span>{getLabel(lang.code, lang.label)}</span>
                </span>
                {isSelected && <Check className="size-4 text-[#1E1E28]" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
