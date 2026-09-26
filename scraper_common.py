import csv
import glob
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.4dmoon.com/past-results/{}"
LIVE_JSON_URL = "https://www.4dmoon.com/feedwest.json"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FALLBACK_START_DATE = date(1985, 1, 1)
RECHECK_DAYS = 60
MAX_WORKERS = 10
RETRY_PASS_MAX_WORKERS = 3
RETRY_PASS_DELAY_SECONDS = 5
REQUEST_TIMEOUT = 15
RETRY_COUNT = 2
SLEEP_BETWEEN_RETRIES = 0.8
MAX_RETRY_AFTER_WAIT = 30

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

# Shared across all worker threads: reuses TCP/TLS connections (keep-alive)
# instead of opening a new one per request, which matters a lot over a
# multi-decade backfill of thousands of requests.
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=MAX_WORKERS))


@dataclass(frozen=True)
class LotteryConfig:
    target_name: str
    file_prefix: str
    logo_src_keys: list[str]
    live_json_key: str


class FetchFailed(Exception):
    """Page could not be retrieved after retries, for a reason other than a confirmed 404 (no draw)."""


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


def suffix_to_date(cfg: LotteryConfig, path: str) -> date:
    m = re.search(rf"{re.escape(cfg.file_prefix)}_(\d{{6}})\.csv$", os.path.basename(path), re.I)
    if not m:
        return date.min
    try:
        return datetime.strptime(m.group(1), "%d%m%y").date()
    except ValueError:
        return date.min


def find_latest_csv(cfg: LotteryConfig) -> str | None:
    files = glob.glob(os.path.join(SCRIPT_DIR, f"{cfg.file_prefix}_*.csv"))
    return max(files, key=lambda p: suffix_to_date(cfg, p)) if files else None


def output_filename(cfg: LotteryConfig, latest_draw_date: date) -> str:
    # Filename uses the latest winning/draw date in the dataset, NOT today's run date.
    return os.path.join(SCRIPT_DIR, f"{cfg.file_prefix}_{latest_draw_date.strftime('%d%m%y')}.csv")


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


def is_suspicious_row(row: dict) -> bool:
    w1, w2, w3 = row.get("winning1", ""), row.get("winning2", ""), row.get("winning3", "")
    if not (is_4d_number(w1) and is_4d_number(w2) and is_4d_number(w3)):
        return True
    # Known bad result from a broken text scrape: section labels like "2D"/"3D" got
    # misread as the numbers 0002/0003. Matched narrowly (not "w1 in {...}") so a
    # legitimate rare winning number like 0002 isn't flagged as suspicious forever
    # and blocked from ever being re-saved. Identical 1st/2nd prizes are NOT treated
    # as suspicious -- that can legitimately happen (see repo history).
    if w1 == "0002" and w2 == "0003":
        return True
    return False


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
    last_status = None
    last_error = None
    wait = SLEEP_BETWEEN_RETRIES
    for attempt in range(RETRY_COUNT + 1):
        try:
            r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
            last_status = r.status_code
            wait = SLEEP_BETWEEN_RETRIES
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                try:
                    wait = min(float(retry_after), MAX_RETRY_AFTER_WAIT) if retry_after else wait
                except (TypeError, ValueError):
                    pass
        except requests.RequestException as e:
            last_error = e
            wait = SLEEP_BETWEEN_RETRIES
        if attempt < RETRY_COUNT:
            time.sleep(wait)
    # Unlike a 404 (confirmed no draw), this is an unresolved fetch failure
    # (blocked/rate-limited/network error) and must not be treated as "no draw".
    if last_error is not None:
        raise FetchFailed(f"{url} -> {last_error}")
    raise FetchFailed(f"{url} -> HTTP {last_status}")


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


def find_lottery_block(cfg: LotteryConfig, soup: BeautifulSoup):
    # Prefer the exact logo, because the page also contains Toto 5D/6D/Lotto and Magnum jackpot/life tables.
    for img in soup.find_all("img"):
        src = (img.get("src") or "").lower()
        if any(key in src for key in cfg.logo_src_keys):
            mbx = img.find_parent("div", class_="mbx")
            if mbx and cfg.target_name.lower() in clean_cell_text(mbx).lower():
                return mbx

    # Fallback: exact name in an mbx block.
    for mbx in soup.select("div.mbx"):
        txt = clean_cell_text(mbx).lower()
        if cfg.target_name.lower() in txt:
            return mbx
    return None


