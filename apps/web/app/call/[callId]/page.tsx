'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { getCall } from '@/lib/api';
import type { Call } from '@/shared/types';
import type { CallMode, CommunicationMode } from '@/shared/call-types';
import RealtimeCallView from '@/components/call/RealtimeCallView';
import ResultCard from '@/components/call/ResultCard';
import OperationsShell from '@/components/layout/OperationsShell';

const callDescription = '통화 연결 상태를 확인하고 실시간으로 응대합니다.';

export default function CallPage() {
  const params = useParams();
  const router = useRouter();
  const callId = params.callId as string;
  const [call, setCall] = useState<Call | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [callEnded, setCallEnded] = useState(false);

  useEffect(() => {
    if (!callId) return;

    async function fetchCall() {
      try {
        const data = await getCall(callId);
        setCall(data as unknown as Call);
      } catch (fetchError) {
        setError(fetchError instanceof Error ? fetchError.message : 'Failed to load call');
      } finally {
        setLoading(false);
      }
    }

    void fetchCall();
  }, [callId]);

  const handleCallEnd = () => {
    setCallEnded(true);
    void getCall(callId)
      .then((data) => setCall(data as unknown as Call))
      .catch(() => undefined);
  };

  if (loading) {
    return (
      <OperationsShell active="outbound" title="아웃바운드 통화" description={callDescription}>
        <div className="page-card mx-auto flex max-w-md flex-col items-center gap-3 py-14">
          <Loader2 className="size-6 animate-spin text-[#9B51E0]" />
          <p className="text-sm text-[#706A73]">통화 정보를 불러오는 중...</p>
        </div>
      </OperationsShell>
    );
  }

  if (error || !call) {
    return (
      <OperationsShell active="outbound" title="아웃바운드 통화" description={callDescription}>
        <div className="page-card mx-auto max-w-md px-6 py-12 text-center">
          <p className="mb-2 text-sm text-red-500">{error ?? '통화를 찾을 수 없습니다'}</p>
          <button type="button" onClick={() => router.push('/')} className="text-sm text-[#706A73] underline hover:text-[#6B2EAA]">
            홈으로 돌아가기
          </button>
        </div>
      </OperationsShell>
    );
  }

  const isTerminal = call.status === 'COMPLETED' || call.status === 'FAILED';
  if (isTerminal || callEnded) {
    return (
      <OperationsShell active="history" title="통화 결과" description="종료된 통화의 결과와 요약을 확인합니다.">
        <div className="mx-auto w-full max-w-2xl">
          <ResultCard call={call} />
        </div>
      </OperationsShell>
    );
  }

  if (!call.relayWsUrl) {
    return (
      <OperationsShell active="outbound" title="아웃바운드 통화" description={callDescription}>
        <div className="page-card mx-auto max-w-md px-6 py-12 text-center">
          <p className="text-sm text-[#706A73]">통화 연결 정보가 없습니다</p>
          <button type="button" onClick={() => router.push('/')} className="mt-2 text-sm text-[#706A73] underline hover:text-[#6B2EAA]">
            홈으로 돌아가기
          </button>
        </div>
      </OperationsShell>
    );
  }

  return (
    <OperationsShell
      active="outbound"
      title="아웃바운드 통화"
      description={call.targetName ? `${call.targetName} 통화 중` : '실시간 통화 중'}
      workspace
    >
      <div className="h-full min-h-0">
        <RealtimeCallView
          callId={callId}
          relayWsUrl={call.relayWsUrl}
          callMode={(call.callMode as CallMode) ?? 'agent'}
          communicationMode={(call.communicationMode as CommunicationMode) ?? 'voice_to_voice'}
          targetName={call.targetName}
          onCallEnd={handleCallEnd}
        />
      </div>
    </OperationsShell>
  );
}
