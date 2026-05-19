TARGET_NAME = "SportsToto 4D"
FILE_PREFIX = "toto_pastresult"
LOGO_SRC_KEYS = ['logo_toto4d']


import csv
import glob
import os
import re
import time
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.4dmoon.com/past-results/{}"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_START_DATE = date(1985, 1, 1)
RECHECK_DAYS = 60
MAX_WORKERS = 10
REQUEST_TIMEOUT = 15
RETRY_COUNT = 2
SLEEP_BETWEEN_RETRIES = 0.8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )
}

CSV_COLUMNS = [
    "date", "drawno",
    "winning1", "winning2", "winning3",
    "special1", "special2", "special3", "special4", "special5",
    "special6", "special7", "special8", "special9", "special10",
    "consolation1", "consolation2", "consolation3", "consolation4", "consolation5",
    "consolation6", "consolation7", "consolation8", "consolation9", "consolation10",
]


def parse_csv_date(value: str) -> date | None:
    value = str(value or "").strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def format_csv_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def suffix_to_date(path: str) -> date:
    m = re.search(rf"{re.escape(FILE_PREFIX)}_(\d{{6}})\.csv$", os.path.basename(path), re.I)
    if not m:
        return date.min
    try:
        return datetime.strptime(m.group(1), "%d%m%y").date()
    except ValueError:
        return date.min


def find_latest_csv() -> str | None:
    files = glob.glob(os.path.join(SCRIPT_DIR, f"{FILE_PREFIX}_*.csv"))
    return max(files, key=suffix_to_date) if files else None


def output_filename(latest_draw_date: date) -> str:
    # Filename uses the latest winning/draw date in the dataset, NOT today's run date.
    return os.path.join(SCRIPT_DIR, f"{FILE_PREFIX}_{latest_draw_date.strftime('%d%m%y')}.csv")


def empty_row(draw_date: str) -> dict:
    row = {c: "" for c in CSV_COLUMNS}
    row["date"] = draw_date
    return row


def row_date(row: dict) -> date | None:
    return parse_csv_date(row.get("date", ""))


