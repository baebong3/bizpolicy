#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
소상공인 정책 뉴스 수집기 (bizpolicy)
네이버 뉴스 API → 게이트(소상공인 관련성) → 주제·시도·부처 태깅 → 규칙 감성 → biz_news.json 누적

환경변수: NAVER_ID, NAVER_SECRET  (.env 지원)
실행:    python collect_biz_news.py
누적:    biz_news.json (멱등 — id 기준 중복 제거, 기존 항목 보존)
"""
import html, json, os, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "biz_news.json")
KST = timezone(timedelta(hours=9))

if os.path.exists(os.path.join(HERE, ".env")):
    for ln in open(os.path.join(HERE, ".env"), encoding="utf-8"):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.strip().split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
NAVER_ID = os.environ.get("NAVER_ID", "")
NAVER_SECRET = os.environ.get("NAVER_SECRET", "")

# ── 수집 쿼리: (시도 힌트, 검색어) ──────────────────────────────
SIDO = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
        "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
QUERIES = [(None, q) for q in [
    "소상공인 지원", "소상공인 정책", "자영업자 지원", "소상공인 대출",
    "전통시장 지원", "골목상권", "온누리상품권", "스마트상점",
    "소상공인 디지털", "배달 수수료 소상공인", "상가 임대료 지원",
    "폐업 소상공인", "노란우산", "소상공인 재기", "소진공",
]] + [(s, f"{s} 소상공인") for s in SIDO]

# ── 게이트·분류 사전 ───────────────────────────────────────────
CORE = re.compile(r"소상공인|자영업|소공인|전통시장|골목상권|상인회|온누리")
NOISE = re.compile(r"주가|코스피|코스닥|경기\s?결과|프로야구|날씨|운세|부고|인사\]")

TOPICS = [
    ("금융·자금",    r"대출|보증|융자|이차보전|자금|금리|채무|상환|대환|보증서"),
    ("디지털·판로",  r"디지털|스마트상점|온라인|라이브커머스|판로|플랫폼|배달|수수료|키오스크|이커머스"),
    ("임대료·상가",  r"임대료|임차|상가|점포|젠트리|권리금|임대차"),
    ("전통시장·상권", r"전통시장|시장 활성|상권|온누리|골목|야시장|특화거리"),
    ("폐업·재기",    r"폐업|재기|재창업|노란우산|점포철거|브릿지보증|채무조정|새출발"),
    ("고용·인력",    r"고용|인건비|두루누리|일자리|인력|최저임금|근로"),
    ("정책·제도",    r"조례|법안|기본계획|제도|규제|세제|감면|간담회|협약"),
]
DEPTS = ["중소벤처기업부", "중기부", "소상공인시장진흥공단", "소진공", "금융위원회",
         "국세청", "고용노동부", "행정안전부", "공정거래위원회", "동반성장위원회"]

NEG = r"폐업|줄폐업|한파|위기|급감|부담|연체|체납|반발|규탄|항의|피해|눈물|벼랑|직격탄|침체|미납|갈등|시위|악화|비명|한숨|먹튀|사기"
POS = r"성료|호응|북적|훈풍|특수|활성화|매출 증가|매출 상승|인하|감면|완화|확대 지원|부활|호황|혜택|첫 지급|개소"


def clean(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(t or ""))).strip()

def topic_tags(text):
    tags = [name for name, pat in TOPICS if re.search(pat, text)]
    return tags or ["정책·제도"]

def sido_of(text, hinted):
    for s in SIDO:
        if re.search(s + r"(특별|광역)?(시|도)?[\s의]", text + " ") or text.startswith(s):
            return s
    return hinted

def dept_of(text):
    for d in DEPTS:
        if d in text:
            return {"중기부": "중소벤처기업부", "소진공": "소상공인시장진흥공단"}.get(d, d)
    return None

def classify(text):
    n = len(re.findall(NEG, text)); p = len(re.findall(POS, text))
    if n > p and n >= 1:
        return "부정"
    if p > n and p >= 1:
        return "긍정"
    return "중립"

def pubdate_iso(p):
    try:
        return datetime.strptime(p, "%a, %d %b %Y %H:%M:%S %z").astimezone(KST).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(KST).strftime("%Y-%m-%d")

def naver(query, start=1):
    req = urllib.request.Request(
        "https://openapi.naver.com/v1/search/news.json?" +
        urllib.parse.urlencode({"query": query, "display": 100, "start": start, "sort": "date"}),
        headers={"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode()).get("items", [])
    except Exception:
        return []


def main():
    if not (NAVER_ID and NAVER_SECRET):
        print("NAVER_ID / NAVER_SECRET 환경변수가 필요합니다 (.env)"); return
    existing = {"items": []}
    if os.path.exists(OUT):
        try:
            existing = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            pass
    seen = {it["id"]: it for it in existing.get("items", [])}
    new_cnt = 0
    for hinted, q in QUERIES:
        for start in (1, 101):
            items = naver(q, start)
            if not items:
                break
            for it in items:
                title = clean(it.get("title")); desc = clean(it.get("description"))
                text = f"{title} {desc}"
                if not CORE.search(text) or NOISE.search(title):
                    continue
                url = it.get("originallink") or it.get("link") or ""
                _id = re.sub(r"\W", "", url)[-16:] or str(abs(hash(title)))[:12]
                if _id in seen:
                    continue
                sido = sido_of(text, hinted)
                tags = topic_tags(text)
                seen[_id] = {
                    "id": _id, "date": pubdate_iso(it.get("pubDate")),
                    "title": title, "description": desc[:300],
                    "url": url, "source": "네이버뉴스",
                    "scope": "지자체" if sido else "중앙",
                    "sido": sido, "dept": dept_of(text),
                    "field": tags[0], "topics": tags,
                    "sentiment": classify(text),
                }
                new_cnt += 1
            time.sleep(0.12)
        print(f"· {q}  (누적 {len(seen):,})")
    items = sorted(seen.values(), key=lambda x: x["date"], reverse=True)
    json.dump({"meta": {"generated": datetime.now(KST).isoformat(timespec="seconds"),
                        "total": len(items), "sources": ["네이버 뉴스 API"]},
               "items": items}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"신규 {new_cnt:,}건 · biz_news.json 총 {len(items):,}건")


if __name__ == "__main__":
    main()
