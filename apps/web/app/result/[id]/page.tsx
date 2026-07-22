'use client';

import { useParams, useRouter } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import ResultCard from '@/components/call/ResultCard';
import OperationsShell from '@/components/layout/OperationsShell';
import { Loader2, AlertTriangle, RefreshCw, Home } from 'lucide-react';
import type { Call } from '@/shared/types';

export default function ResultPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [call, setCall] = useState<Call | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;

    async function fetchCall() {
      try {
        const res = await fetch(`/api/calls/${id}`);

        if (res.status === 401) {
          router.push('/login');
          return;
        }

        if (res.status === 404) {
          setError('통화 기록을 찾을 수 없습니다.');
          setLoading(false);
          return;
        }

        if (!res.ok) {
          setError('데이터를 불러오는 데 실패했습니다.');
          setLoading(false);
          return;
        }

        const data: Call = await res.json();
        setCall(data);
        setLoading(false);
      } catch {
        setError('네트워크 오류가 발생했습니다.');
        setLoading(false);
      }
    }

    fetchCall();
  }, [id, router]);

  if (loading) {
    return (
      <OperationsShell active="history" title="통화 결과" description="종료된 통화의 결과와 요약을 확인합니다.">
        <div className="page-card max-w-md flex flex-col items-center gap-4 py-16">
          <Loader2 className="size-6 animate-spin text-[#9B51E0]" />
          <p className="text-sm text-[#706A73]">결과를 불러오는 중...</p>
        </div>
      </OperationsShell>
    );
  }

  if (error || !call) {
    return (
      <OperationsShell active="history" title="통화 결과" description="종료된 통화의 결과와 요약을 확인합니다.">
        <div className="page-card mx-auto flex w-full max-w-md flex-col items-center gap-5 px-5 py-10 text-center">
          <div className="w-14 h-14 rounded-2xl bg-red-50 flex items-center justify-center">
            <AlertTriangle className="size-6 text-red-500" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-[#211D24]">오류 발생</h2>
            <p className="mt-1.5 text-sm text-[#706A73]">
              {error || '알 수 없는 오류가 발생했습니다.'}
            </p>
          </div>
          <div className="flex w-full flex-col gap-2">
            <button
              onClick={() => {
                fetchedRef.current = false;
                setLoading(true);
                setError(null);
                window.location.reload();
              }}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-[#1E1E28] text-sm font-semibold text-white transition-colors hover:bg-[#15151E]"
            >
              <RefreshCw className="size-4" />
              다시 시도
            </button>
            <button
              onClick={() => router.push('/')}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-[10px] text-sm font-semibold text-[#706A73] transition-colors hover:bg-[#F5F0F8] hover:text-[#6B2EAA]"
            >
              <Home className="size-4" />
              홈으로 돌아가기
            </button>
          </div>
        </div>
      </OperationsShell>
    );
  }

  return (
    <OperationsShell active="history" title="통화 결과" description="종료된 통화의 결과와 요약을 확인합니다.">
      <div className="mx-auto w-full max-w-2xl">
        <ResultCard call={call} />
      </div>
    </OperationsShell>
  );
}
