"""data/*.json으로 정적 사이트(site/)를 만든다."""
import json
import shutil
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import CATEGORIES, DATA_DIR, KST, SEVERITIES, SITE_DIR, STATUSES, TEMPLATE_DIR

WEEKDAYS = "월화수목금토일"


def _fmt_time(value) -> str:
    if not value:
        return "시각 미상"
    dt = datetime.fromisoformat(value).astimezone(KST)
    return dt.strftime("%m-%d %H:%M")


def _fmt_date(value: str) -> str:
    d = date.fromisoformat(value)
    return f"{d.isoformat()}({WEEKDAYS[d.weekday()]})"


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape())
    env.filters["time"] = _fmt_time
    env.filters["kdate"] = _fmt_date
    env.globals.update(CATEGORIES=CATEGORIES, SEVERITIES=SEVERITIES, STATUSES=STATUSES)
    return env


def _counts(events: list) -> dict:
    counts = {c: {s: 0 for s in SEVERITIES} for c in CATEGORIES}
    for e in events:
        counts[e["category"]][e["severity"]] += 1
    return counts


def load_reports(data_dir: Path = DATA_DIR) -> list[dict]:
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(data_dir.glob("????-??-??.json"))]
    return sorted(reports, key=lambda r: r["report_date"], reverse=True)


def build(reports: list[dict], site_dir: Path = SITE_DIR) -> list[Path]:
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)
    env = _env()
    report_tpl, archive_tpl = env.get_template("report.html.j2"), env.get_template("archive.html.j2")
    written = []

    def write(path: Path, html: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        written.append(path)

    for i, report in enumerate(reports):
        ctx = dict(report=report, counts=_counts(report["events"]))
        write(site_dir / report["report_date"] / "index.html", report_tpl.render(**ctx, root="../"))
        if i == 0:
            write(site_dir / "index.html", report_tpl.render(**ctx, root=""))

    if not reports:
        write(site_dir / "index.html", archive_tpl.render(reports=[], root=""))
    write(site_dir / "archive" / "index.html", archive_tpl.render(reports=reports, root="../"))
    return written