def parse_lottery_html(cfg: LotteryConfig, html: str, requested_date: date) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    block = find_lottery_block(cfg, soup)
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


def scrape_live_json(cfg: LotteryConfig, dt: date) -> dict | None:
    try:
        r = SESSION.get(LIVE_JSON_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        prov_data = data.get(cfg.live_json_key)
        if not prov_data:
            return None

        dd_str = prov_data.get("DD", "")
        match = re.search(r"\d{1,2}-[A-Za-z]{3}-\d{4}", dd_str)
        if not match:
            return None
        draw_date = datetime.strptime(match.group(0), "%d-%b-%Y").date()
        if draw_date != dt:
            return None

        row = empty_row(format_csv_date(draw_date))
        dn = prov_data.get("DN", "")
        m = re.search(r"#\s*([A-Za-z0-9/\-]+)", dn)
        row["drawno"] = m.group(1).strip() if m else dn.strip()

        row["winning1"] = prov_data.get("P1", "")
        row["winning2"] = prov_data.get("P2", "")
        row["winning3"] = prov_data.get("P3", "")

        specials = []
        for i in range(1, 15):
            val = prov_data.get(f"S{i}", "")
            if is_4d_number(val):
                specials.append(val)
        for i, value in enumerate((specials + [""] * 10)[:10], 1):
            row[f"special{i}"] = value

        cons = []
        for i in range(1, 15):
            val = prov_data.get(f"C{i}", "")
            if is_4d_number(val):
                cons.append(val)
        for i, value in enumerate((cons + [""] * 10)[:10], 1):
            row[f"consolation{i}"] = value

        if is_suspicious_row(row):
            return None
        return row
    except Exception as e:
        print(f"  (live JSON unavailable for {cfg.target_name}: {e})")
        return None


def scrape_one_day(cfg: LotteryConfig, dt: date) -> dict | None:
    if dt == date.today():
        live_row = scrape_live_json(cfg, dt)
        if live_row:
            return live_row

    html = get_html(BASE_URL.format(dt.strftime("%Y-%m-%d")))
    if not html:
        return None
    return parse_lottery_html(cfg, html, dt)


def merge_rows(existing_rows: list[dict], new_rows: list[dict]) -> tuple[list[dict], int]:
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

    all_rows = invalid_rows + [merged[d] for d in sorted(merged)]
    return all_rows, len(invalid_rows)


def latest_draw_date(rows: list[dict]) -> date | None:
    dates = [d for d in (row_date(r) for r in rows) if d]
    return max(dates) if dates else None


def print_row_result(cfg: LotteryConfig, row: dict | None, target_date: date):
    print(f"{cfg.target_name} Results - {format_csv_date(target_date)}")
    if not row:
        print("No draw result found for this date.\n")
        return

    print(f"1st prize: {row['winning1']}")
    print(f"2nd prize: {row['winning2']}")
    print(f"3rd prize: {row['winning3']}")

    special = [row[f"special{i}"] for i in range(1, 11) if row[f"special{i}"]]
    consolation = [row[f"consolation{i}"] for i in range(1, 11) if row[f"consolation{i}"]]

    print(f"Special: {', '.join(special)}")
    print(f"Consolation: {', '.join(consolation)}")
    print()


def print_result_for_date(cfg: LotteryConfig, rows: list[dict], target_date: date):
    row = next((r for r in rows if row_date(r) == target_date), None)
    print_row_result(cfg, row, target_date)


def save_csv(rows: list[dict], output_path: str):
    rows = sorted(rows, key=lambda r: row_date(r) or date.min)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows([{c: r.get(c, "") for c in CSV_COLUMNS} for r in rows])


def fetch_dates(cfg: LotteryConfig, dates: list[date], max_workers: int, label: str = "") -> tuple[list[dict], list[date]]:
    rows: list[dict] = []
    failed: list[date] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(scrape_one_day, cfg, dt): dt for dt in dates}
        total = len(futures)
        for idx, future in enumerate(as_completed(futures), 1):
            dt = futures[future]
            dt_str = format_csv_date(dt)
            prefix = f"  [{idx}/{total}]{label}"
            try:
                row = future.result()
                if row:
                    rows.append(row)
                    print(f"{prefix} OK     {row['date']} {row['winning1']} {row['winning2']} {row['winning3']}")
                else:
                    print(f"{prefix} SKIP   {dt_str} (confirmed no draw / no valid {cfg.target_name} data)")
            except FetchFailed as e:
                failed.append(dt)
                print(f"{prefix} FAILED {dt_str} -> could not fetch page ({e})")
            except Exception as e:
                failed.append(dt)
                print(f"{prefix} ERROR  {dt_str} -> {e}")
    return rows, failed


