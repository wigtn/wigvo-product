'use client';

import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { type Call } from '@/shared/types';
import { useDashboard } from '@/hooks/useDashboard';
import { useChat } from '@/hooks/useChat';
import { PhoneOff, MapPin, Calendar, Clock, Scissors, FileText, List, Home } from 'lucide-react';

interface ResultCardProps {
  call: Call;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-';
  try {
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      const year = parseInt(parts[0], 10);
      const month = parseInt(parts[1], 10);
      const day = parseInt(parts[2], 10);
      const date = new Date(year, month - 1, day);
      const days = ['일', '월', '화', '수', '목', '금', '토'];
      return `${year}년 ${month}월 ${day}일 (${days[date.getDay()]})`;
    }
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;
    const days = ['일', '월', '화', '수', '목', '금', '토'];
    return `${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일 (${days[date.getDay()]})`;
  } catch {
    return dateStr;
  }
}

function formatTime(timeStr: string | null): string {
  if (!timeStr) return '-';
  try {
    const parts = timeStr.split(':');
    if (parts.length < 2) return timeStr;
    const hours = parseInt(parts[0], 10);
    const minutes = parseInt(parts[1], 10);
    if (isNaN(hours) || isNaN(minutes)) return timeStr;
    const period = hours < 12 ? '오전' : '오후';
    const displayHours = hours % 12 || 12;
    return minutes > 0 ? `${period} ${displayHours}시 ${minutes}분` : `${period} ${displayHours}시`;
  } catch {
    return timeStr;
  }
}

export default function ResultCard({ call }: ResultCardProps) {
  const router = useRouter();
  const t = useTranslations('result');
  const tc = useTranslations('common');
  const { resetCalling, resetDashboard, callingCallId } = useDashboard();
  const { handleNewConversation } = useChat();
  const isInline = !!callingCallId;

  return (
    <div className="flex flex-col items-center gap-4 py-2 sm:gap-5 sm:py-4">
      {/* 통화 종료 헤더 */}
      <div className="flex w-full flex-col items-center gap-3 rounded-[12px] border border-[#E4E1E6] bg-white px-6 py-7 shadow-[0_4px_18px_rgba(33,29,36,0.04)]">
        <div className="flex size-12 items-center justify-center rounded-[12px] bg-[#F5F4F6]">
          <PhoneOff className="size-6 text-[#706A73]" />
        </div>
        <h2 className="text-lg font-bold tracking-[-0.025em] text-[#211D24]">
          {t('callEnded')}
        </h2>
      </div>

      {/* 통화 정보 카드 */}
      {(call.targetName || call.parsedDate || call.parsedTime || call.parsedService) && (
        <div className="w-full overflow-hidden rounded-[12px] border border-[#E4E1E6] bg-white shadow-[0_4px_18px_rgba(33,29,36,0.04)]">
          <div className="border-b border-[#E4E1E6] px-5 py-3.5">
            <h3 className="text-xs font-bold tracking-[-0.01em] text-[#312C35]">{t('callInfo')}</h3>
          </div>
          <div className="px-5 py-4 space-y-4">
            {call.targetName && (
              <InfoRow icon={<MapPin className="size-4" />} label={t('place')} value={call.targetName} />
            )}
            {call.parsedDate && (
              <InfoRow icon={<Calendar className="size-4" />} label={t('date')} value={formatDate(call.parsedDate)} />
            )}
            {call.parsedTime && (
              <InfoRow icon={<Clock className="size-4" />} label={t('time')} value={formatTime(call.parsedTime)} />
            )}
            {call.parsedService && (
              <InfoRow icon={<Scissors className="size-4" />} label={t('service')} value={call.parsedService} />
            )}
          </div>
        </div>
      )}

      {/* AI 요약 */}
      {call.summary && (
        <div className="w-full overflow-hidden rounded-[12px] border border-[#E4E1E6] bg-white shadow-[0_4px_18px_rgba(33,29,36,0.04)]">
          <div className="flex items-center gap-2 border-b border-[#E4E1E6] px-5 py-3.5">
            <FileText className="size-3.5 text-[#9B51E0]" />
            <h3 className="text-xs font-bold tracking-[-0.01em] text-[#312C35]">{t('aiSummary')}</h3>
          </div>
          <div className="px-5 py-4">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-[#4E4851]">
              {call.summary}
            </p>
          </div>
        </div>
      )}

      {/* 액션 버튼 */}
      <div className="flex w-full flex-col gap-2 pt-2">
        <button
          onClick={() => {
            resetCalling();
            router.push('/history');
          }}
          className="flex h-11 w-full items-center justify-center gap-2 rounded-[10px] border border-[#DCD8DF] bg-white text-sm font-semibold text-[#312C35] transition-colors hover:border-[#CDB5DF] hover:bg-[#F8F4FB]"
        >
          <List className="size-4" />
          {t('viewHistory')}
        </button>
        <button
          onClick={async () => {
            resetDashboard();
            await handleNewConversation();
            router.push('/outbound');
          }}
          className="flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-[#1E1E28] text-sm font-semibold text-white transition-colors hover:bg-[#15151E]"
        >
          <Home className="size-4" />
          {isInline ? tc('newChat') : tc('home')}
        </button>
      </div>
    </div>
  );
}

/* ── 서브 컴포넌트 ── */
function InfoRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-[9px] bg-[#F5F0F8] text-[#7B3BB6]">
        {icon}
      </div>
      <div>
        <p className="text-[10px] font-semibold tracking-[0.04em] text-[#8D8691]">{label}</p>
        <p className="text-sm font-semibold text-[#312C35]">{value}</p>
      </div>
    </div>
  );
}
