from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from bs4 import BeautifulSoup

# Configure logging to sys.stdout with a clean ISO timestamp format.
# StreamHandler handles flushing automatically.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
    handlers=[logging.StreamHandler(sys.stdout)]
)


SOURCE_URL = "https://www.cbm.al.gov.br/paginas/ocorrencias/true"

OUTPUT_DIR = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "cbmal_fire_incidents.csv"
RUN_LOG_FILE = OUTPUT_DIR / "scraper_run_log.csv"

FIELDNAMES = [
    "incident_id",
    "scraped_at_utc",
    "orgao",
    "data",
    "hora",
    "cidade",
    "tipo",
    "detalhe",
    "local",
    "viaturas",
    "militares",
    "latitude",
    "longitude",
]

DEDUP_FIELDS = [
    "orgao",
    "data",
    "hora",
    "cidade",
    "tipo",
    "detalhe",
    "local",
    "viaturas",
    "militares",
]

RUN_LOG_FIELDNAMES = [
    "run_id",
    "run_started_at_utc",
    "run_finished_at_utc",
    "success",
    "exit_reason",
    "error_message",
    "fetch_duration_s",
    "total_duration_s",
    "attempts_used",
    "max_attempts",
    "last_http_status",
    "user_agents_tried",
    "occurrences_extracted",
    "fire_incidents_extracted",
    "fire_incidents_existing",
    "fire_incidents_after_merge",
    "new_fire_incidents_added",
    "dataset_changed",
    "geocoding_attempted",
    "geocoding_succeeded",
    "geocoding_failed",
    "response_size_bytes",
    "source_url",
    "trigger",
    "gh_run_id",
    "gh_run_number",
    "python_version",
    "runner_os",
]


