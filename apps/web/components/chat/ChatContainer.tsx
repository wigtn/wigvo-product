"use client";

import { useRef, useEffect, useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useChat } from "@/hooks/useChat";
import { useDashboard } from "@/hooks/useDashboard";
import { useRelayCallStore } from "@/hooks/useRelayCallStore";
import ChatMessage from "./ChatMessage";
import CaptionMessage from "./CaptionMessage";
import CallStatusMessage from "./CallStatusMessage";
import CallChatInput from "./CallChatInput";
import ChatInput, { type ChatInputHandle } from "./ChatInput";
import CollectionSummary from "./CollectionSummary";

import ScenarioSelector from "./ScenarioSelector";
import { Phone, Loader2, Plus } from "lucide-react";

function formatDuration(seconds: number): string {
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(Math.floor(seconds % 60)).padStart(2, "0");
  return `${mm}:${ss}`;
}

export default function ChatContainer() {
  const {
    messages,
    collectedData,
    isComplete,
    conversationStatus,
    isLoading,
    isInitializing,
    scenarioSelected,
    communicationMode,
    handleScenarioSelect,
    sendMessage,
    handleConfirm,
    handleEdit,
    handleNewConversation,
    error,
  } = useChat();

  const t = useTranslations("chat");
  const tc = useTranslations("common");

  const { callingCallId, callingCommunicationMode } = useDashboard();
  const isCalling = !!callingCallId;

  // Relay call store (통화 중 자막/상태 + Call 메타데이터)
  const {
    captions,
    callStatus,
    translationState,
    callDuration,
    sendText,
    sendTypingState,
    callData: call,
  } = useRelayCallStore();

  // 통화 끝났는지 판별 (입력 활성화용)
  const isCallEnded = callStatus === 'ended';
  const isCallActive = isCalling && !isCallEnded;
  const isTextMode = callingCommunicationMode === 'text_to_voice';
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatInputRef = useRef<ChatInputHandle>(null);
  const prevLoadingRef = useRef(isLoading);

  // 스크롤 + 포커스 (iOS 키보드 올라와도 동작하도록 scrollTop 직접 제어)
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (el) {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    }
  }, [messages, isLoading, captions.length, callStatus]);

  // iOS 키보드 열림/닫힘 시 스크롤 보정
  const scrollToBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (el) {
      requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
    }
  }, []);

  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    vv.addEventListener("resize", scrollToBottom);
    return () => vv.removeEventListener("resize", scrollToBottom);
  }, [scrollToBottom]);

  // AI 답변 완료 후 입력창 자동 포커스
  useEffect(() => {
    if (prevLoadingRef.current && !isLoading && !isComplete && !isCallActive) {
      chatInputRef.current?.focus();
    }
    prevLoadingRef.current = isLoading;
  }, [isLoading, isComplete, isCallActive]);

  // AI 음성 자막 제외 (사용자 입력의 번역이므로 중복 표시 불필요)
  const visibleCaptions = useMemo(
    () => captions.filter((entry) => entry.speaker !== 'ai' && entry.stage !== 1),
    [captions],
  );

  if (isInitializing) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <Loader2 className="size-8 animate-spin text-[#6B2EAA]" />
        <p className="text-sm text-[#706A73]">{t("loadingConversation")}</p>
      </div>
    );
  }

  // 시나리오 선택 화면
  if (!scenarioSelected) {
    return (
      <div className="flex flex-col h-full bg-transparent">
        <div className="flex-1 overflow-y-auto styled-scrollbar">
          <ScenarioSelector
            onSelect={handleScenarioSelect}
            disabled={isLoading}
          />
        </div>
        {error && (
          <div className="mx-4 mb-4 text-center">
            <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">
              {error}
            </p>
          </div>
        )}
        {isLoading && (
          <div className="flex justify-center pb-4">
            <Loader2 className="size-5 animate-spin text-[#6B2EAA]" />
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-transparent">
      {/* 채팅 헤더 - 새 대화 버튼 */}
      <div className="flex min-h-[58px] shrink-0 items-center justify-between border-b border-[#E4E1E6] px-4">
        <div className="flex items-center gap-2">
          <span className="grid size-8 place-items-center rounded-lg bg-[#F3EEF9] text-[#6B2EAA]"><Phone className="size-3.5" /></span>
          <span className="text-xs font-bold text-[#312C35]">{isCalling ? t("liveContent") : t("header")}</span>
        </div>
        <button
          type="button"
          onClick={handleNewConversation}
          disabled={isLoading || isCallActive}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-[#8A838D] transition-colors hover:bg-[#F3EEF9] hover:text-[#6B2EAA] disabled:opacity-40"
        >
          <Plus className="size-3.5" />
          {tc("newChat")}
        </button>
      </div>

      {/* 메시지 영역 */}
      <div ref={scrollContainerRef} className="styled-scrollbar flex-1 overflow-y-auto bg-[#F8F7F9] px-4 pb-2 pt-5 sm:px-5">
        {/* 기존 채팅 메시지 */}
        {messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
        ))}

        {/* 로딩 (비통화 중) */}
        {isLoading && !isCalling && (
          <div className="flex justify-start mb-3">
            <div className="max-w-[80%] rounded-2xl rounded-bl-md border border-[#E4E1E6] bg-white px-4 py-2.5">
              <div className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-[#6B2EAA]">
                {tc("agent")}
              </div>
              <div className="flex items-center gap-1 text-sm text-[#8A838D]">
                <span className="animate-bounce" style={{ animationDelay: "0ms" }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: "150ms" }}>.</span>
                <span className="animate-bounce" style={{ animationDelay: "300ms" }}>.</span>
                <span className="ml-1">{t("typing")}</span>
              </div>
            </div>
          </div>
        )}

        {/* === 통화 인라인 자막 영역 === */}
        {isCalling && (
          <>
            {/* 통화 시작 상태 메시지 */}
            {(callStatus === 'connecting' || callStatus === 'waiting') && (
              <CallStatusMessage
                type="connecting"
                targetName={call?.targetName}
                isActive={callStatus === 'connecting' || callStatus === 'waiting'}
              />
            )}

            {/* 연결됨 상태 메시지 */}
            {callStatus === 'connected' && (
              <CallStatusMessage type="connected" />
            )}

            {/* 실시간 자막 */}
            {visibleCaptions.map((entry) => (
              <CaptionMessage key={entry.id} entry={entry} />
            ))}

            {/* 번역 중 타이핑 인디케이터 */}
            {translationState === 'processing' && (
              <div className="flex justify-start mb-3">
                <div className="rounded-2xl rounded-bl-md border border-[#E4E1E6] bg-white px-4 py-2">
                  <p className="animate-pulse text-xs text-[#8A838D]">
                    Translating...
                  </p>
                </div>
              </div>
            )}

            {/* 통화 종료 상태 메시지 */}
            {isCallEnded && (
              <CallStatusMessage
                type="ended"
                duration={formatDuration(callDuration)}
              />
            )}

          </>
        )}

        {/* 에러 */}
        {error && (
          <div className="mb-3 text-center">
            <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 inline-block">
              {error}
            </p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 수집 완료 시 요약 카드 */}
      {!isCalling && collectedData && (isComplete || conversationStatus === "READY") && (
        <div className="shrink-0">
          <CollectionSummary
            data={collectedData}
            communicationMode={communicationMode}
            onConfirm={handleConfirm}
            onEdit={handleEdit}
            onNewConversation={handleNewConversation}
            isLoading={isLoading}
          />
        </div>
      )}

      {/* 입력 영역: 모드별 전환 */}
      <div className="shrink-0">
        {isCallActive && isTextMode ? (
          <CallChatInput
            onSend={(text) => sendText?.(text)}
            onTypingStart={() => sendTypingState?.()}
            disabled={callStatus !== 'connected'}
          />
        ) : (
          <ChatInput
            ref={chatInputRef}
            onSend={sendMessage}
            disabled={isLoading || isComplete || isCallActive}
            placeholder={
              isCallActive
                ? t("callingPlaceholder")
                : isComplete
                  ? t("completePlaceholder")
                  : t("placeholder")
            }
          />
        )}
      </div>
    </div>
  );
}
