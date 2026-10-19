"""Download Nifty 500 daily TRI/NTR history from NSE Indices in <=365-day chunks.

The site exposes an underlying POST endpoint used by its Historical Data page.
This endpoint is undocumented and may change; script validates the response and
keeps a partial CSV if any chunk fails.

Usage:
    python TRI/NIFTY_500_TRI.py
    python TRI/NIFTY_500_TRI.py --start-date 2009-01-01 --end-date 2026-06-08
    python TRI/NIFTY_500_TRI.py --output TRI/my_nifty500_tri.csv

Install dependency if needed: python -m pip install requests
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://www.niftyindices.com/BackPage/getTotalReturnIndexString"
REFERER = "https://www.niftyindices.com/reports/historical-data"
INDEX_NAME = "NIFTY 500"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "NIFTY_500_TRI.csv"
CSV_FIELDS = ["date", "index_name", "total_return_index", "net_total_return_index"]


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM-DD date, got {value!r}") from exc


def chunks(start: date, end: date, max_days: int = 365):
    """Yield contiguous inclusive ranges, each no longer than max_days."""
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_days - 1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def make_payload(start: date, end: date) -> dict[str, str]:
    # NSE page's ASP.NET endpoint expects cinfo as a JSON string containing
    # single-quoted fields, wrapped in ordinary outer JSON.
    start_text = start.strftime("%d-%b-%Y")
    end_text = end.strftime("%d-%b-%Y")
    cinfo = (
        "{'name':'NIFTY 500',"
        f"'startDate':'{start_text}','endDate':'{end_text}',"
        "'indexName':'NIFTY 500'}"
    )
    return {"cinfo": cinfo}


def parse_api_date(value: Any) -> date:
    value = str(value).strip()
    for fmt in ("%d %b %Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date in NSE TRI response: {value!r}")


def parse_number(value: Any) -> float | None:
    if value is None or str(value).strip() in {"", "-", "NA", "N/A"}:
        return None
    return float(str(value).replace(",", "").strip())


def fetch_chunk(session: requests.Session, start: date, end: date,
                retries: int = 4, timeout: int = 60) -> list[dict[str, Any]]:
    payload = make_payload(start, end)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.post(ENDPOINT, json=payload, timeout=timeout)
            response.raise_for_status()
            try:
                outer = response.json()
            except ValueError as exc:
                excerpt = response.text[:300].replace("\r", " ").replace("\n", " ")
                raise RuntimeError(
                    f"NSE returned non-JSON for {start}..{end}; HTTP {response.status_code}, "
                    f"content-type {response.headers.get('Content-Type')!r}, body {excerpt!r}"
                ) from exc
            # Current endpoint returns an array; old endpoint wrapped it in
            # {"d": "<JSON array string>"}. Accept both formats.
            if isinstance(outer, dict) and "d" in outer:
                inner = outer["d"]
                if inner in (None, "false", False):
                    raise RuntimeError(f"NSE returned no TRI payload for {start}..{end}: {outer!r}")
                rows = json.loads(inner) if isinstance(inner, str) else inner
            else:
                rows = outer
            if not isinstance(rows, list):
                excerpt = response.text[:300].replace("\r", " ").replace("\n", " ")
                raise RuntimeError(
                    f"Unexpected NSE TRI response for {start}..{end}; "
                    f"HTTP {response.status_code}, content-type "
                    f"{response.headers.get('Content-Type')!r}, body {excerpt!r}"
                )
            parsed = []
            for row in rows:
                if not isinstance(row, dict) or "Date" not in row or "TotalReturnsIndex" not in row:
                    continue
                parsed.append({
                    "date": parse_api_date(row["Date"]).isoformat(),
                    "index_name": str(row.get("Index Name", INDEX_NAME)),
                    "total_return_index": parse_number(row.get("TotalReturnsIndex")),
                    "net_total_return_index": parse_number(row.get("NTR_Value")),
                })
            return parsed
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.5 ** attempt)
    raise RuntimeError(f"Failed NSE TRI range {start}..{end} after {retries} attempts: {last_error}")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)
    temp.replace(path)


def download(start: date, end: date, output: Path, delay_seconds: float) -> list[dict[str, Any]]:
    if end < start:
        raise ValueError("end-date must be on or after start-date")
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://www.niftyindices.com",
        "Referer": REFERER,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest",
    })
    # Seed session/cookies from current Historical Data page before API POSTs.
    warmup = session.get(REFERER, timeout=30)
    warmup.raise_for_status()
    all_rows: dict[str, dict[str, Any]] = {}
    ranges = list(chunks(start, end))
    partial_path = output.with_name(output.stem + ".partial" + output.suffix)
    try:
        for number, (chunk_start, chunk_end) in enumerate(ranges, start=1):
            print(f"[{number}/{len(ranges)}] Fetching {chunk_start} to {chunk_end}...")
            chunk_rows = fetch_chunk(session, chunk_start, chunk_end)
            for row in chunk_rows:
                if start.isoformat() <= row["date"] <= end.isoformat():
                    all_rows[row["date"]] = row
            # Preserve completed ranges if a later request fails.
            write_csv(partial_path, sorted(all_rows.values(), key=lambda row: row["date"]))
            if delay_seconds and number < len(ranges):
                time.sleep(delay_seconds)
    except Exception:
        if all_rows:
            print(f"Partial data saved: {partial_path}", file=sys.stderr)
        raise
    if not all_rows:
        raise RuntimeError("NSE returned zero TRI rows for requested period.")
    records = sorted(all_rows.values(), key=lambda row: row["date"])
    write_csv(output, records)
    partial_path.unlink(missing_ok=True)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=parse_date, default=date(1999, 1, 1),
                        help="Inclusive start (YYYY-MM-DD); default 1999-01-01.")
    parser.add_argument("--end-date", type=parse_date, default=date.today(),
                        help="Inclusive end (YYYY-MM-DD); default today.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="CSV output path.")
    parser.add_argument("--delay-seconds", type=float, default=0.3,
                        help="Pause between requests.")
    args = parser.parse_args()
    if args.delay_seconds < 0:
        parser.error("--delay-seconds must be nonnegative")
    try:
        records = download(args.start_date, args.end_date, args.output, args.delay_seconds)
    except Exception as exc:
        parser.error(str(exc))
    print(f"Saved {len(records):,} daily rows: {records[0]['date']} to {records[-1]['date']}")
    print(f"TRI CSV: {args.output.resolve()}")
    print("Columns include gross Total Return Index and Net Total Return Index.")


if __name__ == "__main__":
    main()
