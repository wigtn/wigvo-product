'use client';

import { useRouter } from 'next/navigation';
import { Phone, Calendar, HelpCircle, Search, ChevronRight, Inbox } from 'lucide-react';
import { type Call, type CallStatus } from '@/shared/types';
import type { ReactNode } from 'react';

interface HistoryListProps {
  calls: Call[];
}

interface StatusBadge {
  label: string;
  dotColor: string;
  bg: string;
  text: string;
}

function getStatusBadge(status: CallStatus): StatusBadge {
  if (status === 'COMPLETED') {
    return { label: '완료', dotColor: 'bg-[#247353]', bg: 'bg-[#EDF6F1]', text: 'text-[#247353]' };
  }
  if (status === 'FAILED') {
    return { label: '실패', dotColor: 'bg-[#A83C3C]', bg: 'bg-[#FAECEB]', text: 'text-[#A83C3C]' };
  }
  if (status === 'CALLING' || status === 'IN_PROGRESS') {
    return { label: '통화 중', dotColor: 'bg-[#9B51E0] animate-pulse', bg: 'bg-[#F3EEF9]', text: 'text-[#6B2EAA]' };
  }
  return { label: '대기', dotColor: 'bg-[#9A5D16]', bg: 'bg-[#FBF1DE]', text: 'text-[#9A5D16]' };
}

function getRequestTypeLabel(type: string): string {
  switch (type) {
    case 'RESERVATION': return '예약';
    case 'INQUIRY': return '문의';
    case 'CONFIRMATION': return '확인';
    default: return type;
  }
}

function getRequestTypeIcon(type: string): ReactNode {
  switch (type) {
    case 'RESERVATION': return <Calendar className="size-4 text-[#6B2EAA]" />;
    case 'INQUIRY': return <HelpCircle className="size-4 text-[#6B2EAA]" />;
    case 'CONFIRMATION': return <Search className="size-4 text-[#6B2EAA]" />;
    default: return <Phone className="size-4 text-[#6B2EAA]" />;
  }
}

function formatCreatedAt(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${month}/${day} ${hours}:${minutes}`;
  } catch {
    return dateStr;
  }
}

function getNavigationTarget(call: Call): string {
  if (call.status === 'COMPLETED' || call.status === 'FAILED') {
    return `/result/${call.id}`;
  }
  return `/calling/${call.id}`;
}

export default function HistoryList({ calls }: HistoryListProps) {
  const router = useRouter();

  if (calls.length === 0) {
    return (
      <div className="flex min-h-56 flex-col items-center justify-center gap-2 px-6 text-center">
        <div className="mb-1 flex size-11 items-center justify-center rounded-[10px] bg-[#F3EEF9]">
          <Inbox className="size-5 text-[#6B2EAA]" />
        </div>
        <p className="text-sm font-semibold text-[#1E1E28]">아직 통화 기록이 없습니다</p>
        <p className="text-xs text-[#9A939E]">아웃바운드에서 전화를 시작해보세요</p>
      </div>
    );
  }

  return (
    <div>
      {calls.map((call) => {
        const badge = getStatusBadge(call.status);
        const icon = getRequestTypeIcon(call.requestType);
        return (
          <button
            key={call.id}
            onClick={() => router.push(getNavigationTarget(call))}
            className="ops-list-row grid w-full grid-cols-[40px_minmax(0,1fr)_auto_auto] items-center gap-3 border-b border-[#E3E0E8] bg-transparent text-left transition-colors last:border-b-0 hover:bg-white/60 active:bg-white"
          >
            {/* 아이콘 */}
            <div className="flex size-10 shrink-0 items-center justify-center rounded-[9px] bg-[#F3EEF9]">
              {icon}
            </div>

            {/* 정보 */}
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="truncate text-sm font-bold text-[#211D24]">{call.targetName}</span>
              <div className="flex items-center gap-1.5 text-[11px] text-[#706A73]">
                <span>{getRequestTypeLabel(call.requestType)}</span>
                <span className="text-[#CFC9D1]">·</span>
                <span>{formatCreatedAt(call.createdAt)}</span>
              </div>
            </div>

            {/* 상태 뱃지 */}
            <div className={`flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 ${badge.bg}`}>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${badge.dotColor}`} />
              <span className={`text-[10px] font-bold ${badge.text}`}>{badge.label}</span>
            </div>

            {/* 화살표 */}
            <ChevronRight className="size-4 shrink-0 text-[#B8B1BA]" />
          </button>
        );
      })}
    </div>
  );
}
