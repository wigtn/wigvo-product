"""오역 측정 — 프로덕션 턴의 의미 보존 여부를 채점한다.

왜 이걸 만드는가:
  사용자 피해가 가장 큰 실패는 '오역'(의미가 바뀜)인데 지금까지 측정이 전무했다.
  실제 사례: "How many times you poop?" → "몇 번이나 넣었어?" (의미 소실),
  STT가 깨진 짧은 발화를 번역이 맥락으로 지어낸 사례(원문에 없는 내용 생성).
  Langfuse에 원문/번역 쌍이 쌓이므로 사람 라벨 없이 바로 채점할 수 있다.

설계 원칙:
  1. **judge를 먼저 검증한다.** 정답을 아는 사례로 judge가 실제로 오역을 잡는지
     확인하지 않으면, 합성 하네스와 같은 실수(검증 안 된 측정도구로 결론)를 반복한다.
     → `--validate` 로 먼저 돌릴 것.
  2. environment=production 만 소비한다 (부하 트래픽 제외, OBSERVABILITY.md 참조).
  3. 스타일이 아니라 **의미**만 본다 — 어색함은 최하 등급으로 분리.

judge 검증 결과 (사례 11건, gpt-4o-mini):
  문제 유무 탐지  11/11 — 주 지표로 사용
  카테고리 세분   7/11  — SANITIZED/FABRICATED/OMITTED/MEANING_CHANGED가 실제로
                          의미가 겹쳐 판정이 흔들린다. **참고용으로만 볼 것.**
  ⚠️ 번역이 gpt-4o 계열 산출물인데 judge도 같은 계열이라 자기선호 편향 가능성이
     있다. 추세가 중요해지면 다른 계열(Gemini 등)로 교차검증할 것.

실행:
  OPENAI_API_KEY=... uv run python scripts/translation_quality_eval.py --validate
  LANGFUSE_* ... uv run python scripts/translation_quality_eval.py --limit 100
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_client = None

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-4o-mini")

CATEGORIES = {
    "OK": "의미가 보존됨",
    "MEANING_CHANGED": "의미가 바뀜 — 원문과 다른 내용을 전달",
    "SANITIZED": "완곡화/검열 — 노골적·민감한 내용을 순화하거나 삭제",
    "OMITTED": "누락 — 원문의 일부가 번역되지 않음",
    "FABRICATED": "생성 — 원문에 없는 내용이 추가됨",
    "AWKWARD": "의미는 맞으나 어색함 (심각도 최하)",
}

SYSTEM = """You judge whether a translation preserves the MEANING of the source utterance.
This is a live phone-interpretation service between a foreign caller and a Korean institution
(medical, administrative). A changed or softened meaning can cause real harm.

Rules:
- Judge MEANING only. Register/politeness differences are NOT errors.
- Blunt, coarse, or clinical source content MUST stay blunt in translation.
  Softening or replacing it is SANITIZED, not OK.
- If the translation states something the source does not, that is FABRICATED —
  even if it is fluent and contextually plausible.
- If part of the source is missing, that is OMITTED.
- AWKWARD only when meaning is fully preserved but phrasing is unnatural.

Category precedence (these overlap — pick the MOST SPECIFIC one that applies):
1. SANITIZED  — the change is specifically a softening/censoring of sensitive content
2. FABRICATED — content present in the translation is absent from the source
3. OMITTED    — content present in the source is absent from the translation
4. MEANING_CHANGED — meaning differs but none of the above describes it
Use MEANING_CHANGED only as the fallback.

