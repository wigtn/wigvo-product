'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { useTranslations } from 'next-intl';
import { MessageSquare, Settings2 } from 'lucide-react';
import OperationsShell from '@/components/layout/OperationsShell';
import ChatContainer from '@/components/chat/ChatContainer';
import RelayCallProvider from '@/components/call/RelayCallProvider';
import CallEffectPanel from '@/components/call/CallEffectPanel';
import { useDashboard } from '@/hooks/useDashboard';
import { cn } from '@/lib/utils';

function WorkspaceGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-0 w-full flex-1 gap-3 lg:grid-cols-[420px_minmax(0,1fr)] lg:gap-4">
      {children}
    </div>
  );
}

export default function DashboardLayout() {
  const { callingCallId, callingCommunicationMode } = useDashboard();
  const t = useTranslations('dashboard');
  const [mobileTab, setMobileTab] = useState<'controls' | 'live'>('controls');
  const isCalling = Boolean(callingCallId);

  useEffect(() => {
    if (!isCalling) return;
    const id = window.setTimeout(() => setMobileTab('live'), 0);
    return () => window.clearTimeout(id);
  }, [isCalling]);

  const mobileTabs = (
    <div className="flex rounded-[9px] border border-[#E4E1E6] bg-[#F3F0F4] p-1 lg:hidden">
      <button
        type="button"
        onClick={() => setMobileTab('controls')}
        className={cn('flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-xs font-semibold transition-colors', mobileTab === 'controls' ? 'bg-white text-[#1E1E28] shadow-sm' : 'text-[#686375] hover:text-[#1E1E28]')}
      >
        <Settings2 className="size-3.5" />
        {isCalling ? t('tabSession') : t('tabSetup')}
      </button>
      <button
        type="button"
        onClick={() => setMobileTab('live')}
        className={cn('flex h-8 items-center gap-1.5 rounded-[7px] px-3 text-xs font-semibold transition-colors', mobileTab === 'live' ? 'bg-white text-[#1E1E28] shadow-sm' : 'text-[#686375] hover:text-[#1E1E28]')}
      >
        <MessageSquare className="size-3.5" />
        {t('tabLive')}
      </button>
    </div>
  );

  const activeCallGrid = (
    <WorkspaceGrid>
      <section className={cn('dashboard-panel min-h-0 overflow-hidden rounded-xl', mobileTab !== 'controls' ? 'hidden lg:block' : 'block')} aria-label={t('tabSession')}>
        <CallEffectPanel />
      </section>

      <section className={cn('dashboard-panel min-h-0 overflow-hidden rounded-xl', mobileTab !== 'live' ? 'hidden lg:block' : 'block')} aria-label={t('tabLive')}>
        <ChatContainer />
      </section>
    </WorkspaceGrid>
  );

  if (!isCalling || !callingCallId) {
    return (
      <OperationsShell active="outbound" title={t('outboundTitle')} description={t('outboundDescription')}>
        <section className="ops-page-frame" aria-label={t('tabSetup')}>
          <ChatContainer />
        </section>
      </OperationsShell>
    );
  }

  return (
    <OperationsShell active="outbound" title={t('outboundTitle')} description={t('outboundDescription')} workspace>
      <div className="flex h-full min-h-0 flex-col gap-2 lg:gap-0">
        {mobileTabs}
        <RelayCallProvider key={callingCallId} callingCallId={callingCallId} communicationMode={callingCommunicationMode ?? 'voice_to_voice'}>
          {activeCallGrid}
        </RelayCallProvider>
      </div>
    </OperationsShell>
  );
}
