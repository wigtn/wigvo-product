'use client';

import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, Globe2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { changeLocale } from '@/components/providers/I18nProvider';
import { getStoredLocale, type Locale } from '@/lib/i18n';
import { cn } from '@/lib/utils';

interface LanguageSwitcherProps {
  direction?: 'up' | 'down';
  isCollapsed?: boolean;
  tone?: 'light' | 'dark';
}

const locales: Locale[] = ['ko', 'en'];

export default function LanguageSwitcher({
  direction = 'up',
  isCollapsed = false,
  tone = 'light',
}: LanguageSwitcherProps) {
  const t = useTranslations('language');
  const [isOpen, setIsOpen] = useState(false);
  const [currentLocale, setCurrentLocale] = useState<Locale>(() => getStoredLocale());
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleLocaleChange = (event: CustomEvent<Locale>) => setCurrentLocale(event.detail);
    window.addEventListener('localeChange', handleLocaleChange as EventListener);
    return () => window.removeEventListener('localeChange', handleLocaleChange as EventListener);
  }, []);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) setIsOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  const handleLocaleChange = (locale: Locale) => {
    changeLocale(locale);
    setIsOpen(false);
  };

  const isDark = tone === 'dark';

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-label={t(currentLocale)}
        aria-expanded={isOpen}
        className={cn(
          'flex h-10 items-center rounded-[9px] border text-xs font-semibold transition-colors',
          isCollapsed ? 'w-10 justify-center px-0' : 'w-full justify-between gap-2 px-3',
          isDark
            ? 'border-[#353139] bg-[#211E24] text-[#D9D3DC] hover:border-[#49434D] hover:bg-[#29252C] hover:text-white'
            : 'border-[#D8D4DC] bg-white text-[#5F5A68] hover:border-[#BEB8C4] hover:bg-[#FAF9FB] hover:text-[#1E1E28]',
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Globe2 className={cn('size-4 shrink-0', isDark ? 'text-[#A85FEA]' : 'text-[#6B2EAA]')} />
          {!isCollapsed && <span className="truncate">{t(currentLocale)}</span>}
        </span>
        {!isCollapsed && <ChevronDown className={cn('size-3.5 shrink-0 transition-transform', isOpen && 'rotate-180')} />}
      </button>

      {isOpen && (
        <div
          className={cn(
            'absolute z-50 w-full min-w-36 overflow-hidden rounded-[10px] border p-1 shadow-[0_12px_30px_rgba(21,21,30,0.16)]',
            direction === 'down' ? 'top-full mt-2' : 'bottom-full mb-2',
            isCollapsed ? 'left-0' : 'right-0',
            isDark ? 'border-[#3A353E] bg-[#211E24]' : 'border-[#E0DCE4] bg-white',
          )}
        >
          {locales.map((locale) => {
            const selected = currentLocale === locale;
            return (
              <button
                key={locale}
                type="button"
                onClick={() => handleLocaleChange(locale)}
                className={cn(
                  'flex h-9 w-full items-center justify-between rounded-[7px] px-2.5 text-left text-xs font-medium transition-colors',
                  isDark
                    ? selected
                      ? 'bg-[#302A35] text-white'
                      : 'text-[#B7B0BA] hover:bg-[#29252C] hover:text-white'
                    : selected
                      ? 'bg-[#F3EEF9] text-[#6B2EAA]'
                      : 'text-[#686375] hover:bg-[#F7F5F8] hover:text-[#1E1E28]',
                )}
              >
                <span>{t(locale)}</span>
                {selected && <Check className="size-3.5" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
