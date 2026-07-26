// =============================================================================
// Demo Mode — Mock API Functions
// =============================================================================
// lib/api.ts 와 동일한 인터페이스, Mock 데이터 반환
// =============================================================================

import type {
  Conversation,
  ChatResponse,
  Call,
  CreateConversationResponse,
  Message,
} from '@/shared/types';
import type { CommunicationMode } from '@/shared/call-types';
import {
  DEMO_CONVERSATION_ID,
  DEMO_CONVERSATION,
  DEMO_CHAT_SEQUENCE,
  DEMO_CALL_ID,
  DEMO_CALL,
  DEMO_CALL_START_RESPONSE,
  DEMO_CALL_RESULT,
  DEMO_USER_ID,
} from './mock-data';

// --- State: 채팅 step 카운터 (몇 번째 메시지인지 추적) ---
let chatStepIndex = 0;
let demoMessages: Message[] = [];

/** 데모 리셋 (새 대화 시작 시) */
export function resetDemoState(): void {
  chatStepIndex = 0;
  demoMessages = [];
}

// --- Mock API Functions ---

export async function mockCreateConversation(): Promise<CreateConversationResponse> {
  resetDemoState();
  // 300ms 지연으로 자연스러운 로딩 표현
  await delay(300);
  const createdAt = new Date().toISOString();
  if (DEMO_CONVERSATION.greeting) {
    demoMessages = [{
      id: `greeting-${DEMO_CONVERSATION_ID}`,
      role: 'assistant',
      content: DEMO_CONVERSATION.greeting,
      createdAt,
    }];
  }
  return { ...DEMO_CONVERSATION, createdAt };
}

export async function mockGetConversation(id: string): Promise<Conversation> {
  await delay(200);
  if (demoMessages.length === 0 && DEMO_CONVERSATION.greeting) {
    demoMessages = [{
      id: `greeting-${DEMO_CONVERSATION_ID}`,
      role: 'assistant',
      content: DEMO_CONVERSATION.greeting,
      createdAt: new Date().toISOString(),
    }];
  }
  const lastChat = DEMO_CHAT_SEQUENCE[Math.min(chatStepIndex - 1, DEMO_CHAT_SEQUENCE.length - 1)];
  return {
    id: id || DEMO_CONVERSATION_ID,
    userId: DEMO_USER_ID,
    status: lastChat?.conversation_status ?? 'COLLECTING',
    collectedData: lastChat?.collected ?? DEMO_CONVERSATION.collectedData,
    messages: [...demoMessages],
    createdAt: DEMO_CONVERSATION.createdAt,
    updatedAt: new Date().toISOString(),
  };
}

export async function mockSendChatMessage(
  _conversationId: string,
  message: string,
  _communicationMode?: CommunicationMode,
  _locale?: string,
): Promise<ChatResponse> {
  demoMessages.push({
    id: `user-${chatStepIndex + 1}`,
    role: 'user',
    content: message,
    createdAt: new Date().toISOString(),
  });

  // 실제 chat-service와 동일하게 직통 통화 모드는 전화번호만 수집하면
  // 예약 시나리오 대화를 건너뛰고 바로 통화 준비 상태로 전환한다.
  if (_communicationMode && _communicationMode !== 'full_agent') {
    const compactPhone = message.trim().replace(/[\s()-]/g, '');
    if (/^\+[1-9]\d{7,14}$/.test(compactPhone)) {
      const response: ChatResponse = {
        message: _locale === 'ko'
          ? `${compactPhone}(으)로 전화를 걸 준비가 되었어요! 전화 걸기 버튼을 눌러주세요.`
          : `Ready to call ${compactPhone}! Press the call button to start.`,
        collected: {
          target_name: compactPhone,
          target_phone: compactPhone,
          scenario_type: 'INQUIRY',
          scenario_sub_type: 'OTHER',
          primary_datetime: null,
          service: null,
          fallback_datetimes: [],
          fallback_action: null,
          customer_name: null,
          party_size: null,
          special_request: null,
          source_language: 'ko',
          target_language: 'en',
        },
        is_complete: true,
        conversation_status: 'READY',
      };

      await delay(500);
      demoMessages.push({
        id: `assistant-ready-${Date.now()}`,
        role: 'assistant',
        content: response.message,
        createdAt: new Date().toISOString(),
      });
      return response;
    }
  }

  // 현재 step의 응답 반환
  const step = Math.min(chatStepIndex, DEMO_CHAT_SEQUENCE.length - 1);
  const response = DEMO_CHAT_SEQUENCE[step];
  chatStepIndex++;

  // 자연스러운 타이핑 지연 (800ms ~ 1.5s)
  await delay(800 + Math.random() * 700);
  demoMessages.push({
    id: `assistant-${chatStepIndex}`,
    role: 'assistant',
    content: response.message,
    createdAt: new Date().toISOString(),
  });
  return { ...response };
}

export async function mockCreateCall(): Promise<Call> {
  await delay(400);
  return { ...DEMO_CALL, createdAt: new Date().toISOString() };
}

export async function mockStartCall(): Promise<{
  success: boolean;
  callId: string;
  relayWsUrl?: string;
  callSid?: string;
}> {
  await delay(600);
  return { ...DEMO_CALL_START_RESPONSE };
}

export async function mockGetCall(id: string): Promise<Call> {
  await delay(200);
  // 통화 완료된 상태 반환
  return { ...DEMO_CALL_RESULT, id: id || DEMO_CALL_ID };
}

// --- Utility ---

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
