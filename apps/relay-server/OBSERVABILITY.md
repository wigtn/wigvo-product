# WIGVO Tracing 필수 항목 (Langfuse)

모든 통화는 Langfuse trace로 남는다 (키 미설정 시 no-op). 이 문서는 **반드시 존재해야 하는
필드**의 규약이다 — MEGA Loop(평가/데이터 루프)이 이 스키마를 그대로 소비한다.
새 파이프라인 단계를 추가할 때 여기 항목이 비면 트레이싱 누락으로 간주한다.

## 환경 분리 (선결 조건)

모든 trace는 `environment` 태그를 갖는다. **부하·개발 트래픽과 실사용을 섞으면
품질 기준선도 평가셋도 신뢰할 수 없다** — 실측으로 확인된 문제다: 프로덕션에
쌓인 통화 300건 중 297건이 비용 0원인 부하 트래픽이었고 실사용은 3건뿐이었다.

| 값 | 언제 |
|---|---|
| `production` | 기본값 (`LANGFUSE_ENVIRONMENT`) |
| `load-test` | `LOAD_TEST_MODE=true`면 설정값과 **무관하게 강제** — 하네스 쪽이 환경변수를 빠뜨려도 실사용 데이터가 오염되지 않도록 |
| 임의 값 | `staging` 등. 소문자·숫자·`.-_`만 허용하고 `langfuse` 접두사는 예약 — 위반 시 `production`으로 대체 |

**MEGA Loop·품질 대시보드는 `environment=production`만 소비할 것.**

> 남은 구멍: 팀원이 프로덕션에서 수동으로 거는 테스트 통화는 프로세스 단위로
> 구분되지 않아 `production`으로 기록된다. 필요해지면 테넌트/헤더 기반 태깅을
> 추가한다.

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

## 오역 측정 (`scripts/translation_quality_eval.py`)

턴의 `input`(원문)/`output`(번역)을 LLM judge로 채점해 **의미 보존 여부**를 잰다.
사용자 피해가 가장 큰 실패(오역)를 겨냥하며, 사람 라벨 없이 프로덕션 데이터에
바로 적용된다.

**judge를 먼저 검증하고 쓸 것** — `--validate`로 정답을 아는 사례를 돌린다.
검증 안 된 측정도구로 결론을 내면 far-field 합성 하네스와 같은 실수를 반복한다.

| 지표 | 검증 결과(n=11) | 사용 |
|---|---|---|
| 문제 유무 + 심각도 | 11/11 | **주 지표** |
| 카테고리 세분 | 7/11 | 참고용 — 카테고리 간 의미가 겹쳐 흔들림 |

⚠️ 번역이 gpt-4o 계열 산출물인데 judge도 같은 계열이라 **자기선호 편향** 가능성이
있다. 추세를 근거로 삼기 전에 다른 계열로 교차검증할 것.

## MEGA Loop 연결
- 소비 단위 = **턴 generation** (`input`/`output` + `latency.*` + trace 루트의
  `flow`/`tenant_id`/언어쌍) — 번역 품질 평가 페어로 바로 사용 가능.
- 이벤트는 네거티브 샘플 라벨(할루시/차단/스킵) 소스.
- export는 Langfuse API(트레이스 조회)로 배치 추출 → 평가 파이프라인 입력. (커넥터는 후속.)

## 프라이버시 주의
`record_turn`/`record_event`는 전사 내용을 포함한다(기존 정책 — pilot-readiness §2.3의
별도 트랙에서 보존기간·마스킹 관리). `flow_span` attr에는 내용 금지(denylist 강제).
