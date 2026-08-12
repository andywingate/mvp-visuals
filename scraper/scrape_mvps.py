"""
Scrape Microsoft MVP profiles from the public MVP search API and write
the aggregated data to docs/data/mvps.json for use by the GitHub Pages
visualisation site.

Usage:
    python scrape_mvps.py [--out PATH] [--top N] [--delay SECONDS] [--no-enrich]

The script pages through the MVP CommunityLeaders search API until it has
fetched every profile or until the optional --top limit is reached.  Each
profile stub is then optionally enriched with a second API call to retrieve
tech areas and years-in-program data (pass --no-enrich to skip enrichment).
"""

import argparse
import json
import os
import time
import sys
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SEARCH_URL = "https://mavenapi-prod.azurewebsites.net/api/CommunityLeaders/search/"
PROFILE_URL = "https://mavenapi-prod.azurewebsites.net/api/mvp/UserProfiles/public/{}"
DEFAULT_PAGE_SIZE = 100
MAX_ENRICH_WORKERS = 5
# Approximate current award year; update when a new MVP award year begins.
CURRENT_YEAR = 2025
DEFAULT_OUT = os.path.join(
    os.path.dirname(__file__), "..", "docs", "data", "mvps.json"
)

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://mvp.microsoft.com",
    "Referer": "https://mvp.microsoft.com/",
    "User-Agent": (
        "Mozilla/5.0 (compatible; mvp-visuals-scraper/1.0; "
        "+https://github.com/andywingate/mvp-visuals)"
    ),
}


def fetch_page(page_index: int, page_size: int, session: requests.Session) -> dict:
    """Fetch one page of MVP search results (page_index is 1-based)."""
    payload = {
        "searchKey": "",
        "program": ["MVP"],
        "pageIndex": page_index,
        "pageSize": page_size,
        "countryRegionList": [],
        "stateProvinceList": [],
        "languagesList": [],
        "technologyFocusAreaList": [],
    }
    response = session.post(SEARCH_URL, json=payload, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_profile_detail(profile_id: str, session: requests.Session) -> dict:
    """Fetch detailed profile data for a single MVP by ID."""
    url = PROFILE_URL.format(profile_id)
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json().get("userProfile") or {}
    except requests.RequestException:
        return {}


def extract_profile(raw: dict, detail: dict | None = None) -> dict:
    """Extract the fields we care about from a raw API profile stub and optional detail."""
    profile_id = raw.get("userProfileIdentifier") or ""

    # Build display name (prefer localized variant when the server flag is set)
    if raw.get("screenNameLocalized"):
        first = raw.get("localizedFirstName") or raw.get("firstName") or ""
        last = raw.get("localizedLastName") or raw.get("lastName") or ""
    else:
        first = raw.get("firstName") or ""
        last = raw.get("lastName") or ""
    display_name = f"{first} {last}".strip()
    # Some localized names are stored as "-" prefixed in the API; strip leading hyphens.
    display_name = display_name.lstrip("-").strip()

    detail = detail or {}

    # Technology areas come from the detail endpoint (awardCategory is the primary field)
    tech_areas = detail.get("awardCategory") or detail.get("technologyFocusArea") or []
    if isinstance(tech_areas, str):
        tech_areas = [t.strip() for t in tech_areas.split(",") if t.strip()]

    years_in_program = detail.get("yearsInProgram") or 0
    if isinstance(years_in_program, int) and years_in_program > 0:
        first_award_year = CURRENT_YEAR - years_in_program + 1
    else:
        first_award_year = 0

    profile_url = (
        f"https://mvp.microsoft.com/en-US/mvp/profile/{profile_id}"
        if profile_id
        else ""
    )

    return {
        "id": profile_id,
        "displayName": display_name,
        "country": raw.get("addressCountryOrRegionName") or "",
        "stateOrProvince": "",
        "city": "",
        "techAreas": tech_areas,
        "firstAwardYear": first_award_year,
        "consecutiveYears": years_in_program,
        "profileUrl": profile_url,
    }


def scrape(
    top: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    delay: float = 0.5,
    enrich: bool = True,
) -> list[dict]:
    """Page through the search API and return a list of extracted profile dicts."""
    stubs: list[dict] = []
    page_index = 1
    total = None

    with requests.Session() as session:
        while True:
            fetch_size = page_size
            if top is not None:
                remaining = top - len(stubs)
                if remaining <= 0:
                    break
                fetch_size = min(page_size, remaining)

            print(
                f"Fetching page {page_index} ({fetch_size} profiles per page) …",
                flush=True,
            )
            try:
                data = fetch_page(page_index, fetch_size, session)
            except requests.HTTPError as exc:
                print(f"HTTP error: {exc}", file=sys.stderr)
                break
            except requests.RequestException as exc:
                print(f"Request error: {exc}", file=sys.stderr)
                break

            items = data.get("communityLeaderProfiles") or []
            if total is None:
                total = data.get("filteredCount") or 0
                print(f"Total profiles reported by API: {total}", flush=True)

            if not items:
                break

            stubs.extend(items)

            if total and len(stubs) >= total:
                break
            if len(items) < fetch_size:
                # API returned fewer items than requested → last page
                break

            page_index += 1
            time.sleep(delay)

    print(f"Collected {len(stubs)} profile stubs.", flush=True)

    if not enrich:
        return [extract_profile(stub) for stub in stubs]

    # Enrich each stub with individual profile details (tech areas, years, etc.)
    print(
        f"Enriching {len(stubs)} profiles with detail data "
        f"(concurrency={MAX_ENRICH_WORKERS}) …",
        flush=True,
    )

    profiles: dict[int, dict] = {}

    def _enrich(index_stub: tuple[int, dict]) -> tuple[int, dict]:
        idx, stub = index_stub
        pid = stub.get("userProfileIdentifier") or ""
        with requests.Session() as s:
            detail = fetch_profile_detail(pid, s) if pid else {}
        return idx, extract_profile(stub, detail)

    with ThreadPoolExecutor(max_workers=MAX_ENRICH_WORKERS) as executor:
        futures = {
            executor.submit(_enrich, (i, stub)): i
            for i, stub in enumerate(stubs)
        }
        done = 0
        for future in as_completed(futures):
            idx, profile = future.result()
            profiles[idx] = profile
            done += 1
            if done % 100 == 0 or done == len(stubs):
                print(f"  Enriched {done}/{len(stubs)} profiles …", flush=True)

    return [profiles[i] for i in range(len(stubs))]


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
        help="Seconds to wait between search-page API requests (default: 0.5)",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        default=False,
        help=(
            "Skip per-profile detail calls (faster but omits tech areas "
            "and years-in-program data)"
        ),
    )
    args = parser.parse_args()

    profiles = scrape(
        top=args.top,
        page_size=args.page_size,
        delay=args.delay,
        enrich=not args.no_enrich,
    )
    summary = build_summary(profiles)

    output = {
        "lastUpdated": "",  # filled by the caller / CI
        "totalProfiles": len(profiles),
        "summary": summary,
        "profiles": profiles,
    }

    # Stamp the update time using a simple ISO-8601 string
    output["lastUpdated"] = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    print(f"Wrote {len(profiles)} profiles → {out_path}", flush=True)
    print(f"Summary: {json.dumps(summary, indent=2)}", flush=True)


if __name__ == "__main__":
    main()
