'use client';

import { useEffect } from 'react';
import OperationsShell from '@/components/layout/OperationsShell';
import CallHistoryPanel from '@/components/call/CallHistoryPanel';
import { useDashboard } from '@/hooks/useDashboard';

export default function HistoryPage() {
  useEffect(() => {
    useDashboard.getState().resetCalling();
  }, []);

  return (
    <OperationsShell active="history" title="통화 기록" description="통화 목록을 유지한 채 결과와 실시간 번역 내용을 확인하세요.">
      <CallHistoryPanel />
    </OperationsShell>
  );
}
