import argparse
from datetime import date

from scraper_common import (
    LotteryConfig,
    find_latest_csv,
    load_existing_csv,
    parse_csv_date,
    print_result_for_date,
)

GAMES = [
    LotteryConfig("Magnum 4D", "magnum_pastresult", ['logo_magnum.gif'], "M"),
    LotteryConfig("SportsToto 4D", "toto_pastresult", ['logo_toto4d'], "T"),
]


def print_result(cfg: LotteryConfig, target_date: date):
    csv_path = find_latest_csv(cfg)
    if not csv_path:
        print(f"{cfg.target_name}: no data file found.\n")
        return

    rows, _, _ = load_existing_csv(csv_path)
    print_result_for_date(cfg, rows, target_date)


def main():
    parser = argparse.ArgumentParser(description="Show 4D winning numbers for a given date.")
    parser.add_argument(
        "date", nargs="?", default=None,
        help="Date to show results for (DD-MM-YYYY). Defaults to today.",
    )
    args = parser.parse_args()

    if args.date:
        target_date = parse_csv_date(args.date)
        if not target_date:
            raise SystemExit(f"Could not parse date: {args.date}")
    else:
        target_date = date.today()

    for cfg in GAMES:
        print_result(cfg, target_date)


if __name__ == "__main__":
    main()
