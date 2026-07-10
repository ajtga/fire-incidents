from __future__ import annotations

import csv
import hashlib
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


SOURCE_URL = "https://www.cbm.al.gov.br/paginas/ocorrencias/true"

OUTPUT_DIR = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "cbmal_fire_incidents.csv"

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


def normalize_text(value: str | None) -> str:
    if not value:
        return ""

    text = unescape(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_incident_id(row: dict[str, str]) -> str:
    raw_key = "|".join(
        normalize_text(row.get(field, "")).upper()
        for field in DEDUP_FIELDS
    )

    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


def load_html(url: str = SOURCE_URL, max_attempts: int = 3) -> str:
    import random

    last_error = None

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ]
    # Randomly select unique User-Agents for each attempt of this run
    selected_agents = random.sample(user_agents, min(max_attempts, len(user_agents)))

    for attempt in range(1, max_attempts + 1):
        if attempt - 1 < len(selected_agents):
            user_agent = selected_agents[attempt - 1]
        else:
            user_agent = random.choice(user_agents)

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
            print(f"Fetching CBMAL page. Attempt {attempt}/{max_attempts}...")

            with urlopen(request, timeout=15) as response:
                return response.read().decode("utf-8", errors="replace")

        except HTTPError as exc:
            last_error = exc

            if exc.code not in {408, 429, 500, 502, 503, 504}:
                raise RuntimeError(
                    f"HTTP error while accessing CBMAL page: {exc.code} {exc.reason}"
                ) from exc

            if attempt == max_attempts:
                break

            wait_seconds = attempt * 5
            print(
                f"Temporary HTTP error {exc.code} while accessing CBMAL page. "
                f"Retrying in {wait_seconds} seconds..."
            )
            time.sleep(wait_seconds)

        except (URLError, SocketTimeout, TimeoutError) as exc:
            last_error = exc

            if attempt == max_attempts:
                break

            wait_seconds = attempt * 5
            print(
                f"Network error while accessing CBMAL page: {exc}. "
                f"Retrying in {wait_seconds} seconds..."
            )
            time.sleep(wait_seconds)

    raise RuntimeError(
        f"Failed to access CBMAL page after {max_attempts} attempts. "
        f"Last error: {last_error}"
    )

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

        merged[clean_row["incident_id"]] = clean_row

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


def main() -> None:
    scraped_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    html_text = load_html()
    extracted_rows = extract_occurrences(html_text, scraped_at_utc)

    if not extracted_rows:
        raise RuntimeError(
            "No occurrences were extracted. The CBMAL page structure may have changed."
        )

    new_fire_incidents = [
        row
        for row in extracted_rows
        if is_fire_incident(row)
    ]

    existing_rows = read_existing_rows(OUTPUT_FILE)
    merged_rows = merge_rows(existing_rows, new_fire_incidents)

    print(f"Occurrences extracted: {len(extracted_rows)}")
    print(f"Fire incidents extracted: {len(new_fire_incidents)}")
    print(f"Existing fire incidents: {len(existing_rows)}")
    print(f"Merged fire incidents: {len(merged_rows)}")

    if OUTPUT_FILE.exists() and len(merged_rows) == len(existing_rows):
        print("No new fire incident found. Dataset was not changed.")
        return

    write_rows(OUTPUT_FILE, merged_rows)

    print(f"Dataset saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()