Return JSON only:
{"category": one of ["OK","MEANING_CHANGED","SANITIZED","OMITTED","FABRICATED","AWKWARD"],
 "severity": 0-3 (0=none, 1=minor, 2=serious, 3=harmful),
 "reason": "one short sentence in Korean"}"""

# judge 자체를 검증할 사례 — 정답을 아는 것만 넣는다.
# 대부분 실제 프로덕션 로그에서 관측된 것이다.
VALIDATION_CASES = [
    # (원문, 번역, 기대 카테고리, 출처)
    ("What's your name?", "성함이 어떻게 되실까요?", "OK", "정상 (2026-07-19 통화)"),
    ("배송은 보통 이틀 정도 걸립니다.", "Delivery usually takes about two days.", "OK", "정상"),
    # STT가 짧은 발화를 엉뚱하게 인식했는데 번역은 맥락에서 그럴듯한 문장을 지어낸 유형
    ("아르바이트!", "What's your name?", "FABRICATED", "STT 깨짐 → 맥락으로 지어냄"),
    ("또 뭐야", "What's your name?", "FABRICATED", "같은 출력 반복"),
    ("How many times do you poop?", "몇 번이나 넣었어?", "MEANING_CHANGED", "실측: 의미 소실"),
    ("Fuck. Fuck.", "[unclear]", "OMITTED", "실측: 욕설이 통째로 사라짐"),
    ("설사가 심하고 피가 섞여 나옵니다.",
     "I have an upset stomach.", "SANITIZED", "의료 증상 순화 — 위험"),
    # 라벨 정정: 처음엔 OK로 뒀으나 judge 지적이 맞다 — 입원(admitted)과
    # 방문(went to)은 의료 맥락에서 다른 정보다. judge에 맞춰 테스트를 고친 게
    # 아니라, 판정 근거를 검토해 내 라벨이 틀렸다고 판단한 것이다.
    ("아버지가 어제 병원에 입원하셨어요.",
     "My father was admitted to the hospital yesterday.", "OK", "존댓말 차이는 오류 아님"),
    ("아버지가 어제 병원에 입원하셨어요.",
     "My father went to the hospital yesterday.", "MEANING_CHANGED", "입원 → 방문 (정보 손실)"),
    ("보험 적용이 안 되고 본인 부담 삼십만 원입니다.",
     "It's not covered by insurance.", "OMITTED", "금액 누락"),
    ("네, 알겠습니다.", "Yes, I understand. Thank you so much for your help today.",
     "FABRICATED", "원문에 없는 내용 추가"),
]


def _openai_json(system: str, user: str) -> dict:
    """openai SDK 사용 — urllib은 이 환경에서 CA 번들이 없어 SSL 검증에 실패한다."""
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI()
    r = _client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(r.choices[0].message.content)


def judge(source: str, translation: str, direction: str = "") -> dict:
    user = f"Source utterance:\n{source}\n\nTranslation:\n{translation}"
    if direction:
        user += f"\n\n(direction: {direction})"
    try:
        out = _openai_json(SYSTEM, user)
        if out.get("category") not in CATEGORIES:
            out["category"] = "OK"
        return out
    except Exception as e:  # 채점 실패가 파이프라인을 멈추지 않게
        return {"category": "ERROR", "severity": 0, "reason": str(e)[:80]}


# ---------------- judge 검증 ----------------

def run_validation() -> None:
    print(f"judge 검증 — 모델 {JUDGE_MODEL} · 사례 {len(VALIDATION_CASES)}건")
    print("정답을 아는 사례로 judge가 실제 오역을 잡는지 먼저 확인한다.\n")
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda c: judge(c[0], c[1]), VALIDATION_CASES))

    hit = 0
    # OK/오류 이분법으로도 따로 본다 — 카테고리를 헷갈려도 '문제 있음'만 맞히면 쓸모가 있다
    binary_hit = 0
    for (src, tr, expect, note), got in zip(VALIDATION_CASES, results):
        ok = got["category"] == expect
        hit += ok
        # ERROR는 판정 실패이므로 어떤 경우에도 정답으로 세지 않는다
        if got["category"] != "ERROR":
            binary_hit += (got["category"] == "OK") == (expect == "OK")
        mark = "✓" if ok else "✗"
        print(f"  {mark} 기대 {expect:16} 판정 {got['category']:16} sev={got.get('severity')}  [{note}]")
        if not ok:
            print(f"      원문: {src[:52]}")
            print(f"      번역: {tr[:52]}")
            print(f"      사유: {got.get('reason','')[:70]}")
    n = len(VALIDATION_CASES)
    print(f"\n  카테고리 정확도  {hit}/{n} ({hit/n*100:.0f}%)")
    print(f"  문제유무 정확도  {binary_hit}/{n} ({binary_hit/n*100:.0f}%)  ← 실사용에 더 중요")
    if binary_hit < n * 0.8:
        print("\n  ⚠️ judge 신뢰도가 낮다. 이 상태로 프로덕션 채점을 돌리면 안 된다.")


# ---------------- 프로덕션 채점 ----------------

def fetch_turns(limit: int) -> list[dict]:
    """Langfuse에서 번역 턴(generation)을 가져온다. production 환경만."""
    pk, sk = os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    url = f"{host}/api/public/observations?type=GENERATION&limit={min(limit, 100)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)["data"]
    turns = []
    for o in data:
        if o.get("environment") not in (None, "production"):
            continue  # 부하/개발 트래픽 제외
        src, tr = o.get("input"), o.get("output")
        if isinstance(src, str) and isinstance(tr, str) and src.strip() and tr.strip():
            turns.append({"id": o["id"], "source": src, "translation": tr,
                          "direction": (o.get("metadata") or {}).get("direction", "")})
    return turns


def run_production(limit: int) -> None:
    turns = fetch_turns(limit)
    print(f"채점 대상 {len(turns)}턴 (environment=production)\n")
    if not turns:
        print("  대상이 없다. 실사용 통화가 쌓여야 한다.")
        return
    with ThreadPoolExecutor(max_workers=8) as ex:
        verdicts = list(ex.map(lambda t: judge(t["source"], t["translation"], t["direction"]), turns))

    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v["category"]] = counts.get(v["category"], 0) + 1
    bad = [(t, v) for t, v in zip(turns, verdicts) if v["category"] not in ("OK", "AWKWARD", "ERROR")]

    sev = [v.get("severity", 0) for v in verdicts if v["category"] != "ERROR"]
    harmful = sum(1 for x in sev if x >= 3)
    serious = sum(1 for x in sev if x == 2)
    print("── 주 지표 (검증된 축) ──")
    print(f"  의미 훼손 턴   {len(bad)}/{len(turns)} ({len(bad)/len(turns)*100:.1f}%)")
    print(f"  심각도 3(해로움) {harmful}   심각도 2(중대) {serious}")
    print("\n── 카테고리 분포 (참고용 — 판정 신뢰도 낮음) ──")
    for c, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {c:16} {n:4}  ({n/len(turns)*100:4.1f}%)  {CATEGORIES.get(c,'')}")

    if bad:
        print("\n── 심각도 높은 사례 ──")
        for t, v in sorted(bad, key=lambda x: -x[1].get("severity", 0))[:10]:
            print(f"  [{v['category']} sev={v.get('severity')}] {v.get('reason','')[:60]}")
            print(f"     원문: {t['source'][:64]}")
            print(f"     번역: {t['translation'][:64]}")


if __name__ == "__main__":
    if "--validate" in sys.argv:
        run_validation()
    else:
        lim = 100
        if "--limit" in sys.argv:
            lim = int(sys.argv[sys.argv.index("--limit") + 1])
        run_production(lim)
