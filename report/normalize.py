"""수집 결과 검증, 기간 필터, 중복 제거, 심각도 보정."""
import re
from datetime import date, datetime

from .config import CATEGORIES, REGIONS, SEVERITIES, SEVERITY_RANK, STATUSES, report_window

CRITICAL_WORDS = ["사망", "실종", "인명피해", "부상자", "위급재난", "전면 통제", "전면통제", "운행 중단", "운행중단"]
WARNING_WORDS = ["주의보", "긴급재난", "결항", "지연", "부분 통제", "통제", "장애"]


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _upgrade_severity(event: dict) -> str:
    """4.3절 기준 보수적 보정: 키워드가 있으면 등급을 올리기만 한다."""
    text = f"{event['title']} {event['summary']}"
    severity = event["severity"]
    if event["status"] == "resolved":  # 복구 안내는 모델 판단을 그대로 쓴다
        return severity
    if any(w in text for w in CRITICAL_WORDS) or re.search(r"(?<!주의)경보", text):
        candidate = "critical"
    elif any(w in text for w in WARNING_WORDS):
        candidate = "warning"
    else:
        candidate = severity
    return min(severity, candidate, key=SEVERITY_RANK.__getitem__)


def _dedup_key(event: dict) -> tuple:
    return event["category"], re.sub(r"[\s\W_]+", "", event["title"])


def normalize(raw_events: list, report_date: date) -> tuple[list, dict]:
    start, end = report_window(report_date)
    dropped = {"no_source": 0, "out_of_window": 0, "invalid": 0, "duplicate": 0}
    merged: dict[tuple, dict] = {}

    for raw in raw_events:
        if not isinstance(raw, dict) or raw.get("category") not in CATEGORIES or not raw.get("title"):
            dropped["invalid"] += 1
            continue
        # http(s) 링크만 허용한다 (javascript: 등 악성 링크 차단)
        sources = [s for s in raw.get("sources") or [] if str(s.get("url", "")).startswith(("https://", "http://"))]
        if not sources:  # 환각 방지: 근거 URL 없는 항목은 게시하지 않는다
            dropped["no_source"] += 1
            continue

        started = _parse_time(raw.get("started_at"))
        ended = _parse_time(raw.get("ended_at"))
        status = raw.get("status") if raw.get("status") in STATUSES else "ongoing"
        if started and started.tzinfo and started > end:
            dropped["out_of_window"] += 1
            continue
        if ended and ended.tzinfo and ended < start:
            dropped["out_of_window"] += 1
            continue

        region = raw.get("region") or []
        if isinstance(region, str):
            region = [region]
        event = {
            "category": raw["category"],
            "severity": raw.get("severity") if raw.get("severity") in SEVERITIES else "warning",
            "status": status,
            "title": str(raw["title"]).strip(),
            "summary": str(raw.get("summary") or "").strip(),
            "region": [r for r in region if r in REGIONS or r == "전국"],
            "started_at": started.isoformat() if started else None,
            "ended_at": ended.isoformat() if ended else None,
            "sources": sources,
        }
        event["severity"] = _upgrade_severity(event)

        key = _dedup_key(event)
        if key in merged:
            dropped["duplicate"] += 1
            kept = merged[key]
            urls = {s["url"] for s in kept["sources"]}
            kept["sources"] += [s for s in sources if s["url"] not in urls]
            kept["severity"] = min(kept["severity"], event["severity"], key=SEVERITY_RANK.__getitem__)
        else:
            merged[key] = event

    events = sorted(
        merged.values(),
        key=lambda e: (SEVERITY_RANK[e["severity"]], e["status"] != "ongoing", e["started_at"] or ""),
    )
    for i, event in enumerate(events, 1):
        event["id"] = f"{report_date.isoformat()}-{event['category']}-{i:04d}"
    return events, dropped
