'use client';

import { NextIntlClientProvider } from 'next-intl';
import { useState, useEffect, ReactNode } from 'react';
import { getStoredLocale, LOCALE_STORAGE_KEY, setStoredLocale, type Locale } from '@/lib/i18n';

// Import messages statically
import koMessages from '@/messages/ko.json';
import enMessages from '@/messages/en.json';

const messages: Record<Locale, typeof koMessages> = {
  ko: koMessages,
  en: enMessages,
};

interface I18nProviderProps {
  children: ReactNode;
}

export default function I18nProvider({ children }: I18nProviderProps) {
  const [locale, setLocale] = useState<Locale>('ko');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const storedLocale = getStoredLocale();
    const initialSync = window.setTimeout(() => {
      setLocale(storedLocale);
      setMounted(true);
      document.documentElement.lang = storedLocale;
    }, 0);

    // Listen for locale changes
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === LOCALE_STORAGE_KEY && e.newValue) {
        const nextLocale = e.newValue as Locale;
        setLocale(nextLocale);
        document.documentElement.lang = nextLocale;
      }
    };

    // Custom event for same-tab locale changes
    const handleLocaleChange = (e: CustomEvent<Locale>) => {
      setLocale(e.detail);
      document.documentElement.lang = e.detail;
    };

    window.addEventListener('storage', handleStorageChange);
    window.addEventListener('localeChange', handleLocaleChange as EventListener);

    return () => {
      window.clearTimeout(initialSync);
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener('localeChange', handleLocaleChange as EventListener);
    };
  }, []);

  // Prevent hydration mismatch by showing nothing until mounted
  if (!mounted) {
    return (
      <NextIntlClientProvider locale="ko" messages={messages.ko} timeZone="Asia/Seoul">
        {children}
      </NextIntlClientProvider>
    );
  }

  return (
    <NextIntlClientProvider locale={locale} messages={messages[locale]} timeZone="Asia/Seoul">
      {children}
    </NextIntlClientProvider>
  );
}

// Helper function to change locale and trigger re-render
export function changeLocale(newLocale: Locale): void {
  if (typeof window === 'undefined') return;
  setStoredLocale(newLocale);
  window.dispatchEvent(new CustomEvent('localeChange', { detail: newLocale }));
}
