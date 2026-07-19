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
import ssl
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

CRITICAL — the source is a LOSSY AUTOMATIC TRANSCRIPT, not ground truth.
The translation system listens to the AUDIO directly, while the source text you
see is a separate speech-to-text pass over the same audio. That transcript is
often truncated or garbled ("a kind of a", "Can you"), so the translation can
legitimately contain MORE than the transcript shows.
- Do NOT flag a translation merely because it is longer or more complete than
  the transcript. That is expected when the transcript lost words.
- Flag it when the translation is about something ELSE — a different topic,
  entity, question, or answer than the transcript could plausibly come from.
  Example of a real failure: transcript "출근입니다." → translation "Yes, 27 minutes."
Fragmentary transcripts are filtered out before you see them, so assume the
source is a reasonably complete utterance.
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
    # STT 손실 케이스 — 전사가 조각났을 뿐 번역은 정상. 벌점을 주면 안 된다.
    # 실측 오역 — 주제 자체가 다르므로 전사 손실로 설명되지 않는다
    ("출근입니다.", "Yes, 27 minutes.", "MEANING_CHANGED", "실측: 주제 불일치"),
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
    frags = ["a kind of a", "Can you", "Oh", "You", "Three"]
    caught = sum(looks_fragmentary(f) for f in frags)
    print(f"\n  조각 전사 사전필터  {caught}/{len(frags)} 차단 "
          f"(judge에게 묻지 않고 규칙으로 제외)")
    if binary_hit < n * 0.8:
        print("\n  ⚠️ judge 신뢰도가 낮다. 이 상태로 프로덕션 채점을 돌리면 안 된다.")


# ---------------- 프로덕션 채점 ----------------

# 조각난 전사는 채점 대상에서 제외한다. 실시간 모델은 오디오를 직접 듣지만
# 여기 '원문'은 별도 STT 결과라, 전사가 잘리면 정상 번역도 '원문에 없는 내용
# 추가'로 보인다. 텍스트만으로는 '전사가 잃은 것'과 '모델이 지어낸 것'을
# 구분할 수 없으므로(오디오가 있어야 판별 가능), judge에게 묻지 않고 규칙으로
# 걸러낸다 — 판정을 프롬프트로 강제하려 하면 사례 몇 개에 과적합될 뿐이다.
_SENTENCE_END = (".", "?", "!", "。", "？", "！", "요", "다", "까", "죠", "네")


def looks_fragmentary(text: str) -> bool:
    t = text.strip()
    if len(t) < 6:
        return True
    if not t.endswith(_SENTENCE_END):
        return True
    return len(t.split()) < 2 and len(t) < 10


def _ssl_context() -> ssl.SSLContext:
    """certifi 번들로 검증 컨텍스트를 만든다.

    이 환경의 시스템 파이썬에는 CA 번들이 설치돼 있지 않아 urllib 기본 설정으로는
    CERTIFICATE_VERIFY_FAILED가 난다. 검증을 끄는 대신 번들을 지정한다.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_turns(limit: int) -> list[dict]:
    """Langfuse에서 번역 턴(generation)을 가져온다. production 환경만."""
    pk, sk = os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"]
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
    auth = base64.b64encode(f"{pk}:{sk}".encode()).decode()
    url = f"{host}/api/public/observations?type=GENERATION&limit={min(limit, 100)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as r:
        data = json.load(r)["data"]
    turns = []
    for o in data:
        if o.get("environment") not in (None, "production"):
            continue  # 부하/개발 트래픽 제외
        src, tr = o.get("input"), o.get("output")
        if isinstance(src, str) and isinstance(tr, str) and src.strip() and tr.strip():
            meta = o.get("metadata") or {}
            stt_source = meta.get("stage.stt_source") or meta.get("stt_source") or ""
            turns.append({
                "id": o["id"], "source": src, "translation": tr,
                "direction": meta.get("direction", ""),
                # 원문 STT가 없어 번역문으로 대체된 턴. 원문==번역이라 채점이
                # 무의미하고, 동시에 '아무도 말하지 않았는데 모델이 발화한' 생성
                # 환각의 후보이기도 하다 — 별도 지표로 센다.
                "is_fallback": stt_source == "translation_fallback",
                "is_fragment": looks_fragmentary(src),
                "input_peak_rms": meta.get("stage.input_peak_rms"),
            })
    return turns


def run_production(limit: int) -> None:
    all_turns = fetch_turns(limit)
    fallback = [t for t in all_turns if t["is_fallback"]]
    rest = [t for t in all_turns if not t["is_fallback"]]
    fragments = [t for t in rest if t["is_fragment"]]
    turns = [t for t in rest if not t["is_fragment"]]

    print(f"수집 {len(all_turns)}턴 (environment=production)")
    print(f"  채점 대상          {len(turns)}턴")
    print(f"  원문 조각남        {len(fragments)}턴 — 제외 (STT 손실과 오역 구분 불가)")
    print(f"  원문 없음(fallback) {len(fallback)}턴 — 제외\n")
    if fallback:
        print("── ⚠️ 원문 STT 없이 생성된 발화 (생성 환각 후보) ──")
        print("   페어링 수정 배포 이후에도 남는다면 '아무도 말하지 않은 문장을")
        print("   시스템이 상대에게 말한 것'이다.")
        for t in fallback[:8]:
            pk = t.get("input_peak_rms")
            tag = "입력에너지 없음" if pk is None else f"peak={pk}"
            print(f"   [{tag:>12}] {t['translation'][:56]}")
        print()
    if not turns:
        print("  채점 대상이 없다. 실사용 통화가 쌓여야 한다.")
        return
    with ThreadPoolExecutor(max_workers=8) as ex:
        verdicts = list(ex.map(lambda t: judge(t["source"], t["translation"], t["direction"]), turns))

    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v["category"]] = counts.get(v["category"], 0) + 1
    JUDGEABLE_OK = ("OK", "AWKWARD", "ERROR", "UNJUDGEABLE")
    bad = [(t, v) for t, v in zip(turns, verdicts) if v["category"] not in JUDGEABLE_OK]
    unjudgeable = [v for v in verdicts if v["category"] == "UNJUDGEABLE"]
    judged = [v for v in verdicts if v["category"] not in ("ERROR", "UNJUDGEABLE")]

    sev = [v.get("severity", 0) for v in verdicts if v["category"] != "ERROR"]
    harmful = sum(1 for x in sev if x >= 3)
    serious = sum(1 for x in sev if x == 2)
    print("── 주 지표 (검증된 축) ──")
    denom = max(1, len(judged))
    print(f"  의미 훼손 턴   {len(bad)}/{len(judged)} ({len(bad)/denom*100:.1f}%)  ← 판정 가능분 기준")
    print(f"  판정 불가      {len(unjudgeable)}턴 (전사가 조각나 비교 불능)")
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
