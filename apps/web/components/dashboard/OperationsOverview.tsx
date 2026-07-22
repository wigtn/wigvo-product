'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useLocale, useTranslations } from 'next-intl';
import { AlertCircle, ArrowRight, Clock3, Loader2, PhoneIncoming, PhoneOutgoing, RefreshCw } from 'lucide-react';
import OperationsShell from '@/components/layout/OperationsShell';
import type { Call } from '@/shared/types';
import type { InboundCall } from '@/shared/inbound-types';
import { isDemoMode } from '@/lib/demo';

const REFRESH_INTERVAL_MS = 10_000;

function maskPhone(value: string): string {
  const digits = value.replace(/\D/g, '');
  if (digits.length < 7) return value;
  const visibleEnd = digits.slice(-4);
  const prefix = value.startsWith('+') ? `+${digits.slice(0, Math.min(3, digits.length - 4))}` : digits.slice(0, 3);
  return `${prefix} ··· ${visibleEnd}`;
}

function getCallTarget(call: Call): string {
  if (call.status === 'COMPLETED' || call.status === 'FAILED') return `/result/${call.id}`;
  return `/calling/${call.id}`;
}

export default function OperationsOverview() {
  const t = useTranslations('operationsDashboard');
  const locale = useLocale();
  const router = useRouter();
  const [calls, setCalls] = useState<Call[]>([]);
  const [inboundCalls, setInboundCalls] = useState<InboundCall[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const loadOverview = useCallback(async () => {
    try {
      const [callsResponse, inboundResponse] = await Promise.all([
        fetch('/api/calls', { cache: 'no-store' }),
        fetch('/api/inbound', { cache: 'no-store' }),
      ]);
      if (callsResponse.status === 401 || inboundResponse.status === 401) {
        if (isDemoMode()) {
          setCalls([]);
          setInboundCalls([]);
          setError(false);
          return;
        }
        router.push('/login');
        return;
      }
      if (!callsResponse.ok || !inboundResponse.ok) throw new Error('overview');

      const callsPayload = (await callsResponse.json()) as { calls?: Call[] } | Call[];
      const inboundPayload = (await inboundResponse.json()) as { calls?: InboundCall[] };
      const nextCalls = Array.isArray(callsPayload) ? callsPayload : (callsPayload.calls ?? []);
      setCalls(nextCalls.slice(0, 4));
      setInboundCalls((inboundPayload.calls ?? []).slice(0, 3));
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadOverview(), 0);
    const refreshTimer = window.setInterval(() => void loadOverview(), REFRESH_INTERVAL_MS);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(refreshTimer);
    };
  }, [loadOverview]);

  const statusLabel = (call: Call) => {
    if (call.status === 'COMPLETED') return t('completed');
    if (call.status === 'FAILED') return call.result === 'NO_ANSWER' ? t('noAnswer') : t('failed');
    if (call.status === 'IN_PROGRESS' || call.status === 'CALLING') return t('inProgress');
    return t('pending');
  };

  const hasOverviewData = calls.length > 0 || inboundCalls.length > 0;

  return (
    <OperationsShell active="dashboard" title={t('title')} description={t('description')}>
      <div className="mx-auto w-full max-w-[1320px]">
        <div className="mb-5 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-[11px] font-bold tracking-[0.11em] text-[#6B2EAA]">{t('kicker')}</p>
            <h2 className="mt-1.5 text-[22px] font-bold tracking-[-0.035em] text-[#1E1E28] sm:text-[24px]">{t('workspaceTitle')}</h2>
            <p className="mt-1 text-sm text-[#686375]">{t('workspaceDescription')}</p>
          </div>
          <Link href="/outbound" className="inline-flex h-10 items-center justify-center gap-2 rounded-[9px] bg-[#6B2EAA] px-4 text-sm font-semibold text-white transition-colors hover:bg-[#5B258F]">
            <PhoneOutgoing className="size-4" />
            {t('newCall')}
          </Link>
        </div>

        {error && !hasOverviewData && !loading ? (
          <section className="dashboard-panel flex min-h-56 flex-col items-center justify-center rounded-xl px-6 text-center">
            <span className="grid size-11 place-items-center rounded-[10px] bg-[#FAECEB] text-[#A83C3C]"><AlertCircle className="size-5" /></span>
            <strong className="mt-3 text-sm text-[#1E1E28]">{t('loadError')}</strong>
            <button type="button" onClick={() => void loadOverview()} className="mt-4 inline-flex h-9 items-center gap-2 rounded-[8px] border border-[#D1CCD4] bg-white px-3 text-xs font-semibold text-[#5F5A68] transition-colors hover:border-[#BEB8C4] hover:bg-[#F7F5F8] hover:text-[#1E1E28]">
              <RefreshCw className="size-3.5" />
              {t('retry')}
            </button>
          </section>
        ) : (
          <>
            {error && (
              <div className="mb-3 flex items-center gap-2 rounded-[9px] border border-[#F0D7D4] bg-[#FFF8F7] px-3.5 py-2.5 text-xs text-[#8F3030]">
                <AlertCircle className="size-3.5 shrink-0" />
                <span>{t('loadError')}</span>
              </div>
            )}

        <div className="grid overflow-hidden rounded-[12px] border border-[#DEDADF] bg-white lg:grid-cols-[minmax(0,1fr)_340px]">
          <section className="min-w-0">
            <div className="flex h-[58px] items-center justify-between border-b border-[#E4E1E6] px-5">
              <strong className="text-sm text-[#211D24]">{t('recentCalls')}</strong>
              <Link href="/history" className="inline-flex items-center gap-1 text-xs font-semibold text-[#706A73] hover:text-[#6B2EAA]">
                {t('viewAll')} <ArrowRight className="size-3.5" />
              </Link>
            </div>
            {loading ? (
              <div className="grid min-h-56 place-items-center"><Loader2 className="size-5 animate-spin text-[#6B2EAA]" /></div>
            ) : calls.length === 0 ? (
              <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
                <span className="grid size-10 place-items-center rounded-[10px] bg-[#F3EEF9] text-[#6B2EAA]"><PhoneOutgoing className="size-[18px]" /></span>
                <strong className="mt-3 text-sm text-[#1E1E28]">{t('noRecentCalls')}</strong>
                <p className="mt-1 text-xs text-[#8A838D]">{t('noRecentCallsHint')}</p>
                <Link href="/outbound" className="mt-3 text-xs font-semibold text-[#6B2EAA] hover:text-[#5B258F]">{t('newCall')} →</Link>
              </div>
            ) : (
              <div>
                {calls.map((call) => (
                  <Link key={call.id} href={getCallTarget(call)} className="grid min-h-[76px] grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 border-b border-[#EEEAEF] px-4 transition-colors last:border-b-0 hover:bg-[#FAF8FC] sm:grid-cols-[38px_minmax(0,1fr)_auto_58px] sm:px-5">
                    <span className="grid size-9 place-items-center rounded-[9px] bg-[#F3EEF9] text-[#6B2EAA]"><PhoneOutgoing className="size-4" /></span>
                    <span className="min-w-0">
                      <strong className="block truncate text-sm font-bold text-[#211D24]">{call.targetName || maskPhone(call.targetPhone)}</strong>
                      <span className="mt-1 block truncate text-xs text-[#706A73]">{call.parsedService || call.summary || `${call.sourceLanguage || 'ko'} → ${call.targetLanguage || '-'}`}</span>
                    </span>
                    <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${call.status === 'COMPLETED' ? 'bg-[#EDF6F1] text-[#247353]' : call.status === 'FAILED' ? 'bg-[#FAECEB] text-[#A83C3C]' : 'bg-[#F3EEF9] text-[#6B2EAA]'}`}>{statusLabel(call)}</span>
                    <time className="hidden text-right text-xs tabular-nums text-[#706A73] sm:block">{new Date(call.createdAt).toLocaleTimeString(locale === 'ko' ? 'ko-KR' : 'en-US', { hour: '2-digit', minute: '2-digit' })}</time>
                  </Link>
                ))}
              </div>
            )}
          </section>

          <aside className="border-t border-[#DEDADF] bg-[#FAF9FB] lg:border-l lg:border-t-0">
            <div className="flex h-[58px] items-center justify-between border-b border-[#E4E1E6] px-5">
              <strong className="text-sm text-[#211D24]">{t('waitingCalls', { count: inboundCalls.length })}</strong>
              <span className="text-[11px] text-[#8A838D]">{t('arrivalOrder')}</span>
            </div>
            {loading ? (
              <div className="grid min-h-56 place-items-center"><Loader2 className="size-5 animate-spin text-[#6B2EAA]" /></div>
            ) : inboundCalls.length === 0 ? (
              <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
                <span className="grid size-10 place-items-center rounded-[10px] bg-[#EDF6F1] text-[#247353]"><PhoneIncoming className="size-[18px]" /></span>
                <strong className="mt-3 text-sm text-[#1E1E28]">{t('noWaitingCalls')}</strong>
                <p className="mt-1 text-xs leading-5 text-[#8A838D]">{t('noWaitingCallsHint')}</p>
              </div>
            ) : (
              <div className="p-3">
                {inboundCalls.map((call, index) => (
                  <div key={call.call_id} className="mb-2 rounded-[10px] border border-[#E4E1E6] bg-white p-4 last:mb-0">
                    <div className="flex items-center justify-between gap-3"><strong className="text-sm text-[#211D24]">{t('inboundLabel', { number: index + 1 })}</strong><span className="inline-flex items-center gap-1 text-xs font-semibold tabular-nums text-[#247353]"><Clock3 className="size-3" />{new Date(call.created_at).toLocaleTimeString(locale === 'ko' ? 'ko-KR' : 'en-US', { hour: '2-digit', minute: '2-digit' })}</span></div>
                    <p className="mt-2 text-xs text-[#706A73]">{call.languages.length > 1 ? `${call.languages[0].toUpperCase()} → ${call.languages[1].toUpperCase()}` : t('languagePending')}</p>
                    {index === 0 && <Link href="/inbound" className="mt-3 inline-flex h-9 w-full items-center justify-center rounded-[8px] border border-[#6B2EAA] text-xs font-bold text-[#6B2EAA] transition-colors hover:bg-[#6B2EAA] hover:text-white">{t('pickup')}</Link>}
                  </div>
                ))}
              </div>
            )}
            <p className="border-t border-[#E4E1E6] px-5 py-3 text-[11px] leading-5 text-[#8A838D]">{t('queueHint')}</p>
          </aside>
        </div>
          </>
        )}
      </div>
    </OperationsShell>
  );
}