@dataclass
class LoadResult:
    html: str = ""
    success: bool = False
    attempts_used: int = 0
    max_attempts: int = 0
    total_duration_s: float = 0.0
    user_agents_tried: list[str] = field(default_factory=list)
    last_error: str = ""
    last_http_status: int | None = None
    response_size_bytes: int | None = None


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "cbmal-fire-incidents-scraper/1.0 (https://github.com/ajtga/fire-incidents)"


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    text = unescape(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_address_for_geocoding(raw_address: str, cidade: str) -> str:
    """Clean a CBMAL address string to maximize Nominatim geocoding success.

    Typical patterns in the `local` column:
      "RUA TAVARES BASTOS, UNIÃO DOS PALMARES-AL"
      "RUA JÚLIO PAIXÃO DA SILVA, 14, ARAPIRACA-AL"
      "LOTEAMNETO VILA RICA , RUA DOIS, QD G1 NUMERO B7 RIO LARGO, RIO LARGO-AL"
      "RODOVIA AL - 101 NORTE, JAPARATINGA-AL"
      "R. PROFA. MARIA ESTHER DA COSTA BARROS, 306 - JATIÚCA, MACEIÓ - AL, 57036-840, MACEIÓ-AL"

    Strategy:
      1. Strip the trailing "CITY-AL" suffix (redundant with the `cidade` column).
      2. Remove lot / block / unit noise (QD, QUADRA, LOTE, Nº, NUMERO, CASA, etc.).
      3. Remove building / condo prefixes that confuse Nominatim (EDF., ED., EDIFÍCIO,
         RESIDENCIAL, CONJUNTO, CJ., CONJ.).
      4. Remove CEP (zip code) patterns.
      5. Collapse extra commas / whitespace.
    """
    addr = raw_address.strip()

    # 1. Remove trailing city-state suffix  (e.g. ", MACEIÓ-AL" or ", MACEIÓ - AL")
    addr = re.sub(r",\s*" + re.escape(cidade) + r"\s*-\s*AL\s*$", "", addr, flags=re.I)
    # Also handle when the suffix uses a slightly different city spelling
    addr = re.sub(r",\s*[A-ZÀ-Ú ]+\s*-\s*AL\s*$", "", addr, flags=re.I)

    # 2. Remove CEP (zip codes like 57036-840)
    addr = re.sub(r"\b\d{5}-\d{3}\b", "", addr)

    # 3. Remove lot/block/unit noise
    addr = re.sub(
        r"\b(?:QD|QUADRA|LOTE|NUMERO|Nº|N°|CASA)\s*[A-Z0-9/-]+",
        "", addr, flags=re.I,
    )

    # 4. Remove building / condo prefixes
    addr = re.sub(
        r"\b(?:EDF\.?|ED\.?|EDIFÍCIO|RESIDENCIAL|CONJUNTO|CJ\.?|CONJ\.?)\s+[A-ZÀ-Ú0-9 ]+,?",
        "", addr, flags=re.I,
    )

    # 5. Remove "S/N" (sem número)
    addr = re.sub(r"\bS/N\b", "", addr, flags=re.I)

    # 6. Collapse artifacts: repeated commas, leading/trailing commas, extra whitespace
    addr = re.sub(r"\s*,\s*,+\s*", ", ", addr)
    addr = re.sub(r"\s+", " ", addr).strip(", ")

    return addr


def geocode_address(
    raw_address: str,
    cidade: str,
) -> tuple[float | None, float | None]:
    """Geocode an address using the Nominatim API.

    Returns (latitude, longitude) or (None, None) on failure.
    Respects Nominatim rate limits with a 1.5 s sleep after every request.
    """
    cleaned = clean_address_for_geocoding(raw_address, cidade)

    # Build a structured query: street part + city + state
    query = f"{cleaned}, {cidade}, Alagoas, Brazil"

    params = urlencode({
        "q": query,
        "format": "jsonv2",
        "limit": "1",
        "countrycodes": "br",
    })

    url = f"{NOMINATIM_URL}?{params}"
    request = Request(url, headers={"User-Agent": NOMINATIM_USER_AGENT})

    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data:
            lat = round(float(data[0]["lat"]), 7)
            lon = round(float(data[0]["lon"]), 7)
            logging.info(f"Geocoded: {query!r} -> ({lat}, {lon})")
            return lat, lon

        logging.warning(f"Geocode MISS: {query!r} -> no results")
        return None, None

    except Exception as exc:
        logging.error(f"Geocode ERROR: {query!r} -> {exc}")
        return None, None

    finally:
        time.sleep(1.5)


def make_incident_id(row: dict[str, str]) -> str:
    raw_key = "|".join(
        normalize_text(row.get(field, "")).upper()
        for field in DEDUP_FIELDS
    )

    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


def load_html(url: str = SOURCE_URL, max_attempts: int = 1, timeout: int = 30) -> LoadResult:
    import random

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ]
    # Randomly select unique User-Agents for each attempt of this run
    selected_agents = random.sample(user_agents, min(max_attempts, len(user_agents)))

    result = LoadResult(max_attempts=max_attempts)
    t0 = time.monotonic()

    for attempt in range(1, max_attempts + 1):
        if attempt - 1 < len(selected_agents):
            user_agent = selected_agents[attempt - 1]
        else:
            user_agent = random.choice(user_agents)

        result.user_agents_tried.append(user_agent)
        result.attempts_used = attempt

        request = Request(
            url,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
            },
        )

        try:
            logging.info(f"Fetching CBMAL page. Attempt {attempt}/{max_attempts}...")

            with urlopen(request, timeout=timeout) as response:
                raw_bytes = response.read()
                result.html = raw_bytes.decode("utf-8", errors="replace")
                result.success = True
                result.response_size_bytes = len(raw_bytes)
                result.total_duration_s = round(time.monotonic() - t0, 3)
                return result

        except HTTPError as exc:
            result.last_error = (
                f"HTTP error while accessing CBMAL page: {exc.code} {exc.reason}"
            )
            result.last_http_status = exc.code

            if exc.code not in {408, 429, 500, 502, 503, 504}:
                result.total_duration_s = round(time.monotonic() - t0, 3)
                return result

            if attempt == max_attempts:
                break

            wait_seconds = attempt * 5
            logging.warning(
                f"Temporary HTTP error {exc.code} while accessing CBMAL page. "
                f"Retrying in {wait_seconds} seconds..."
            )
            time.sleep(wait_seconds)

        except (URLError, SocketTimeout, TimeoutError) as exc:
            result.last_error = (
                f"Network error while accessing CBMAL page: {exc}"
            )

            if attempt == max_attempts:
                break

            wait_seconds = attempt * 5
            logging.warning(
                f"Network error while accessing CBMAL page: {exc}. "
                f"Retrying in {wait_seconds} seconds..."
            )
            time.sleep(wait_seconds)

    result.last_error = (
        f"Failed to access CBMAL page after {max_attempts} attempts. "
        f"Last error: {result.last_error}"
    )
    result.total_duration_s = round(time.monotonic() - t0, 3)
    return result


def text_after_icon(container, icon_class: str) -> str:
    icon = container.select_one(f"i.{icon_class}")

    if not icon:
        return ""

    parent = icon.parent

    if not parent:
        return ""

    return normalize_text(parent.get_text(" ", strip=True))


def extract_header_fields(header) -> dict[str, str]:
    text = normalize_text(header.get_text(" ", strip=True))

    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    time_match = re.search(r"\b(\d{2}:\d{2}:\d{2})\b", text)

    red_span = header.find(
        "span",
        style=re.compile(r"color\s*:\s*#ff0000", re.I),
    )

    orgao = normalize_text(red_span.get_text(" ", strip=True)) if red_span else ""
    cidade = text_after_icon(header, "fa-globe")

    tipo = ""

    for span in header.select("span.hidden-xs"):
        candidate = normalize_text(span.get_text(" ", strip=True))

        if candidate and not re.match(r"\d{4}-\d{2}-\d{2}", candidate):
            tipo = candidate
            break

    return {
        "orgao": orgao,
        "data": date_match.group(1) if date_match else "",
        "hora": time_match.group(1) if time_match else "",
        "cidade": cidade,
        "tipo": tipo,
    }


