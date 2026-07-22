'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, History, Loader2, RefreshCw } from 'lucide-react';
import OperationsShell from '@/components/layout/OperationsShell';
import HistoryList from '@/components/call/HistoryList';
import type { Call } from '@/shared/types';
import { isDemoMode } from '@/lib/demo';

export default function HistoryPage() {
  const router = useRouter();
  const [calls, setCalls] = useState<Call[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;

    async function fetchCalls() {
      try {
        const res = await fetch('/api/calls');
        if (res.status === 401) {
          if (isDemoMode()) {
            setCalls([]);
            setLoading(false);
            return;
          }
          router.push('/login');
          return;
        }
        if (!res.ok) {
          setError('기록을 불러오는 데 실패했습니다.');
          setLoading(false);
          return;
        }
        const data = await res.json();
        setCalls(data.calls || []);
        setLoading(false);
      } catch {
        setError('네트워크 오류가 발생했습니다.');
        setLoading(false);
      }
    }

    void fetchCalls();
  }, [router]);

  return (
    <OperationsShell active="history" title="통화 기록" description="인바운드와 아웃바운드 통화 결과를 한곳에서 확인하세요.">
      <div className="ops-page-frame">
        <section>
          <div className="ops-panel-header">
            <div className="flex items-center gap-2.5">
              <span className="grid size-8 place-items-center rounded-lg bg-[#F3EEF9] text-[#6B2EAA]"><History className="size-4" /></span>
              <h2 className="text-sm font-bold text-[#1E1E28]">전체 통화</h2>
            </div>
            {!loading && !error && <span className="text-xs font-medium text-[#918B98]">{calls.length}건</span>}
          </div>

          {loading ? (
            <div className="flex min-h-56 flex-col items-center justify-center gap-3">
              <Loader2 className="size-5 animate-spin text-[#6B2EAA]" />
              <p className="text-sm text-[#706A73]">기록을 불러오는 중...</p>
            </div>
          ) : error ? (
            <div className="flex min-h-56 flex-col items-center justify-center gap-3 px-6 text-center">
              <div className="grid size-11 place-items-center rounded-[10px] bg-[#FAECEB]"><AlertTriangle className="size-5 text-[#A83C3C]" /></div>
              <div>
                <p className="text-sm font-semibold text-[#A83C3C]">{error}</p>
                <p className="mt-1 text-xs text-[#8A838D]">인터넷 연결을 확인해주세요.</p>
              </div>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="inline-flex h-9 items-center gap-2 rounded-[8px] border border-[#D1CCD4] bg-white px-3 text-xs font-semibold text-[#5F5A68] hover:border-[#BEB8C4] hover:bg-[#F7F5F8] hover:text-[#1E1E28]"
              >
                <RefreshCw className="size-3.5" />
                새로고침
              </button>
            </div>
          ) : (
            <HistoryList calls={calls} />
          )}
        </section>
      </div>
    </OperationsShell>
  );
}
