'use client';

import { useTranslations } from 'next-intl';
import { Languages, PhoneCall, ShieldCheck } from 'lucide-react';
import OAuthButtons from '@/components/auth/OAuthButtons';
import LoginForm from '@/components/auth/LoginForm';
import LanguageSwitcher from '@/components/common/LanguageSwitcher';

export default function LoginPage() {
  const t = useTranslations('login');

  return (
    <div className="min-h-dvh overflow-y-auto bg-[#F5F4F6] p-4 sm:p-6">
      <div className="mx-auto grid min-h-[calc(100dvh-2rem)] max-w-5xl overflow-hidden rounded-2xl border border-[#E4E1E6] bg-white shadow-[0_1px_2px_rgba(31,26,34,.04),0_16px_48px_rgba(31,26,34,.07)] sm:min-h-[calc(100dvh-3rem)] lg:grid-cols-[1.05fr_0.95fr]">
        <section className="hidden flex-col justify-between bg-[#17151A] p-10 text-white lg:flex">
          <div>
            <span className="wigtn-wordmark wigtn-wordmark--light text-[28px]">WIGTN<span>.</span></span>
            <span className="mt-2 block text-xs font-semibold tracking-[0.1em] text-[#AAA3AE]">WIGVO OPERATIONS</span>
          </div>
          <div className="max-w-md">
            <h1 className="text-[34px] font-bold leading-[1.25] tracking-[-0.045em] text-[#F5F1F8]">{t('operationsTitle')}</h1>
            <p className="mt-4 text-sm leading-7 text-[#AAA3AE]">{t('operationsDescription')}</p>
            <div className="mt-8 grid gap-3">
              {[
                [PhoneCall, t('featureCalls')],
                [Languages, t('featureTranslation')],
                [ShieldCheck, t('featureInstitution')],
              ].map(([Icon, label]) => {
                const FeatureIcon = Icon as typeof PhoneCall;
                return (
                  <div key={label as string} className="flex items-center gap-3 text-sm text-[#D8D1DB]">
                    <span className="grid size-9 place-items-center rounded-[9px] bg-[#2B2630] text-[#A85FEA]"><FeatureIcon className="size-4" /></span>
                    <span>{label as string}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <p className="text-[11px] text-[#77717B]">© {new Date().getFullYear()} WIGTN</p>
        </section>

        <section className="relative flex items-center justify-center px-6 py-12 sm:px-12">
          <div className="absolute right-5 top-5"><LanguageSwitcher direction="down" /></div>
          <div className="w-full max-w-sm">
            <div className="mb-10 lg:hidden">
              <span className="wigtn-wordmark text-[26px]">WIGTN<span>.</span></span>
              <span className="mt-1.5 block text-[11px] font-semibold tracking-[0.09em] text-[#8A838D]">WIGVO OPERATIONS</span>
            </div>
            <p className="text-xs font-bold tracking-[0.1em] text-[#6B2EAA]">WIGVO OPERATIONS</p>
            <h2 className="mt-3 text-2xl font-bold tracking-[-0.035em] text-[#211D24]">{t('accountTitle')}</h2>
            <p className="mt-2 text-sm leading-6 text-[#706A73]">{t('accountDescription')}</p>
            <div className="mt-7"><LoginForm /></div>
            <div className="my-5 flex items-center gap-3 text-[11px] text-[#9A939E]">
              <span className="h-px flex-1 bg-[#E4E1E6]" />
              <span>{t('or')}</span>
              <span className="h-px flex-1 bg-[#E4E1E6]" />
            </div>
            <OAuthButtons />
            <p className="mt-5 text-center text-[11px] leading-5 text-[#8A838D]">{t('terms')}</p>
          </div>
        </section>
      </div>
    </div>
  );
}
