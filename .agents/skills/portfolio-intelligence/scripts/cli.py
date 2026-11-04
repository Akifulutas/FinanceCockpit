"""One entry point for the local ETF record and optional daily market context."""
import argparse
import subprocess
import sys
from pathlib import Path

from engine import WORKSPACE_DIR, run_all_engines
from render_html import render_html_dashboard
from render_markdown import render_report

COMMANDS = ["daily", "research", "macro", "themes", "news", "fetch", "html", "open", "all", "all_md",
            "option", "setups", "ai", "smart"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="ETF Yatırım Masası · yalnızca ETF ve uzun vade")
    parser.add_argument("command", nargs="?", default="daily", choices=COMMANDS,
                        help="daily: özet; research: günlük ETF araştırması; macro: piyasa; themes/news: fon kaynakları; fetch: günlük veri; open: pano")
    parser.add_argument("--workspace", type=Path, default=WORKSPACE_DIR)
    parser.add_argument("--no-open", action="store_true", help="Tarayıcıyı açmadan raporu kaydet")
    args = parser.parse_args(argv)
    if args.command in {"option", "setups", "ai", "smart"}:
        print("Bu modül etkin değil. Kapsam: ETF ve uzun vadeli yatırım. "
              "Opsiyon, kısa vadeli işlem veya doğrulanmamış puan/akış üretilmez. "
              "Kaynaklı tema araştırması için ETF Yatırım Masası skill'ini kullan.", file=sys.stderr)
        return 2
    status = 0
    try:
        if args.command in {"fetch", "all"}:
            from fetcher import fetch_market_data
            summary = fetch_market_data(root=args.workspace)
            print(f"Piyasa verisi: {summary['success']}/{summary['requested']} gösterge güncellendi.")
            if summary["success"] != summary["requested"]:
                print("Bazı kaynaklara erişilemedi. Varsa önceki kayıtlar korunur; hata durumu panoda gösterilir.", file=sys.stderr)
                status = 1
            if args.command == "fetch":
                return status
        data = run_all_engines(root=args.workspace)
        if args.command in {"html", "open", "all"}:
            output = render_html_dashboard(root=args.workspace, data=data)
            print(f"Pano: {output}")
            if args.command == "all":
                report = render_report(data=data)
                (args.workspace / "reports" / f"daily-{data['date']}.md").write_text(report, encoding="utf-8")
                print(report)
            if args.command in {"open", "all"} and not args.no_open:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                result = subprocess.run([opener, str(output)], check=False)
                if result.returncode:
                    print("Rapor kaydedildi; tarayıcı otomatik açılamadı.", file=sys.stderr)
                    return 1
        else:
            print(render_report(args.command, data=data))
        return status
    except (OSError, ValueError, KeyError) as error:
        print(f"Rapor üretilemedi: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
