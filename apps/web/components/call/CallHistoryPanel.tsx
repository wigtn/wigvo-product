'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  Inbox,
  Keyboard,
  Languages,
  Loader2,
  Mic2,
  Phone,
  PhoneCall,
  PhoneOff,
  RefreshCw,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { isDemoMode } from '@/lib/demo';
import { DEMO_CALL_RESULT } from '@/lib/demo/mock-data';
import type { Call, TranscriptEntry } from '@/shared/types';
import type { CommunicationMode } from '@/shared/call-types';

type MobileView = 'list' | 'detail';

const MODE_ICONS: Record<CommunicationMode, typeof Mic2> = {
  voice_to_voice: Mic2,
  text_to_voice: Keyboard,
  full_agent: Bot,
};

const MODE_KEYS: Record<CommunicationMode, 'voiceToVoice' | 'textToVoice' | 'fullAgent'> = {
  voice_to_voice: 'voiceToVoice',
  text_to_voice: 'textToVoice',
  full_agent: 'fullAgent',
};

function createDemoHistory(): Call[] {
  const now = Date.now();
  return [
    {
      ...DEMO_CALL_RESULT,
      createdAt: new Date(now - 18 * 60_000).toISOString(),
      completedAt: new Date(now - 17 * 60_000).toISOString(),
      transcriptBilingual: [
        { role: 'user', original_text: '내일 저녁 7시에 두 명 예약 가능한가요?', translated_text: 'Is a table for two available tomorrow at 7 PM?', language: 'ko', timestamp: 1 },
        { role: 'recipient', original_text: 'Yes, we have a table available. May I have your name?', translated_text: '네, 가능합니다. 성함을 알려주시겠어요?', language: 'en', timestamp: 2 },
        { role: 'user', original_text: 'Harrison 이름으로 부탁드립니다.', translated_text: 'Please make the reservation under Harrison.', language: 'ko', timestamp: 3 },
      ],
    },
    {
      ...DEMO_CALL_RESULT,
      id: 'demo-call-002',
      requestType: 'INQUIRY',
      targetName: '글로벌 민원 안내센터',
      targetPhone: '+1 213-555-9982',
      parsedService: '서류 문의',
      communicationMode: 'text_to_voice',
      durationS: 92,
      createdAt: new Date(now - 2 * 60 * 60_000).toISOString(),
      completedAt: new Date(now - 2 * 60 * 60_000 + 92_000).toISOString(),
      summary: '체류 기간 연장에 필요한 서류와 접수 방법을 확인했습니다.',
      transcriptBilingual: [],
    },
    {
      ...DEMO_CALL_RESULT,
      id: 'demo-call-003',
      requestType: 'AS_REQUEST',
      targetName: '시설 관리센터',
      targetPhone: '02-555-4420',
      status: 'FAILED',
      result: 'NO_ANSWER',
      communicationMode: 'full_agent',
      durationS: 8,
      createdAt: new Date(now - 26 * 60 * 60_000).toISOString(),
      completedAt: new Date(now - 26 * 60 * 60_000 + 8_000).toISOString(),
      summary: '상대방이 응답하지 않아 통화가 연결되지 않았습니다.',
      transcriptBilingual: [],
    },
  ];
}