def run_scraper(target_name: str, file_prefix: str, logo_src_keys: list[str], live_json_key: str):
    cfg = LotteryConfig(
        target_name=target_name,
        file_prefix=file_prefix,
        logo_src_keys=logo_src_keys,
        live_json_key=live_json_key,
    )

    today = date.today()
    existing_file = find_latest_csv(cfg)
    existing_rows: list[dict] = []
    latest_existing: date | None = None
    suspicious_dates: set[date] = set()

    if existing_file:
        print(f"Found existing {cfg.target_name} dataset: {os.path.basename(existing_file)}")
        existing_rows, latest_existing, suspicious_dates = load_existing_csv(existing_file)
        print(f"  Loaded {len(existing_rows)} rows. Latest draw date in file: {latest_existing}")
        if suspicious_dates:
            print(f"  Found {len(suspicious_dates)} suspicious row(s) to repair.")
    else:
        print(f"No existing {cfg.target_name} dataset found. Starting full scrape from scratch.")

    if latest_existing:
        start_date = min(latest_existing + timedelta(days=1), today - timedelta(days=RECHECK_DAYS))
    else:
        start_date = FALLBACK_START_DATE

    dates_to_fetch = set(daterange(start_date, today))
    dates_to_fetch.update(suspicious_dates)
    dates_to_fetch = sorted(d for d in dates_to_fetch if d <= today)

    print(f"Fetching/checking {len(dates_to_fetch)} date(s) from 4dmoon...")
    new_rows, failed_dates = fetch_dates(cfg, dates_to_fetch, max_workers=MAX_WORKERS)

    if failed_dates:
        print(
            f"\n{len(failed_dates)} date(s) failed to fetch (not confirmed as 'no draw') -- "
            f"waiting {RETRY_PASS_DELAY_SECONDS}s and retrying once at lower concurrency..."
        )
        time.sleep(RETRY_PASS_DELAY_SECONDS)
        retried_rows, still_failed = fetch_dates(
            cfg, sorted(failed_dates), max_workers=RETRY_PASS_MAX_WORKERS, label=" retry"
        )
        new_rows.extend(retried_rows)
        if still_failed:
            print(
                f"\nWARNING: {len(still_failed)} date(s) could not be fetched after retrying. "
                "They are NOT confirmed as having no draw and are left out of this run's output:"
            )
            for dt in sorted(still_failed):
                print(f"  - {dt}")
            print("Re-run the script later to attempt these again.")

    all_rows, invalid_count = merge_rows(existing_rows, new_rows)
    if invalid_count:
        print(f"\nKept {invalid_count} existing row(s) with an unparseable date -- left untouched.")

    latest = latest_draw_date(all_rows) or today
    out = output_filename(cfg, latest)
    save_csv(all_rows, out)
    print(f"\nSaved {len(all_rows)} total rows ({len(new_rows)} scraped/updated) -> {os.path.basename(out)}")

    if len(all_rows) < len(existing_rows):
        print(
            f"WARNING: new dataset has FEWER rows ({len(all_rows)}) than the existing file "
            f"({len(existing_rows)}). Skipping deletion of old file(s) so you don't lose data -- "
            "investigate before re-running."
        )
        return

    for old in glob.glob(os.path.join(SCRIPT_DIR, f"{cfg.file_prefix}_*.csv")):
        if os.path.abspath(old) != os.path.abspath(out):
            try:
                os.remove(old)
                print(f"Deleted old file: {os.path.basename(old)}")
            except OSError as e:
                print(f"Could not delete {old}: {e}")

    print()
    print_result_for_date(cfg, all_rows, latest)
