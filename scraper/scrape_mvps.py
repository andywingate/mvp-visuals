"""
Scrape Microsoft MVP profiles from the public MVP search API and write
the aggregated data to docs/data/mvps.json for use by the GitHub Pages
visualisation site.

Usage:
    python scrape_mvps.py [--out PATH] [--top N] [--delay SECONDS]

The script pages through the Maven/MVP search API until it has fetched
every profile or until the optional --top limit is reached.
"""

import argparse
import json
import os
import time
import sys

import requests

API_URL = (
    "https://mavenapi-prod.azurewebsites.net/api/v2/search/Profiles"
)
DEFAULT_PAGE_SIZE = 100
# Approximate current award year; update when a new MVP award year begins.
CURRENT_YEAR = 2025
DEFAULT_OUT = os.path.join(
    os.path.dirname(__file__), "..", "docs", "data", "mvps.json"
)

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (compatible; mvp-visuals-scraper/1.0; "
        "+https://github.com/andywingate/mvp-visuals)"
    ),
}


def fetch_page(skip: int, page_size: int, session: requests.Session) -> dict:
    """Fetch one page of MVP search results."""
    params = {
        "$skip": skip,
        "$top": page_size,
        "searchText": "",
        "program": "MVP",
        "targetType": "Profile",
    }
    response = session.get(API_URL, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_profile(raw: dict) -> dict:
    """Extract the fields we care about from a raw API profile object."""
    award_years = raw.get("awardRecognitionYear") or raw.get("firstAwardYear") or 0
    consecutive = raw.get("numberOfConsecutiveAwards") or 0

    # Technology areas may come back as a list or a comma-separated string
    tech_areas = raw.get("awardCategoryCollection") or []
    if isinstance(tech_areas, str):
        tech_areas = [t.strip() for t in tech_areas.split(",") if t.strip()]

    return {
        "id": raw.get("mvpId") or raw.get("userKey") or "",
        "displayName": raw.get("displayName") or "",
        "country": raw.get("country") or raw.get("countryRegionName") or "",
        "stateOrProvince": raw.get("stateOrProvince") or "",
        "city": raw.get("city") or "",
        "techAreas": tech_areas,
        "firstAwardYear": award_years,
        "consecutiveYears": consecutive,
        "profileUrl": raw.get("userUrl") or raw.get("mvpProfileUrl") or "",
    }


def scrape(
    top: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    delay: float = 0.5,
) -> list[dict]:
    """Page through the API and return a list of extracted profile dicts."""
    profiles: list[dict] = []
    skip = 0
    total = None

    with requests.Session() as session:
        while True:
            fetch_size = page_size
            if top is not None:
                remaining = top - len(profiles)
                if remaining <= 0:
                    break
                fetch_size = min(page_size, remaining)

            print(f"Fetching records {skip}–{skip + fetch_size - 1} …", flush=True)
            try:
                data = fetch_page(skip, fetch_size, session)
            except requests.HTTPError as exc:
                print(f"HTTP error: {exc}", file=sys.stderr)
                break
            except requests.RequestException as exc:
                print(f"Request error: {exc}", file=sys.stderr)
                break

            items = data.get("value") or data.get("profiles") or []
            if total is None:
                total = data.get("totalCount") or data.get("@odata.count") or 0
                print(f"Total profiles reported by API: {total}", flush=True)

            if not items:
                break

            for item in items:
                profiles.append(extract_profile(item))

            skip += len(items)

            if total and skip >= total:
                break
            if len(items) < fetch_size:
                # API returned fewer items than requested → last page
                break

            time.sleep(delay)

    return profiles


def build_summary(profiles: list[dict]) -> dict:
    """Build aggregated summary statistics from the profile list."""
    by_country: dict[str, int] = {}
    by_tech: dict[str, int] = {}
    by_years: dict[str, int] = {}

    current_year = CURRENT_YEAR

    for p in profiles:
        country = p["country"] or "Unknown"
        by_country[country] = by_country.get(country, 0) + 1

        for tech in p["techAreas"]:
            by_tech[tech] = by_tech.get(tech, 0) + 1

        first = p["firstAwardYear"]
        if first and isinstance(first, int) and first > 0:
            length = current_year - first + 1
        else:
            length = p["consecutiveYears"] or 0

        bucket = _years_bucket(length)
        by_years[bucket] = by_years.get(bucket, 0) + 1

    return {
        "byCountry": by_country,
        "byTechArea": by_tech,
        "byLengthOfService": by_years,
    }


def _years_bucket(years: int) -> str:
    if years <= 0:
        return "Unknown"
    if years == 1:
        return "1 year"
    if years <= 3:
        return "2–3 years"
    if years <= 5:
        return "4–5 years"
    if years <= 10:
        return "6–10 years"
    return "10+ years"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Microsoft MVP profiles")
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="Output JSON file path (default: docs/data/mvps.json)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Maximum number of profiles to fetch (default: all)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Number of profiles to request per API call (default: 100)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between API requests (default: 0.5)",
    )
    args = parser.parse_args()

    profiles = scrape(top=args.top, page_size=args.page_size, delay=args.delay)
    summary = build_summary(profiles)

    output = {
        "lastUpdated": "",  # filled by the caller / CI
        "totalProfiles": len(profiles),
        "summary": summary,
        "profiles": profiles,
    }

    # Stamp the update time using a simple ISO-8601 string
    import datetime
    output["lastUpdated"] = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    print(f"Wrote {len(profiles)} profiles → {out_path}", flush=True)
    print(f"Summary: {json.dumps(summary, indent=2)}", flush=True)


if __name__ == "__main__":
    main()
