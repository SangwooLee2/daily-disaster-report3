"""Google 뉴스 RSS로 기사를 모으고, Gemini(검색 없이)를 하루 1회 호출해 사건으로 묶고 분류한다.

출처는 Gemini가 쓴 내용이 아니라 RSS에 실제로 있는 기사(article_ids)에서만 가져온다.
근거 기사가 연결되지 않은 사건은 sources가 비어 있게 되고, normalize 단계에서 제외된다.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

from google import genai
from google.genai import types

from .config import CATEGORIES, GEMINI_MODEL, KST, REGIONS, report_window

RSS_URL = "https://news.google.com/rss/search"
MAX_ARTICLES = 250  # Gemini에 넘길 최대 기사 수

# 분야별 검색어. Google 뉴스는 OR 연산자를 지원한다.
QUERIES = {
    "disaster": [
        "기상특보 OR 호우경보 OR 대설경보 OR 한파경보 OR 폭염경보 OR 강풍경보 OR 풍랑경보",
        "호우주의보 OR 대설주의보 OR 한파주의보 OR 강풍주의보 OR 풍랑주의보 OR 태풍",
        "지진 발생 OR 산불 발생 OR 대피령 OR 긴급재난문자 OR 인명피해",
        "화재 사망 OR 폭발 사고 OR 붕괴 사고 OR 침수 피해 OR 산사태",
    ],
    "telecom": [
        "통신장애 OR 통신 장애 OR 인터넷 먹통 OR 통신 두절 OR 통신망 마비",
        "KT 장애 OR SKT 장애 OR LG유플러스 장애 OR 이동통신 장애 OR 데이터센터 화재",
    ],
    "traffic": [
        "도로 통제 OR 통행 제한 OR 고속도로 통제 OR 교량 통제 OR 차량 통제",
        "열차 운행 중단 OR 열차 지연 OR 운행 중지 OR 지하철 운행 중단",
        "항공기 결항 OR 무더기 결항 OR 여객선 통제 OR 여객선 결항 OR 뱃길 통제",
    ],
}

PROMPT = """너는 대한민국 재난·통신·교통 상황을 정리하는 보고 담당자다.
아래는 Google 뉴스에서 모은 기사 목록이다. 이 목록만 근거로, 집계 기간에 발생했거나 진행 중이던 사건을 정리하라.

[집계 기간] {start} ~ {end} (한국 시간)

[분야]
- disaster (재난·재해): 기상특보, 지진, 산불, 대형 화재·폭발·붕괴, 침수, 긴급재난문자, 인명피해
- telecom (유무선 통신망 두절): 이동통신·인터넷·유선전화 장애, 통신사 장애, 데이터센터 장애
- traffic (교통 두절): 도로 통제·통행 제한, 철도 운행 중단·지연, 항공기 결항, 여객선 통제

[심각도]
- critical: 인명피해 발생, 기상 '경보', 위급재난문자, 2개 시·도 이상 광역 통신 장애, 고속도로·철도 본선 전면 통제
- warning: 기상 '주의보', 긴급재난문자, 단일 지역 통신 장애, 부분 통제·지연, 결항
- info: 안전안내문자, 예고된 통제(공사 등), 복구 완료 안내
- 애매하면 더 높은 등급을 고른다.

[규칙]
- 실제로 발생한 사건만 쓴다. 예방 활동, 캠페인, 훈련, 점검, 정책·예산, 과거 사건 회고, 해외 사건 기사는 제외한다.
- 같은 사건을 다룬 여러 기사는 하나의 사건으로 묶고, article_ids에 해당 기사 번호를 모두 넣는다.
- article_ids에는 아래 목록에 있는 번호만 쓴다. 목록에 없는 사건은 절대 만들지 않는다.
- region은 다음 중에서만 고른다: {regions}, 전국. 알 수 없으면 빈 배열.
- started_at은 기사로 알 수 있는 사건 시작 시각(ISO 8601, +09:00)이며, 모르면 null로 둔다.
- summary는 일반 시민이 이해할 수 있는 쉬운 문장 1~2개로 쓴다.
- 해당 사건이 없는 분야는 비워 둔다.

[출력] JSON 배열만 출력한다.
[{{"category": "disaster|telecom|traffic", "severity": "critical|warning|info",
   "status": "ongoing|resolved", "title": "짧은 제목", "summary": "요약",
   "region": ["강원"], "started_at": null, "ended_at": null, "article_ids": [3, 17]}}]

