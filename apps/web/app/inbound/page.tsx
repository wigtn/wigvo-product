'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { AlertCircle, Clock3, Loader2, PhoneIncoming, RefreshCw } from 'lucide-react';
import OperationsShell from '@/components/layout/OperationsShell';
import type { InboundCall, InboundPickupResult } from '@/shared/inbound-types';
import { isDemoMode } from '@/lib/demo';

const POLL_INTERVAL_MS = 3000;

export default function InboundQueuePage() {
  const router = useRouter();
  const t = useTranslations('inbound');
  const [calls, setCalls] = useState<InboundCall[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [claimingId, setClaimingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refreshingRef = useRef(false);
  const claimingRef = useRef(false);

  const loadCalls = useCallback(async (quiet = false) => {
    if (!quiet && refreshingRef.current) return;
    if (!quiet) refreshingRef.current = true;
    if (!quiet) setRefreshing(true);
    try {
      const response = await fetch('/api/inbound', { cache: 'no-store' });
      if (response.status === 401 && isDemoMode()) {
        setCalls([]);
        setError(null);
        return;
      }
      if (!response.ok) throw new Error(t('errors.load'));
      const payload = (await response.json()) as { calls: InboundCall[] };
      setCalls(payload.calls);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t('errors.load'));
    } finally {
      setLoading(false);
      setRefreshing(false);
      if (!quiet) refreshingRef.current = false;
    }
  }, [t]);

  useEffect(() => {
    const initialLoad = window.setTimeout(() => void loadCalls(true), 0);
    const timer = window.setInterval(() => void loadCalls(true), POLL_INTERVAL_MS);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
    };
  }, [loadCalls]);

  const pickup = useCallback(async (callId: string) => {
    if (claimingRef.current) return;
    claimingRef.current = true;
    setClaimingId(callId);
    setError(null);
    try {
      const response = await fetch(`/api/inbound/${callId}/pickup`, { method: 'POST' });
      const payload = (await response.json()) as InboundPickupResult & { error?: string };
      if (!response.ok) {
        if (response.status === 409) throw new Error(t('errors.claimed'));
        if (response.status === 403) throw new Error(t('errors.forbidden'));
        throw new Error(payload.error || t('errors.pickup'));
      }
      router.push(`/inbound/${callId}`);
    } catch (pickupError) {
      setError(pickupError instanceof Error ? pickupError.message : t('errors.pickup'));
      await loadCalls(true);
    } finally {
      setClaimingId(null);
      claimingRef.current = false;
    }
  }, [loadCalls, router, t]);

  const refreshButton = (
    <button
      type="button"
      onClick={() => void loadCalls()}
      disabled={refreshing}
      className="grid size-10 place-items-center rounded-[9px] border border-[#D1CCD4] bg-white text-[#686375] transition-colors hover:border-[#BEB8C4] hover:bg-[#F7F5F8] hover:text-[#1E1E28] disabled:opacity-50"
      aria-label={t('refresh')}
    >
      <RefreshCw className={`size-4 ${refreshing ? 'animate-spin' : ''}`} />
    </button>
  );

  return (
    <OperationsShell active="inbound" title={t('title')} description={t('subtitle')} headerActions={refreshButton}>
      <div className="ops-page-frame">
        <section>
          <div className="ops-panel-header">
            <div className="flex items-center gap-2.5">
              <span className="grid size-8 place-items-center rounded-lg bg-[#EDF6F1] text-[#247353]"><PhoneIncoming className="size-4" /></span>
              <h2 className="text-sm font-bold text-[#211D24]">{t('queueTitle')}</h2>
            </div>
            {!loading && !error && (
              <span className={calls.length > 0 ? 'text-xs font-semibold text-[#247353]' : 'text-xs font-medium text-[#918B98]'}>
                {t('waitingCount', { count: calls.length })}
              </span>
            )}
          </div>

          {loading ? (
            <div className="flex min-h-56 items-center justify-center gap-3 text-sm text-[#686375]">
              <Loader2 className="size-5 animate-spin text-[#6B2EAA]" />
              <span>{t('loading')}</span>
            </div>
          ) : error && calls.length === 0 ? (
            <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
              <div className="grid size-11 place-items-center rounded-[10px] bg-[#FAECEB] text-[#A83C3C]"><AlertCircle className="size-5" /></div>
              <p className="mt-3 text-sm font-semibold text-[#1E1E28]">{error}</p>
              <button
                type="button"
                onClick={() => void loadCalls()}
                className="mt-4 inline-flex h-9 items-center gap-2 rounded-[8px] border border-[#D1CCD4] bg-white px-3 text-xs font-semibold text-[#5F5A68] transition-colors hover:border-[#BEB8C4] hover:bg-[#F7F5F8] hover:text-[#1E1E28]"
              >
                <RefreshCw className="size-3.5" />
                {t('refresh')}
              </button>
            </div>
          ) : calls.length === 0 ? (
            <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
              <div className="grid size-11 place-items-center rounded-[10px] bg-[#EDF6F1] text-[#247353]"><PhoneIncoming className="size-5" /></div>
              <p className="mt-3 text-sm font-semibold text-[#1E1E28]">{t('emptyTitle')}</p>
              <p className="mt-1 text-xs text-[#686375]">{t('emptyDescription')}</p>
            </div>
          ) : (
            <>
              {error && (
                <div className="flex items-center gap-2 border-b border-[#F0D7D4] bg-[#FFF8F7] px-5 py-2.5 text-xs text-[#8F3030]">
                  <AlertCircle className="size-3.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}
              <ul className="divide-y divide-[#EEEAEF]">
              {calls.map((call, index) => {
                const languages = call.languages.length >= 2
                  ? `${call.languages[0].toUpperCase()} → ${call.languages[1].toUpperCase()}`
                  : t('defaultLanguages');
                return (
                  <li key={call.call_id} className="ops-list-row grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 transition-colors hover:bg-[#FAF8FC] sm:gap-4">
                    <div className="grid size-10 shrink-0 place-items-center rounded-[10px] bg-[#EDF6F1] text-[#247353]"><PhoneIncoming className="size-[18px]" /></div>
                    <div className="min-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <p className="truncate text-sm font-bold text-[#211D24]">{t('callLabel', { number: index + 1 })}</p>
                        <span className="hidden items-center rounded-full bg-[#EDF6F1] px-2 py-1 text-[10px] font-bold text-[#247353] sm:inline-flex">{t('waiting')}</span>
                      </div>
                      <p className="mt-1 flex items-center gap-1.5 truncate text-xs text-[#706A73]">
                        <span>{languages}</span><span aria-hidden="true">·</span><Clock3 className="size-3" />
                        <span>{new Date(call.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => void pickup(call.call_id)}
                      disabled={claimingId !== null}
                      className="inline-flex min-h-10 min-w-20 items-center justify-center gap-2 rounded-[9px] border border-[#6B2EAA] bg-[#6B2EAA] px-3 text-xs font-bold text-white transition-all hover:border-[#51327E] hover:bg-[#51327E] disabled:opacity-50 sm:min-w-24 sm:px-4 sm:text-sm"
                    >
                      {claimingId === call.call_id && <Loader2 className="size-4 animate-spin" />}
                      {claimingId === call.call_id ? t('connecting') : t('pickup')}
                    </button>
                  </li>
                );
              })}
              </ul>
            </>
          )}
        </section>
      </div>
    </OperationsShell>
  );
}
