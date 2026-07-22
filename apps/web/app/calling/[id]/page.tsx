'use client';

import { useParams, useRouter } from 'next/navigation';
import { useState, useEffect, useRef } from 'react';
import { useCallPolling } from '@/hooks/useCallPolling';
import CallingStatus from '@/components/call/CallingStatus';
import OperationsShell from '@/components/layout/OperationsShell';
import { Loader2, AlertTriangle, RefreshCw, Home } from 'lucide-react';

export default function CallingPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { call, loading, error } = useCallPolling(id);
  const [elapsed, setElapsed] = useState(0);
  const hasNavigatedRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isTerminalRef = useRef(false);

  // 경과 시간 카운터
  useEffect(() => {
    timerRef.current = setInterval(() => {
      if (!isTerminalRef.current) {
        setElapsed((prev) => prev + 1);
      }
    }, 1000);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  // 종료 상태시 자동 이동
  useEffect(() => {
    if (!call) return;
    if (hasNavigatedRef.current) return;

    const isTerminal = call.status === 'COMPLETED' || call.status === 'FAILED';
    if (isTerminal) {
      isTerminalRef.current = true;
      hasNavigatedRef.current = true;

      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }

      setTimeout(() => {
        router.push(`/result/${id}`);
      }, 1000);
    }
  }, [call, id, router]);

  if (error) {
    return (
      <OperationsShell active="outbound" title="통화 연결" description="상대방 연결 상태를 확인합니다.">
        <div className="page-card mx-auto flex w-full max-w-md flex-col items-center gap-5 px-5 py-10 text-center">
          <div className="w-14 h-14 rounded-2xl bg-red-50 flex items-center justify-center">
            <AlertTriangle className="size-6 text-red-500" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-[#211D24]">연결 오류</h2>
            <p className="mt-1.5 text-sm text-[#706A73]">{error}</p>
          </div>
          <div className="flex w-full flex-col gap-2">
            <button
              onClick={() => window.location.reload()}
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
    <OperationsShell active="outbound" title="통화 연결" description="상대방 연결 상태를 확인합니다.">
      <div className="mx-auto w-full max-w-md">
        {loading && !call ? (
          <div className="page-card flex flex-col items-center gap-4 py-16">
            <Loader2 className="size-8 animate-spin text-[#9B51E0]" />
            <p className="text-sm text-[#706A73]">통화 정보를 불러오는 중...</p>
          </div>
        ) : (
          <CallingStatus call={call} elapsed={elapsed} />
        )}
      </div>
    </OperationsShell>
  );
}
