# CBMAL Fire Incidents Scraper

A lightweight tool to scrape, parse, and geocode fire incident reports published by **CBMAL** (*Corpo de Bombeiros Militar de Alagoas*).

The project aggregates incident data into a structured CSV dataset and enriches records with estimated latitude and longitude coordinates using automated geocoding.

---

## ⚠️ Disclaimer: Coordinate Accuracy

> **IMPORTANT**: The latitude and longitude coordinates in this dataset are **approximations** and must not be relied upon as exact locations.

In many cases, the original scraped reports simply do not provide enough location detail to make a precise estimate. Both automated geocoding (via OpenStreetMap's Nominatim API) and manual coordinate entries rely on limited context—often falling back to city centers, street centroids, or neighborhood areas when specific addresses are missing in the source data.

Always treat coordinates as **rough geographic estimates** rather than exact pinpoint locations.

---

## Project Structure

```
.
├── cbmal_fire_incidents_scraper.py   # Main web scraper & geocoding script
├── requirements.txt                  # Python dependencies
├── data/
│   ├── cbmal_fire_incidents.csv      # Main dataset containing scraped fire incidents
│   └── scraper_run_log.csv           # Execution log tracking scraper runs
└── scripts/
    └── backfill_geocoding.py         # Utility script to backfill missing coordinates
```

---

## Getting Started

### Prerequisites

Python 3.9+ is recommended. Install required packages using:

```bash
pip install -r requirements.txt
```

### Running the Scraper

To fetch the latest occurrences, deduplicate records, geocode addresses, and update the dataset:

```bash
python cbmal_fire_incidents_scraper.py
```

### Backfilling Missing Coordinates

If existing records in `data/cbmal_fire_incidents.csv` are missing coordinates, run the backfill script:

```bash
python scripts/backfill_geocoding.py
```

---

## Dataset Schema

The main dataset (`data/cbmal_fire_incidents.csv`) includes the following columns:

| Column | Description |
| --- | --- |
| `incident_id` | Unique ID for the incident |
| `scraped_at_utc` | ISO timestamp of when the record was scraped |
| `orgao` | Responsible agency / unit |
| `data` | Incident date |
| `hora` | Incident time |
| `cidade` | City / Municipality |
| `tipo` | Category / Type of fire incident |
| `detalhe` | Additional incident details or descriptions |
| `local` | Location text / address snippet reported |
| `viaturas` | Number of vehicles dispatched |
| `militares` | Number of personnel dispatched |
| `latitude` | Estimated latitude coordinate |
| `longitude` | Estimated longitude coordinate |

---

## Scraping Strategy & Resilience

To handle the characteristics of the CBMAL server, we adopt a **fail-fast** scraping strategy:

- **Diagnostic Findings**: Log audits revealed that the CBMAL portal runs on a legacy stack (`Apache/2.4.25` and `PHP/5.6.40`) which experiences significant transient latency (baseline page fetch time is 5.5s to 8.5s). 
- **Fail-Fast Approach**: Rather than consuming multiple retries that increase load on the target server during outages, the scraper is configured to try **only once** per execution but with an increased timeout of **60 seconds**. 
- **Scheduling Intention**: The scraper runs on a strict **6-hour schedule** (`18 */6 * * *`). This frequency is maintained to prevent data loss from rolling occurrence lists. We explicitly choose **not** to skip runs if a previous run was successful in the past 24 hours.
- **Handling Failures**: Transient connection failures are accepted as expected server-side events, and subsequent scheduled executions naturally backfill missing data.

---

## Attribution & Data License

Geocoding location data is powered by [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors using the Nominatim API, available under the Open Database License ([ODbL](https://opendatacommons.org/licenses/odbl/)).