def is_4d_number(text: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", str(text or "").strip()))


def clean_cell_text(tag) -> str:
    if tag is None:
        return ""
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()


def pad4(x: str) -> str:
    digits = re.sub(r"\D", "", str(x or ""))
    return digits.zfill(4)[-4:] if digits else ""


def is_suspicious_row(row: dict) -> bool:
    w1, w2, w3 = row.get("winning1", ""), row.get("winning2", ""), row.get("winning3", "")
    # Known bad result from text scrape: labels like 2D/3D become 0002/0003,
    # or the 1st prize is duplicated into the 2nd prize.
    return (
        (w1 == "0002" and w2 == "0003") or
        (w1 and w1 == w2) or
        (w1 in {"0002", "0003", "0004"}) or
        (w2 in {"0002", "0003", "0004"}) or
        not (is_4d_number(w1) and is_4d_number(w2) and is_4d_number(w3))
    )


def load_existing_csv(path: str) -> tuple[list[dict], date | None, set[date]]:
    rows: list[dict] = []
    latest: date | None = None
    suspicious_dates: set[date] = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {c: str(raw.get(c, "") or "").strip() for c in CSV_COLUMNS}
            d = row_date(row)
            if d:
                row["date"] = format_csv_date(d)
                if latest is None or d > latest:
                    latest = d
                if is_suspicious_row(row):
                    suspicious_dates.add(d)
            rows.append(row)
    return rows, latest, suspicious_dates


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def get_html(url: str) -> str | None:
    for attempt in range(RETRY_COUNT + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        if attempt < RETRY_COUNT:
            time.sleep(SLEEP_BETWEEN_RETRIES)
    return None


def parse_header_date_and_draw(block) -> tuple[date | None, str]:
    text = clean_cell_text(block)
    date_match = re.search(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b", text)
    draw_match = re.search(r"#\s*([A-Za-z0-9/\-]+)", text)
    d = datetime.strptime(date_match.group(0), "%d-%b-%Y").date() if date_match else None
    drawno = draw_match.group(1).strip() if draw_match else ""
    return d, drawno


def extract_prizes_from_block(block) -> list[str]:
    # Current and past 4dmoon tables both keep the three main prizes in td.rtn.
    prizes = []
    for td in block.select("td.rtn"):
        value = clean_cell_text(td)
        if is_4d_number(value):
            prizes.append(value)
        if len(prizes) == 3:
            break
    return prizes


def extract_section_numbers(block, section_name: str) -> list[str]:
    # Find the table whose rpl header says Special or Consolation, then collect only td.rbn 4-digit cells.
    for header in block.select("td.rpl"):
        if clean_cell_text(header).lower() == section_name.lower():
            table = header.find_parent("table")
            if not table:
                continue
            nums = []
            for td in table.select("td.rbn"):
                value = clean_cell_text(td)
                if is_4d_number(value):
                    nums.append(value)
            return nums[:10]
    return []


def find_lottery_block(soup: BeautifulSoup):
    # Prefer the exact logo, because the page also contains Toto 5D/6D/Lotto and Magnum jackpot/life tables.
    for img in soup.find_all("img"):
        src = (img.get("src") or "").lower()
        if any(key in src for key in LOGO_SRC_KEYS):
            mbx = img.find_parent("div", class_="mbx")
            if mbx and TARGET_NAME.lower() in clean_cell_text(mbx).lower():
                return mbx

    # Fallback: exact name in an mbx block.
    for mbx in soup.select("div.mbx"):
        txt = clean_cell_text(mbx).lower()
        if TARGET_NAME.lower() in txt:
            return mbx
    return None


def parse_lottery_html(html: str, requested_date: date) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    block = find_lottery_block(soup)
    if not block:
        return None

    actual_date, drawno = parse_header_date_and_draw(block)
    draw_date = actual_date or requested_date

    row = empty_row(format_csv_date(draw_date))
    row["drawno"] = drawno

    prizes = extract_prizes_from_block(block)
    if len(prizes) >= 3:
        row["winning1"], row["winning2"], row["winning3"] = prizes[:3]

    special = extract_section_numbers(block, "Special")
    consolation = extract_section_numbers(block, "Consolation")

    for i, value in enumerate((special + [""] * 10)[:10], 1):
        row[f"special{i}"] = value
    for i, value in enumerate((consolation + [""] * 10)[:10], 1):
        row[f"consolation{i}"] = value

    if is_suspicious_row(row):
        return None
    return row


def scrape_one_day(dt: date) -> dict | None:
    html = get_html(BASE_URL.format(dt.strftime("%Y-%m-%d")))
    if not html:
        return None
    return parse_lottery_html(html, dt)


def merge_rows(existing_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    merged: dict[date, dict] = {}
    invalid_rows: list[dict] = []

    for row in existing_rows:
        d = row_date(row)
        if d:
            row["date"] = format_csv_date(d)
            merged[d] = {c: row.get(c, "") for c in CSV_COLUMNS}
        else:
            invalid_rows.append(row)

    for row in new_rows:
        d = row_date(row)
        if d:
            row["date"] = format_csv_date(d)
            # New scrape replaces old row for the same draw date, fixing old bad rows.
            merged[d] = {c: row.get(c, "") for c in CSV_COLUMNS}

    return invalid_rows + [merged[d] for d in sorted(merged)]


def latest_draw_date(rows: list[dict]) -> date | None:
    dates = [d for d in (row_date(r) for r in rows) if d]
    return max(dates) if dates else None


def save_csv(rows: list[dict], output_path: str):
    rows = sorted(rows, key=lambda r: row_date(r) or date.min)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows([{c: r.get(c, "") for c in CSV_COLUMNS} for r in rows])


def main():
    today = date.today()
    existing_file = find_latest_csv()
    existing_rows: list[dict] = []
    latest_existing: date | None = None
    suspicious_dates: set[date] = set()

    if existing_file:
        print(f"Found existing {TARGET_NAME} dataset: {os.path.basename(existing_file)}")
        existing_rows, latest_existing, suspicious_dates = load_existing_csv(existing_file)
        print(f"  Loaded {len(existing_rows)} rows. Latest draw date in file: {latest_existing}")
        if suspicious_dates:
            print(f"  Found {len(suspicious_dates)} suspicious row(s) to repair.")
    else:
        print(f"No existing {TARGET_NAME} dataset found. Starting full scrape from scratch.")

    if latest_existing:
        start_date = min(latest_existing + timedelta(days=1), today - timedelta(days=RECHECK_DAYS))
    else:
        start_date = FALLBACK_START_DATE

    dates_to_fetch = set(daterange(start_date, today))
    dates_to_fetch.update(suspicious_dates)
    dates_to_fetch = sorted(d for d in dates_to_fetch if d <= today)

    print(f"Fetching/checking {len(dates_to_fetch)} date(s) from 4dmoon...")
    new_rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scrape_one_day, dt): dt for dt in dates_to_fetch}
        total = len(futures)
        for idx, future in enumerate(as_completed(futures), 1):
            dt = futures[future]
            try:
                row = future.result()
                if row:
                    new_rows.append(row)
                    print(f"  [{idx}/{total}] OK   {row['date']} {row['winning1']} {row['winning2']} {row['winning3']}")
                else:
                    print(f"  [{idx}/{total}] SKIP {dt} (no draw / no valid {TARGET_NAME} data)")
            except Exception as e:
                print(f"  [{idx}/{total}] ERROR {dt} → {e}")

    all_rows = merge_rows(existing_rows, new_rows)
    latest = latest_draw_date(all_rows) or today
    out = output_filename(latest)
    save_csv(all_rows, out)
    print(f"\nSaved {len(all_rows)} total rows ({len(new_rows)} scraped/updated) → {os.path.basename(out)}")

    for old in glob.glob(os.path.join(SCRIPT_DIR, f"{FILE_PREFIX}_*.csv")):
        if os.path.abspath(old) != os.path.abspath(out):
            try:
                os.remove(old)
                print(f"Deleted old file: {os.path.basename(old)}")
            except OSError as e:
                print(f"Could not delete {old}: {e}")


if __name__ == "__main__":
    main()
