"""전국 재난·통신·교통 일일 현황 보고.

사용법:
  python main.py collect [--date YYYY-MM-DD]   Gemini로 수집해 data/YYYY-MM-DD.json 저장
  python main.py build                         data/*.json으로 site/ 생성
  python main.py sample                        샘플 데이터로 site/ 생성 (data/는 건드리지 않음)
"""
import argparse
import json
from datetime import date, datetime

from report.build import build, load_reports
from report.config import DATA_DIR, KST, ROOT, report_window, today_kst
from report.normalize import normalize


def make_report(report_date: date, raw: dict, sample: bool = False) -> dict:
    start, end = report_window(report_date)
    events, dropped = normalize(raw["events"], report_date)
    return {
        "report_date": report_date.isoformat(),
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "sample": sample,
        "sources_status": raw["sources_status"],
        "dropped": dropped,
        "events": events,
    }


def cmd_collect(args):
    from report.collect import collect  # Gemini SDK는 수집할 때만 불러온다

    report_date = date.fromisoformat(args.date) if args.date else today_kst()
    report = make_report(report_date, collect(report_date))
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"{report_date.isoformat()}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[collect] {path.name}: 게시 {len(report['events'])}건, 제외 {report['dropped']}")
    for status in report["sources_status"]:
        print(f"[collect] {status['name']}: {'OK' if status['ok'] else 'FAIL'} {status['message']}")


def cmd_build(_args):
    written = build(load_reports())
    print(f"[build] {len(written)}개 페이지 생성 → site/")


def cmd_sample(_args):
    raw = json.loads((ROOT / "samples" / "sample.json").read_text(encoding="utf-8"))
    report = make_report(date.fromisoformat(raw["report_date"]), raw, sample=True)
    written = build([report])
    print(f"[sample] 게시 {len(report['events'])}건, 제외 {report['dropped']}, {len(written)}개 페이지 → site/")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("collect")
    p.add_argument("--date", help="보고 날짜 (기본: 오늘, KST)")
    p.set_defaults(func=cmd_collect)
    sub.add_parser("build").set_defaults(func=cmd_build)
    sub.add_parser("sample").set_defaults(func=cmd_sample)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