function formatRelativeDate(dateString: string, yesterday: string, daysAgo: (count: number) => string) {
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return dateString;
  const now = new Date();
  const dayDifference = Math.floor((now.getTime() - date.getTime()) / 86_400_000);
  if (dayDifference <= 0) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  if (dayDifference === 1) return yesterday;
  if (dayDifference < 7) return daysAgo(dayDifference);
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function formatFullDate(dateString: string | null) {
  if (!dateString) return '-';
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return dateString;
  return date.toLocaleString([], {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(seconds?: number | null) {
  if (!seconds) return '-';
  const minutes = Math.floor(seconds / 60);
  const remainder = String(seconds % 60).padStart(2, '0');
  return `${minutes}:${remainder}`;
}

function HistorySkeleton() {
  return (
    <div className="grid gap-1 px-2 py-2" aria-label="통화 기록을 불러오는 중">
      {[0, 1, 2, 3, 4].map((index) => (
        <div key={index} className="flex h-[72px] animate-pulse items-center gap-3 rounded-[9px] px-3">
          <span className="size-9 rounded-[9px] bg-[#EDEAEF]" />
          <span className="min-w-0 flex-1">
            <span className="block h-3 w-3/5 rounded bg-[#E3E0E5]" />
            <span className="mt-2 block h-2.5 w-2/5 rounded bg-[#ECE9EE]" />
          </span>
          <span className="h-5 w-12 rounded-full bg-[#ECE9EE]" />
        </div>
      ))}
    </div>
  );
}

export default function CallHistoryPanel() {
  const router = useRouter();
  const t = useTranslations('history');
  const tc = useTranslations('common');
  const [calls, setCalls] = useState<Call[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Call | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<MobileView>('list');
  const selectedIdRef = useRef<string | null>(null);

  const requestTypeLabel = useCallback((requestType: string) => {
    if (requestType === 'RESERVATION') return t('requestType.reservation');
    if (requestType === 'INQUIRY') return t('requestType.inquiry');
    if (requestType === 'AS_REQUEST') return t('requestType.asRequest');
    return requestType;
  }, [t]);

  const loadCalls = useCallback(async (showLoading = true) => {
    if (showLoading) setListLoading(true);
    setListError(null);
    try {
      let nextCalls: Call[];
      if (isDemoMode()) {
        nextCalls = createDemoHistory();
      } else {
        const response = await fetch('/api/calls', { cache: 'no-store' });
        if (response.status === 401) {
          router.push('/login');
          return;
        }
        if (!response.ok) throw new Error(t('loadFailed'));
        const payload = (await response.json()) as { calls?: Call[] };
        nextCalls = payload.calls ?? [];
      }
      setCalls(nextCalls);

      const currentId = selectedIdRef.current;
      const nextDetail = nextCalls.find((call) => call.id === currentId) ?? nextCalls[0] ?? null;
      selectedIdRef.current = nextDetail?.id ?? null;
      setSelectedId(nextDetail?.id ?? null);
      setDetail(nextDetail);
    } catch (loadError) {
      setListError(loadError instanceof Error ? loadError.message : t('loadFailed'));
    } finally {
      setListLoading(false);
    }
  }, [router, t]);

  useEffect(() => {
    const requestedCallId = new URLSearchParams(window.location.search).get('call');
    selectedIdRef.current = requestedCallId;
    const initialLoad = window.setTimeout(() => {
      if (requestedCallId) setMobileView('detail');
      void loadCalls(false);
    }, 0);
    return () => window.clearTimeout(initialLoad);
  }, [loadCalls]);

  const selectCall = useCallback(async (call: Call) => {
    selectedIdRef.current = call.id;
    setSelectedId(call.id);
    setDetail(call);
    setDetailError(null);
    setDetailLoading(true);
    setMobileView('detail');
    router.replace(`/history?call=${encodeURIComponent(call.id)}`, { scroll: false });
    try {
      if (isDemoMode()) {
        setDetail(call);
        return;
      }
      const response = await fetch(`/api/calls/${call.id}`, { cache: 'no-store' });
      if (response.status === 401) {
        router.push('/login');
        return;
      }
      if (!response.ok) throw new Error(t('detailLoadFailed'));
      const nextDetail = (await response.json()) as Call;
      if (selectedIdRef.current === call.id) setDetail(nextDetail);
    } catch (loadError) {
      if (selectedIdRef.current === call.id) {
        setDetailError(loadError instanceof Error ? loadError.message : t('detailLoadFailed'));
      }
    } finally {
      if (selectedIdRef.current === call.id) setDetailLoading(false);
    }
  }, [router, t]);

  return (
    <section className="ops-page-frame h-[min(720px,calc(100dvh-132px))] min-h-[560px] overflow-hidden border-y border-[#DFDBE2]" aria-label={t('title')}>
      <div className="grid h-full min-h-0 lg:grid-cols-[336px_minmax(0,1fr)]">
        <aside className={cn('min-h-0 min-w-0 overflow-hidden lg:border-r lg:border-[#DFDBE2]', mobileView === 'detail' ? 'hidden lg:flex lg:flex-col' : 'flex flex-col')}>
          <div className="flex min-h-[52px] items-center justify-between gap-3 border-b border-[#DFDBE2] px-3">
            <div className="flex min-w-0 items-center gap-2.5">
              <span className="grid size-8 shrink-0 place-items-center rounded-[8px] bg-[#F3EEF9] text-[#6B2EAA]"><Phone className="size-4" /></span>
              <div className="min-w-0">
                <h2 className="truncate text-sm font-bold text-[#1E1E28]">{t('allCalls')}</h2>
                {!listLoading && !listError && <p className="mt-0.5 text-[10px] text-[#918B98]">{t('totalCount', { count: calls.length })}</p>}
              </div>
            </div>
            <button
              type="button"
              onClick={() => void loadCalls()}
              disabled={listLoading}
              className="grid size-8 shrink-0 place-items-center rounded-[8px] text-[#686375] transition-colors hover:bg-white hover:text-[#1E1E28] disabled:opacity-50"
              aria-label={t('refresh')}
            >
              <RefreshCw className={cn('size-3.5', listLoading && 'animate-spin')} />
            </button>
          </div>

          <div className="styled-scrollbar min-h-0 flex-1 overflow-y-auto">
            {listLoading ? (
              <HistorySkeleton />
            ) : listError ? (
              <StateMessage icon={<AlertTriangle className="size-5" />} tone="error" title={listError} actionLabel={tc('retry')} onAction={() => void loadCalls()} />
            ) : calls.length === 0 ? (
              <StateMessage icon={<Inbox className="size-5" />} title={t('noRecords')} description={t('noRecordsHint')} />
            ) : (
              <div className="grid gap-1 p-2">
                {calls.map((call) => (
                  <HistoryRow
                    key={call.id}
                    call={call}
                    selected={selectedId === call.id}
                    requestType={requestTypeLabel(call.requestType)}
                    relativeDate={formatRelativeDate(call.createdAt, t('yesterday'), (count) => t('daysAgo', { count }))}
                    onSelect={() => void selectCall(call)}
                  />
                ))}
              </div>
            )}
          </div>
        </aside>

        <div className={cn('min-h-0 min-w-0 overflow-hidden', mobileView === 'detail' ? 'flex flex-col' : 'hidden lg:flex lg:flex-col')}>
          {detail ? (
            <CallDetail
              call={detail}
              loading={detailLoading}
              error={detailError}
              requestType={requestTypeLabel(detail.requestType)}
              onBack={() => setMobileView('list')}
              onRetry={() => void selectCall(detail)}
            />
          ) : (
            <StateMessage icon={<Phone className="size-5" />} title={t('selectCall')} description={t('selectCallHint')} grow />
          )}
        </div>
      </div>
    </section>
  );
}

function HistoryRow({
  call,
  selected,
  requestType,
  relativeDate,
  onSelect,
}: {
  call: Call;
  selected: boolean;
  requestType: string;
  relativeDate: string;
  onSelect: () => void;
}) {
  const t = useTranslations('history');
  const isActive = call.status === 'CALLING' || call.status === 'IN_PROGRESS';
  const isPending = call.status === 'PENDING';
  const failed = call.status === 'FAILED';
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'grid min-h-[72px] w-full grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 rounded-[9px] px-3 py-2.5 text-left transition-colors',
        selected ? 'bg-white shadow-[inset_0_0_0_1px_#D9D4DC]' : 'hover:bg-white/70',
      )}
    >
      <span className={cn('grid size-9 place-items-center rounded-[8px]', isActive ? 'bg-[#F3EEF9] text-[#6B2EAA]' : isPending ? 'bg-[#F8F2E7] text-[#8A672B]' : failed ? 'bg-[#FAECEB] text-[#A83C3C]' : 'bg-[#F0EEEF] text-[#686375]')}>
        {isActive ? <PhoneCall className="size-4" /> : isPending ? <Clock3 className="size-4" /> : <PhoneOff className="size-4" />}
      </span>
      <span className="min-w-0">
        <span className="flex items-center gap-2">
          <strong className="truncate text-[13px] text-[#211D24]">{call.targetName || t('unknownTarget')}</strong>
          {isActive && <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-[#9B51E0]" />}
        </span>
        <span className="mt-1 flex items-center gap-1.5 text-[10px] text-[#817A85]">
          <span>{requestType}</span><span className="text-[#CBC5CD]">·</span><span>{relativeDate}</span>
        </span>
      </span>
      <span className="flex items-center gap-2">
        <span className={cn('rounded-full px-2 py-1 text-[9px] font-bold', isActive ? 'bg-[#F3EEF9] text-[#6B2EAA]' : isPending ? 'bg-[#F8F2E7] text-[#8A672B]' : failed ? 'bg-[#FAECEB] text-[#A83C3C]' : 'bg-[#EDF6F1] text-[#247353]')}>
          {isActive ? t('status.inProgress') : isPending ? t('status.pending') : failed ? t('status.failed') : t('status.completed')}
        </span>
        <ChevronRight className="size-3.5 text-[#B8B1BA]" />
      </span>
    </button>
  );
}

function CallDetail({
  call,
  loading,
  error,
  requestType,
  onBack,
  onRetry,
}: {
  call: Call;
  loading: boolean;
  error: string | null;
  requestType: string;
  onBack: () => void;
  onRetry: () => void;
}) {
  const t = useTranslations('history');
  const tc = useTranslations('common');
  const ts = useTranslations('summary');
  const mode = (call.communicationMode ?? 'voice_to_voice') as CommunicationMode;
  const ModeIcon = MODE_ICONS[mode];
  const transcript = call.transcriptBilingual ?? [];
  const statusLabel = call.status === 'FAILED'
    ? t('status.failed')
    : call.status === 'PENDING'
      ? t('status.pending')
      : call.status === 'CALLING' || call.status === 'IN_PROGRESS'
        ? t('status.inProgress')
        : t('status.completed');

  return (
    <>
      <div className="flex min-h-[52px] items-center gap-3 border-b border-[#DFDBE2] px-3 sm:px-4">
        <button type="button" onClick={onBack} className="grid size-8 place-items-center rounded-[8px] text-[#686375] hover:bg-white lg:hidden" aria-label={t('backToList')}>
          <ArrowLeft className="size-4" />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-sm font-bold text-[#1E1E28]">{call.targetName || t('unknownTarget')}</h2>
            <span className="rounded-full bg-[#F0EEEF] px-2 py-0.5 text-[9px] font-bold text-[#686375]">{requestType}</span>
          </div>
          <p className="mt-0.5 text-[10px] text-[#918B98]">{formatFullDate(call.createdAt)}</p>
        </div>
        {loading && <Loader2 className="size-4 animate-spin text-[#6B2EAA]" />}
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {error && (
          <div className="mx-3 mt-3 flex shrink-0 items-center justify-between gap-3 rounded-[9px] bg-[#FAECEB] px-3 py-2.5 text-xs text-[#A83C3C] sm:mx-5">
            <span>{error}</span>
            <button type="button" onClick={onRetry} className="shrink-0 font-bold underline">{tc('retry')}</button>
          </div>
        )}

        <div className="mx-auto grid w-full max-w-3xl shrink-0 gap-3 px-3 py-3 sm:px-5">
          <div className="grid grid-cols-3 divide-x divide-[#DFDBE2] border-y border-[#DFDBE2] py-2">
            <Metric icon={<CheckCircle2 className="size-4" />} label={t('callStatus')} value={statusLabel} />
            <Metric icon={<Clock3 className="size-4" />} label={t('duration')} value={formatDuration(call.durationS)} />
            <Metric icon={<ModeIcon className="size-4" />} label={t('mode')} value={ts(`mode.${MODE_KEYS[mode]}`)} />
          </div>

          <section aria-labelledby="history-info-title">
            <SectionTitle id="history-info-title" icon={<Phone className="size-4" />} title={t('callInfo')} />
            <div className="mt-2 grid grid-cols-2 border-y border-[#E3E0E5] [&>*:nth-child(n+3)]:border-t [&>*:nth-child(odd)]:border-r [&>*]:border-[#E3E0E5]">
              <InfoRow label={t('target')} value={call.targetName || t('unknownTarget')} />
              <InfoRow label={t('phoneNumber')} value={call.targetPhone || '-'} />
              <InfoRow label={t('createdAt')} value={formatFullDate(call.createdAt)} />
              <InfoRow label={t('completedAt')} value={formatFullDate(call.completedAt)} />
            </div>
          </section>

          {call.summary && (
            <section aria-labelledby="history-summary-title">
              <SectionTitle id="history-summary-title" icon={<FileText className="size-4" />} title={t('summary')} />
              <p className="mt-2 rounded-[9px] bg-[#F2EFF3] px-3.5 py-2.5 text-xs leading-5 text-[#4F4953] sm:text-[13px]">{call.summary}</p>
            </section>
          )}
        </div>

        <section className="flex min-h-0 flex-1 flex-col border-t border-[#DFDBE2]" aria-labelledby="history-transcript-title">
          <div className="mx-auto w-full max-w-3xl shrink-0 px-3 py-3 sm:px-5">
            <SectionTitle id="history-transcript-title" icon={<Languages className="size-4" />} title={t('transcript')} meta={t('transcriptHint')} />
          </div>
          <div
            className="styled-scrollbar min-h-0 flex-1 overflow-y-auto bg-[#FAF9FB] px-3 py-4 sm:px-5"
            aria-label={t('transcript')}
            tabIndex={0}
          >
            <div className="mx-auto w-full max-w-3xl">
              {transcript.length > 0 ? (
                <div className="grid gap-3">
                  {transcript.map((entry, index) => <TranscriptBubble key={`${entry.timestamp}-${index}`} entry={entry} />)}
                </div>
              ) : (
                <div className="flex min-h-28 flex-col items-center justify-center gap-2 text-center">
                  <Languages className="size-5 text-[#B5AEB8]" />
                  <p className="text-xs text-[#918B98]">{t('noTranscript')}</p>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </>
  );
}

function TranscriptBubble({ entry }: { entry: TranscriptEntry }) {
  const t = useTranslations('history');
  const isOperator = entry.role === 'user';
  return (
    <div className={cn('flex', isOperator ? 'justify-end' : 'justify-start')}>
      <div className={cn('max-w-[82%] rounded-[12px] px-3.5 py-3', isOperator ? 'bg-[#292632] text-white' : 'border border-[#DFDBE2] bg-white text-[#211D24]')}>
        <p className="text-[10px] font-bold uppercase tracking-[0.08em] opacity-55">{isOperator ? t('operator') : t('recipient')}</p>
        <p className="mt-1 text-sm leading-5">{entry.translated_text || entry.original_text}</p>
        {entry.original_text && entry.translated_text && (
          <p className={cn('mt-2 border-t pt-2 text-[11px] leading-4', isOperator ? 'border-white/15 text-white/55' : 'border-[#EEEAEF] text-[#918B98]')}>{entry.original_text}</p>
        )}
      </div>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="min-w-0 px-2 text-center sm:px-4">
      <span className="mx-auto grid size-7 place-items-center text-[#6B2EAA]">{icon}</span>
      <p className="mt-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[#918B98]">{label}</p>
      <p className="mt-1 truncate text-xs font-bold text-[#312C35]">{value}</p>
    </div>
  );
}

function SectionTitle({ id, icon, title, meta }: { id: string; icon: React.ReactNode; title: string; meta?: string }) {
  return (
    <div className="flex items-center gap-2 text-[#4F4953]">
      {icon}<h3 id={id} className="text-xs font-bold text-[#1E1E28]">{title}</h3>
      {meta && <span className="ml-auto text-[10px] text-[#918B98]">{meta}</span>}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 px-3 py-3">
      <p className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[#918B98]">{label}</p>
      <p className="mt-1 truncate text-xs font-semibold text-[#312C35]">{value}</p>
    </div>
  );
}

function StateMessage({
  icon,
  title,
  description,
  tone = 'neutral',
  actionLabel,
  onAction,
  grow = false,
}: {
  icon: React.ReactNode;
  title: string;
  description?: string;
  tone?: 'neutral' | 'error';
  actionLabel?: string;
  onAction?: () => void;
  grow?: boolean;
}) {
  return (
    <div className={cn('flex min-h-56 flex-col items-center justify-center gap-2 px-5 text-center', grow && 'flex-1')}>
      <span className={cn('grid size-10 place-items-center rounded-[9px]', tone === 'error' ? 'bg-[#FAECEB] text-[#A83C3C]' : 'bg-[#F0EEEF] text-[#817A85]')}>{icon}</span>
      <p className={cn('mt-1 text-sm font-semibold', tone === 'error' ? 'text-[#A83C3C]' : 'text-[#312C35]')}>{title}</p>
      {description && <p className="max-w-xs text-xs leading-5 text-[#918B98]">{description}</p>}
      {actionLabel && onAction && <button type="button" onClick={onAction} className="mt-2 h-8 rounded-[8px] border border-[#D1CCD4] bg-white px-3 text-xs font-bold text-[#5E5861] hover:border-[#BEB8C4]">{actionLabel}</button>}
    </div>
  );
}