[기사 목록] 번호 | 검색 분야 | 발행 시각 | 언론사 | 제목
{articles}
"""


def _fetch_rss(query: str, start: datetime, end: datetime) -> list[dict]:
    after = (start - timedelta(days=1)).date().isoformat()
    before = (end + timedelta(days=1)).date().isoformat()
    params = {"q": f"{query} after:{after} before:{before}", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    req = urllib.request.Request(f"{RSS_URL}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "Mozilla/5.0"})
    root = ET.fromstring(urllib.request.urlopen(req, timeout=20).read())

    articles = []
    for item in root.findall("./channel/item"):
        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).astimezone(KST)
        except (TypeError, ValueError):
            continue
        if not start <= published <= end:
            continue
        source = item.find("source")
        press = source.text.strip() if source is not None and source.text else ""
        title = (item.findtext("title") or "").strip()
        if press and title.endswith(f" - {press}"):
            title = title[: -len(press) - 3]
        articles.append({"title": title, "press": press, "url": item.findtext("link"), "published_at": published})
    return articles


def gather_articles(report_date: date) -> tuple[list[dict], list[dict]]:
    """분야별 검색어로 RSS를 모은다. 같은 기사는 한 번만 남긴다."""
    start, end = report_window(report_date)
    articles, seen, statuses = [], set(), []
    for category, queries in QUERIES.items():
        ok, count, errors = 0, 0, []
        for query in queries:
            try:
                found = _fetch_rss(query, start, end)
                ok += 1
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}"[:120])
                continue
            for a in found:
                key = re.sub(r"\W+", "", a["title"])
                if a["url"] in seen or key in seen:
                    continue
                seen.update({a["url"], key})
                articles.append({**a, "category": category})
                count += 1
        statuses.append({
            "name": f"Google 뉴스 RSS ({CATEGORIES[category]})",
            "ok": ok > 0,
            "message": f"검색어 {ok}/{len(queries)}개 성공, 기사 {count}건" + (f" · {errors[0]}" if errors else ""),
        })
    articles.sort(key=lambda a: a["published_at"], reverse=True)
    return articles[:MAX_ARTICLES], statuses


def _extract_json(text: str) -> list:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("응답에서 JSON 배열을 찾지 못했습니다")
    return json.loads(text[start : end + 1])


def _ask_gemini(prompt: str, retries: int = 3) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise KeyError("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json"),
            )
            return response.text or ""
        except genai.errors.ServerError:  # 503 등 일시적 과부하는 잠시 후 재시도
            if attempt == retries - 1:
                raise
            time.sleep(20 * (attempt + 1))


def _attach_sources(events: list, articles: list) -> None:
    for event in events:
        ids = {i for i in event.pop("article_ids", None) or [] if isinstance(i, int) and 0 <= i < len(articles)}
        cited = sorted((articles[i] for i in ids), key=lambda a: a["published_at"])
        event["sources"] = [
            {"name": a["press"] or "언론 보도", "type": "news", "url": a["url"], "published_at": a["published_at"].isoformat()}
            for a in cited
        ]
        if cited and not event.get("started_at"):  # 시각을 모르면 가장 이른 기사 시각으로
            event["started_at"] = cited[0]["published_at"].isoformat()


def collect(report_date: date) -> dict:
    """RSS 수집 + Gemini 1회 호출로 원시 사건 목록과 수집 상태를 돌려준다."""
    start, end = report_window(report_date)
    articles, statuses = gather_articles(report_date)
    gemini = {"name": "Gemini 분류·요약", "ok": False, "message": ""}
    statuses.append(gemini)
    if not articles:
        gemini["message"] = "분석할 기사가 없어 호출하지 않았습니다"
        gemini["ok"] = any(s["ok"] for s in statuses[:-1])
        return {"events": [], "sources_status": statuses}
    try:
        lines = "\n".join(
            f"{i} | {a['category']} | {a['published_at']:%m-%d %H:%M} | {a['press']} | {a['title']}"
            for i, a in enumerate(articles)
        )
        text = _ask_gemini(PROMPT.format(
            start=f"{start:%Y-%m-%d %H:%M}", end=f"{end:%Y-%m-%d %H:%M}",
            regions=", ".join(REGIONS), articles=lines,
        ))
        events = _extract_json(text)
        _attach_sources(events, articles)
        gemini.update(ok=True, message=f"기사 {len(articles)}건 → 사건 {len(events)}건")
        return {"events": events, "sources_status": statuses}
    except KeyError:
        gemini["message"] = "GEMINI_API_KEY가 설정되지 않았습니다 (.env 또는 환경 변수)"
    except Exception as e:  # F8: 수집 실패해도 발행은 계속한다
        gemini["message"] = f"{type(e).__name__}: {e}"[:300]
    return {"events": [], "sources_status": statuses}
