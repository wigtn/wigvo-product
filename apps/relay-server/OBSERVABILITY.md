# WIGVO Tracing 필수 항목 (Langfuse)

모든 통화는 Langfuse trace로 남는다 (키 미설정 시 no-op). 이 문서는 **반드시 존재해야 하는
필드**의 규약이다 — MEGA Loop(평가/데이터 루프)이 이 스키마를 그대로 소비한다.
새 파이프라인 단계를 추가할 때 여기 항목이 비면 트레이싱 누락으로 간주한다.

## 통화(trace 루트) — `start_call`
| 필드 | 값 | 용도 |
|---|---|---|
| `call_id` / `call_sid` | 식별자 | 로그·DB 조인 |
| `flow` | `inbound` \| `outbound` | **방향 슬라이싱 키** |
| `tenant_id` | UUID 문자열 | **테넌트 슬라이싱 키** |
| `mode` | communication_mode | v2v/t2v 구분 |
| `source_language` / `target_language` | 언어쌍 | 평가 라우팅 |

## 턴(generation) — `record_turn`
Session A(응대측)·Session B(발신측) 발화마다 1개.
| 필드 | 내용 |
|---|---|
| `input` / `output` | STT 원문 / 번역 출력 (**MEGA Loop 평가 페어**) |
| `direction` | `caller_to_callee` \| `callee_to_caller` |
| `latency.total_ms` (+`latency.stt_ms`, `latency.processing_ms` 등) | 레이턴시 분해 |
| `stage.*` | 파이프라인 단계 신호 (echo gate, VAD 등) |

## 이벤트(event) — `record_event`
품질 사건은 전부 이벤트로 남긴다 (데이터셋의 네거티브 라벨 소스):
| 이벤트 | 위치 | metadata |
|---|---|---|
| 🚫 Caller STT hallucination filtered | session_a | `text` (필터된 원문) |
| 🛡 Guardrail triggered | voice_to_voice | guardrail event_data (level 등) |
| ⚡ SessionA commit skipped (low energy) | voice_to_voice | `peak_rms`, `min_peak_rms` |
| (Session B translation hallucination blocked) | session_b | 기존 |
| 📥 Inbound handoff | inbound/media | `settling_s`, `prebuffer_frames_replayed` |

## 제어흐름 스팬 — `flow_span` (PII 금지, `_safe_attrs` 강제)
| 스팬 | 커버 |
|---|---|
| `calls.dual_session.connect` | 아웃바운드 세션 생성 |
| `inbound.pickup` | claim→bootstrap→CONNECTED 전체 |
| `inbound.dual_session.connect` | 인바운드 세션 생성 |

## MEGA Loop 연결
- 소비 단위 = **턴 generation** (`input`/`output` + `latency.*` + trace 루트의
  `flow`/`tenant_id`/언어쌍) — 번역 품질 평가 페어로 바로 사용 가능.
- 이벤트는 네거티브 샘플 라벨(할루시/차단/스킵) 소스.
- export는 Langfuse API(트레이스 조회)로 배치 추출 → 평가 파이프라인 입력. (커넥터는 후속.)

## 프라이버시 주의
`record_turn`/`record_event`는 전사 내용을 포함한다(기존 정책 — pilot-readiness §2.3의
별도 트랙에서 보존기간·마스킹 관리). `flow_span` attr에는 내용 금지(denylist 강제).