def extract_body_fields(body) -> dict[str, str]:
    return {
        "detalhe": text_after_icon(body, "fa-info-circle"),
        "local": text_after_icon(body, "fa-map-marker"),
        "viaturas": text_after_icon(body, "fa-truck"),
        "militares": text_after_icon(body, "fa-users"),
    }


def extract_occurrences(html_text: str, scraped_at_utc: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    rows = []

    for body in soup.select('div.panel-collapse[id^="faq-"]'):
        panel_id = body.get("id", "")
        header = soup.select_one(f'a[href="#{panel_id}"]')

        if not header:
            continue

        row = {
            "scraped_at_utc": scraped_at_utc,
            **extract_header_fields(header),
            **extract_body_fields(body),
        }

        row["incident_id"] = make_incident_id(row)
        rows.append(row)

    return rows


def is_fire_incident(row: dict[str, str]) -> bool:
    return normalize_text(row.get("tipo", "")).upper() == "INCÊNDIO"


def read_existing_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []

    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with csv_path.open("r", encoding=encoding, newline="") as csv_file:
                return list(csv.DictReader(csv_file))
        except UnicodeDecodeError:
            continue

    return []


def merge_rows(
    existing_rows: list[dict[str, str]],
    new_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}

    for row in existing_rows + new_rows:
        clean_row = {
            field: normalize_text(row.get(field, ""))
            for field in FIELDNAMES
        }

        if not clean_row["incident_id"]:
            clean_row["incident_id"] = make_incident_id(clean_row)

        iid = clean_row["incident_id"]

        # Preserve existing coordinates — don't overwrite with blanks
        if iid in merged:
            for coord in ("latitude", "longitude"):
                if not clean_row.get(coord) and merged[iid].get(coord):
                    clean_row[coord] = merged[iid][coord]

        merged[iid] = clean_row

    return sorted(
        merged.values(),
        key=lambda row: (
            row.get("data", ""),
            row.get("hora", ""),
            row.get("incident_id", ""),
        ),
    )


def write_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def append_run_log(
    log_path: Path,
    *,
    run_id: str,
    run_started_at_utc: str,
    run_finished_at_utc: str,
    success: bool,
    exit_reason: str,
    error_message: str = "",
    fetch_duration_s: float = 0.0,
    total_duration_s: float = 0.0,
    attempts_used: int = 0,
    max_attempts: int = 0,
    last_http_status: int | None = None,
    user_agents_tried: list[str] | None = None,
    occurrences_extracted: int = 0,
    fire_incidents_extracted: int = 0,
    fire_incidents_existing: int = 0,
    fire_incidents_after_merge: int = 0,
    new_fire_incidents_added: int = 0,
    dataset_changed: bool = False,
    geocoding_attempted: int = 0,
    geocoding_succeeded: int = 0,
    geocoding_failed: int = 0,
    response_size_bytes: int | None = None,
    source_url: str = SOURCE_URL,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    write_header = not log_path.exists() or log_path.stat().st_size == 0

    row = {
        "run_id": run_id,
        "run_started_at_utc": run_started_at_utc,
        "run_finished_at_utc": run_finished_at_utc,
        "success": success,
        "exit_reason": exit_reason,
        "error_message": error_message,
        "fetch_duration_s": round(fetch_duration_s, 3),
        "total_duration_s": round(total_duration_s, 3),
        "attempts_used": attempts_used,
        "max_attempts": max_attempts,
        "last_http_status": last_http_status if last_http_status is not None else "",
        "user_agents_tried": ";".join(user_agents_tried or []),
        "occurrences_extracted": occurrences_extracted,
        "fire_incidents_extracted": fire_incidents_extracted,
        "fire_incidents_existing": fire_incidents_existing,
        "fire_incidents_after_merge": fire_incidents_after_merge,
        "new_fire_incidents_added": new_fire_incidents_added,
        "dataset_changed": dataset_changed,
        "geocoding_attempted": geocoding_attempted,
        "geocoding_succeeded": geocoding_succeeded,
        "geocoding_failed": geocoding_failed,
        "response_size_bytes": response_size_bytes if response_size_bytes is not None else "",
        "source_url": source_url,
        "trigger": os.environ.get("GITHUB_EVENT_NAME", "local"),
        "gh_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "gh_run_number": os.environ.get("GITHUB_RUN_NUMBER", ""),
        "python_version": sys.version.split()[0],
        "runner_os": os.environ.get("RUNNER_OS", "local"),
    }

    with log_path.open("a", encoding="utf-8", newline="") as log_file:
        writer = csv.DictWriter(log_file, fieldnames=RUN_LOG_FIELDNAMES)

        if write_header:
            writer.writeheader()

        writer.writerow(row)


def main() -> None:
    run_id = uuid4().hex[:12]
    run_started_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.monotonic()

    # Shared log kwargs — populated progressively and written at the end
    log_kwargs: dict = {
        "run_id": run_id,
        "run_started_at_utc": run_started_at_utc,
    }

    try:
        scraped_at_utc = run_started_at_utc

        result = load_html()

        log_kwargs.update(
            fetch_duration_s=result.total_duration_s,
            attempts_used=result.attempts_used,
            max_attempts=result.max_attempts,
            last_http_status=result.last_http_status,
            user_agents_tried=result.user_agents_tried,
            response_size_bytes=result.response_size_bytes,
        )

        if not result.success:
            log_kwargs.update(
                run_finished_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                total_duration_s=time.monotonic() - t0,
                success=False,
                exit_reason="fetch_failed",
                error_message=result.last_error,
            )
            append_run_log(RUN_LOG_FILE, **log_kwargs)
            logging.error(f"ERROR: {result.last_error}")
            sys.exit(1)

        extracted_rows = extract_occurrences(result.html, scraped_at_utc)

        if not extracted_rows:
            error_msg = "No occurrences were extracted. The CBMAL page structure may have changed."
            log_kwargs.update(
                run_finished_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                total_duration_s=time.monotonic() - t0,
                success=False,
                exit_reason="no_occurrences",
                error_message=error_msg,
            )
            append_run_log(RUN_LOG_FILE, **log_kwargs)
            logging.error(f"ERROR: {error_msg}")
            sys.exit(1)

        new_fire_incidents = [
            row
            for row in extracted_rows
            if is_fire_incident(row)
        ]

        existing_rows = read_existing_rows(OUTPUT_FILE)
        existing_ids = {row.get("incident_id") for row in existing_rows}
        merged_rows = merge_rows(existing_rows, new_fire_incidents)

        logging.info(f"Occurrences extracted: {len(extracted_rows)}")
        logging.info(f"Fire incidents extracted: {len(new_fire_incidents)}")
        logging.info(f"Existing fire incidents: {len(existing_rows)}")
        logging.info(f"Merged fire incidents: {len(merged_rows)}")

        dataset_changed = not (OUTPUT_FILE.exists() and len(merged_rows) == len(existing_rows))

        # --- Geocode only truly new incidents ---
        geocoding_attempted = 0
        geocoding_succeeded = 0
        geocoding_failed = 0

        if dataset_changed:
            truly_new = [
                row for row in merged_rows
                if row["incident_id"] not in existing_ids
            ]
            geocoding_attempted = len(truly_new)

            if truly_new:
                logging.info(f"Geocoding {len(truly_new)} new incident(s)...")

            for row in truly_new:
                lat, lon = geocode_address(row.get("local", ""), row.get("cidade", ""))
                row["latitude"] = str(lat) if lat is not None else ""
                row["longitude"] = str(lon) if lon is not None else ""
                if lat is not None:
                    geocoding_succeeded += 1
                else:
                    geocoding_failed += 1

        if not dataset_changed:
            logging.info("No new fire incident found. Dataset was not changed.")
        else:
            write_rows(OUTPUT_FILE, merged_rows)
            logging.info(f"Dataset saved to: {OUTPUT_FILE}")

        if geocoding_attempted:
            logging.info(
                f"Geocoding results: {geocoding_succeeded}/{geocoding_attempted} succeeded, "
                f"{geocoding_failed} failed."
            )

        log_kwargs.update(
            run_finished_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            total_duration_s=time.monotonic() - t0,
            success=True,
            exit_reason="ok",
            occurrences_extracted=len(extracted_rows),
            fire_incidents_extracted=len(new_fire_incidents),
            fire_incidents_existing=len(existing_rows),
            fire_incidents_after_merge=len(merged_rows),
            new_fire_incidents_added=len(merged_rows) - len(existing_rows),
            dataset_changed=dataset_changed,
            geocoding_attempted=geocoding_attempted,
            geocoding_succeeded=geocoding_succeeded,
            geocoding_failed=geocoding_failed,
        )
        append_run_log(RUN_LOG_FILE, **log_kwargs)

    except SystemExit:
        raise

    except Exception as exc:
        log_kwargs.update(
            run_finished_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            total_duration_s=time.monotonic() - t0,
            success=False,
            exit_reason="unexpected_error",
            error_message=str(exc),
        )
        append_run_log(RUN_LOG_FILE, **log_kwargs)
        logging.error(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()