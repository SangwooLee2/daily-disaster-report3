"""공통 설정: 시간대, 집계 기간, 분야·심각도 정의."""
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"
TEMPLATE_DIR = ROOT / "templates"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """.env를 환경 변수로 읽는다. 이미 설정된 값(GitHub Secrets 등)과 빈 값은 덮어쓰지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if value and not os.environ.get(key):
            os.environ[key] = value


load_dotenv()  # 01_사건사고/.env 우선
load_dotenv(ROOT.parent / ".env")  # 없는 값은 상위 폴더 .env에서

PUBLISH_TIME = time(7, 0)  # 매일 07:00 KST 발행

GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"

CATEGORIES = {
    "disaster": "재난·재해",
    "telecom": "유무선 통신망 두절",
    "traffic": "교통 두절",
}

SEVERITIES = {
    "critical": "긴급",
    "warning": "주의",
    "info": "정보",
}
SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}

STATUSES = {"ongoing": "진행 중", "resolved": "해제·복구"}

REGIONS = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]


def today_kst() -> date:
    return datetime.now(KST).date()


def report_window(report_date: date) -> tuple[datetime, datetime]:
    """집계 기간: 전날 07:00 ~ 당일 07:00 (KST)."""
    end = datetime.combine(report_date, PUBLISH_TIME, tzinfo=KST)
    return end - timedelta(days=1), end
