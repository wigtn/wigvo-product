'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import Link from 'next/link';
import { Clock3, Loader2, PhoneIncoming } from 'lucide-react';
import OperationsShell from '@/components/layout/OperationsShell';
import RealtimeCallView from '@/components/call/RealtimeCallView';
import type { InboundCall, InboundPickupResult } from '@/shared/inbound-types';

const PICKUP_WS_PROTOCOL = 'wigvo.pickup';

export default function InboundCallPage() {
  const params = useParams<{ callId: string }>();
  const router = useRouter();
  const t = useTranslations('inbound');
  const callId = params.callId;
  const [pickup, setPickup] = useState<InboundPickupResult | null>(null);
  const [waitingCalls, setWaitingCalls] = useState<InboundCall[]>([]);
  const [error, setError] = useState<string | null>(null);
  const protocols = useMemo(
    () => pickup ? [PICKUP_WS_PROTOCOL, pickup.pickup_token] : undefined,
    [pickup],
  );

  const fetchPickup = useCallback(async () => {
    const response = await fetch(`/api/inbound/${callId}/pickup`, { method: 'POST' });
    const payload = (await response.json()) as InboundPickupResult & { error?: string };
    if (!response.ok) throw new Error(payload.error || t('errors.pickup'));
    return payload;
  }, [callId, t]);

  useEffect(() => {
    let cancelled = false;
    void fetchPickup()
      .then((payload) => {
        if (!cancelled) setPickup(payload);
      })
      .catch((pickupError: unknown) => {
        if (!cancelled) setError(pickupError instanceof Error ? pickupError.message : t('errors.pickup'));
      });
    return () => { cancelled = true; };
  }, [fetchPickup, t]);

  useEffect(() => {
    let cancelled = false;
    const loadQueue = async () => {
      try {
        const response = await fetch('/api/inbound', { cache: 'no-store' });
        if (!response.ok) return;
        const payload = (await response.json()) as { calls?: InboundCall[] };
        if (!cancelled) setWaitingCalls((payload.calls ?? []).filter((call) => call.call_id !== callId));
      } catch {
        // The active call remains usable even if the supporting queue cannot refresh.
      }
    };
    const initialLoad = window.setTimeout(() => void loadQueue(), 0);
    const refreshTimer = window.setInterval(() => void loadQueue(), 3_000);
    return () => {
      cancelled = true;
      window.clearTimeout(initialLoad);
      window.clearInterval(refreshTimer);
    };
  }, [callId]);

  const refreshWsProtocols = useCallback(async () => {
    const refreshed = await fetchPickup();
    setPickup(refreshed);
    return [PICKUP_WS_PROTOCOL, refreshed.pickup_token];
  }, [fetchPickup]);

  if (error) {
    return (
      <OperationsShell active="inbound" title={t('activeTitle')} description={t('activeDescription')}>
        <div className="mx-auto max-w-lg rounded-xl border border-[#EECACA] bg-white px-6 py-12 text-center shadow-sm">
          <p className="text-sm text-[#A83C3C]">{error}</p>
          <button
            type="button"
            onClick={() => router.push('/inbound')}
            className="mt-5 rounded-[9px] border border-[#D1CCD4] px-4 py-2 text-sm font-semibold text-[#5E5861] hover:border-[#D8C9EA] hover:bg-[#F3EEF9] hover:text-[#6B2EAA]"
          >
            {t('backToQueue')}
          </button>
        </div>
      </OperationsShell>
    );
  }

  if (!pickup || !protocols) {
    return (
      <OperationsShell active="inbound" title={t('activeTitle')} description={t('activeDescription')} workspace>
        <div className="flex h-full items-center justify-center"><Loader2 className="size-6 animate-spin text-[#6B2EAA]" /></div>
      </OperationsShell>
    );
  }

  return (
    <OperationsShell active="inbound" title={t('activeTitle')} description={t('activeDescription')} workspace>
      <div className="grid h-full min-h-0 w-full gap-3 lg:grid-cols-[280px_minmax(0,1fr)] lg:gap-4">
        <aside className="dashboard-panel hidden min-h-0 overflow-hidden rounded-xl lg:flex lg:flex-col">
          <div className="flex min-h-[72px] items-center justify-between border-b border-[#E4E1E6] px-5">
            <div>
              <strong className="text-sm text-[#211D24]">{t('queuePanelTitle')}</strong>
              <p className="mt-1 text-[11px] text-[#706A73]">{t('waitingCount', { count: waitingCalls.length })}</p>
            </div>
            <PhoneIncoming className="size-4 text-[#247353]" />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="border-b border-[#EEEAEF] bg-[#F0F7F3] px-4 py-4">
              <div className="flex items-center justify-between gap-2"><strong className="text-sm text-[#211D24]">{t('activeCall')}</strong><span className="rounded-full bg-white px-2 py-1 text-[10px] font-bold text-[#247353]">{t('inCall')}</span></div>
              <p className="mt-2 text-xs text-[#5E7268]">{pickup.source_language.toUpperCase()} → {pickup.target_language.toUpperCase()}</p>
            </div>
            {waitingCalls.map((call, index) => (
              <div key={call.call_id} className="border-b border-[#EEEAEF] px-4 py-4 last:border-b-0">
                <div className="flex items-center justify-between gap-2"><strong className="text-sm text-[#312C35]">{t('callLabel', { number: index + 2 })}</strong><span className="inline-flex items-center gap-1 text-[10px] font-semibold text-[#8A838D]"><Clock3 className="size-3" />{new Date(call.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span></div>
                <p className="mt-2 text-xs text-[#706A73]">{call.languages.length > 1 ? `${call.languages[0].toUpperCase()} → ${call.languages[1].toUpperCase()}` : t('defaultLanguages')}</p>
              </div>
            ))}
          </div>
          <Link href="/inbound" className="flex min-h-11 items-center justify-center border-t border-[#E4E1E6] text-xs font-bold text-[#6B2EAA] hover:bg-[#F3EEF9]">{t('viewQueue')}</Link>
        </aside>

        <div className="h-full min-h-0 min-w-0">
          <RealtimeCallView
            callId={callId}
            relayWsUrl={pickup.relay_ws_url}
            callMode="relay"
            communicationMode="voice_to_voice"
            targetName={t('caller')}
            wsProtocols={protocols}
            refreshWsProtocols={refreshWsProtocols}
            showRemoteSpeakingEffect
            onCallEnd={() => router.push('/inbound')}
          />
        </div>
      </div>
    </OperationsShell>
  );
}
