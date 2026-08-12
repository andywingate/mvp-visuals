"""
Scrape Microsoft MVP profiles from the public MVP search API and write
the aggregated data to docs/data/mvps.json for use by the GitHub Pages
visualisation site.

Usage:
    python scrape_mvps.py [--out PATH] [--top N] [--delay SECONDS]

The script uses a two-phase approach:
  Phase 1 – Page through the search endpoint to collect all MVP profile IDs.
  Phase 2 – Fetch enriched detail (years in programme, award category,
            technology focus areas) for each profile.
"""

import argparse
import json
import math
import os
import time
import sys

import requests

SEARCH_URL = (
    "https://mavenapi-prod.azurewebsites.net/api/CommunityLeaders/search/"
)
PROFILE_URL = (
    "https://mavenapi-prod.azurewebsites.net/api/mvp/UserProfiles/public/{uuid}"
)
MVP_PROFILE_PAGE = (
    "https://mvp.microsoft.com/en-US/MVP/profile/{uuid}"
)
DEFAULT_PAGE_SIZE = 100
DEFAULT_OUT = os.path.join(
    os.path.dirname(__file__), "..", "docs", "data", "mvps.json"
)

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (compatible; mvp-visuals-scraper/1.0; "
        "+https://github.com/andywingate/mvp-visuals)"
    ),
}


def fetch_search_page(
    page_index: int, page_size: int, session: requests.Session
) -> dict:
    """POST to the search endpoint and return the JSON response."""
    payload = {
        "searchKey": "",
        "academicInstitution": "",
        "program": ["MVP"],
        "countryRegionList": [],
        "academicCountryRegionList": [],
        "industryFocusList": [],
        "languagesList": [],
        "milestonesList": [],
        "pageIndex": page_index,
        "pageSize": page_size,
        "stateProvinceList": [],
        "technicalExpertiseList": [],
        "technologyFocusAreaGroupList": [],
        "technologyFocusAreaList": [],
    }
    response = session.post(
        SEARCH_URL, json=payload, headers=HEADERS, timeout=30
    )
    response.raise_for_status()
    return response.json()


def fetch_profile_detail(
    uuid: str, session: requests.Session
) -> dict:
    """GET enriched profile detail for a single MVP."""
    url = PROFILE_URL.format(uuid=uuid)
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_search_profile(raw: dict) -> dict:
    """Extract the fields we care about from a search-result profile."""
    uuid = raw.get("userProfileIdentifier") or ""
    first = (raw.get("firstName") or "").strip()
    last = (raw.get("lastName") or "").strip()
    display = f"{first} {last}".strip() if (first or last) else ""

    return {
        "id": uuid,
        "displayName": display,
        "country": raw.get("addressCountryOrRegionName") or "",
        "profileUrl": MVP_PROFILE_PAGE.format(uuid=uuid) if uuid else "",
        # Enriched in Phase 2:
        "yearsInProgram": 0,
        "awardCategory": "",
        "techAreas": [],
    }


def enrich_profile(profile: dict, detail: dict) -> dict:
    """Merge detail-endpoint data into a search profile."""
    user = detail.get("userProfile") or {}
    profile["yearsInProgram"] = user.get("yearsInProgram") or 0
    profile["awardCategory"] = user.get("awardCategory") or ""
    tech = user.get("technologyFocusArea") or []
    if isinstance(tech, str):
        tech = [t.strip() for t in tech.split(",") if t.strip()]
    profile["techAreas"] = tech
    return profile


def scrape(
    top: int | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    delay: float = 0.2,
) -> list[dict]:
    """Two-phase scrape: search for all profiles then enrich each one."""
    profiles: list[dict] = []

    with requests.Session() as session:
        # ── Phase 1: collect profiles via search endpoint ──
        page_index = 1
        total = None

        while True:
            current_page_size = page_size
            if top is not None:
                remaining = top - len(profiles)
                if remaining <= 0:
                    break
                current_page_size = min(page_size, remaining)

            print(
                f"[Phase 1] Fetching search page {page_index} "
                f"(pageSize={current_page_size}) …",
                flush=True,
            )
            try:
                data = fetch_search_page(page_index, current_page_size, session)
            except requests.HTTPError as exc:
                print(f"HTTP error: {exc}", file=sys.stderr)
                break
            except requests.RequestException as exc:
                print(f"Request error: {exc}", file=sys.stderr)
                break

            if total is None:
                total = data.get("filteredCount") or 0
                total_pages = math.ceil(total / page_size) if total else 0
                print(
                    f"Total MVPs reported by API: {total} "
                    f"({total_pages} pages)",
                    flush=True,
                )

            items = data.get("communityLeaderProfiles") or []
            if not items:
                break

            for item in items:
                profiles.append(extract_search_profile(item))

            if top is not None and len(profiles) >= top:
                profiles = profiles[:top]
                break
            if page_index >= math.ceil(total / page_size) if total else False:
                break

            page_index += 1
            time.sleep(delay)

        print(
            f"[Phase 1] Collected {len(profiles)} profiles.", flush=True
        )

        # ── Phase 2: enrich each profile with detail endpoint ──
        enriched = 0
        for i, profile in enumerate(profiles):
            uuid = profile["id"]
            if not uuid:
                continue
            print(
                f"[Phase 2] Enriching profile {i + 1}/{len(profiles)}: "
                f"{profile['displayName']} …",
                flush=True,
            )
            try:
                detail = fetch_profile_detail(uuid, session)
                enrich_profile(profile, detail)
                enriched += 1
            except requests.HTTPError as exc:
                print(
                    f"  ⚠ HTTP error for {uuid}: {exc}", file=sys.stderr
                )
            except requests.RequestException as exc:
                print(
                    f"  ⚠ Request error for {uuid}: {exc}", file=sys.stderr
                )
            time.sleep(delay)

        print(
            f"[Phase 2] Enriched {enriched}/{len(profiles)} profiles.",
            flush=True,
        )

    return profiles


def build_summary(profiles: list[dict]) -> dict:
    """Build aggregated summary statistics from the profile list."""
    by_country: dict[str, int] = {}
    by_tech: dict[str, int] = {}
    by_years: dict[str, int] = {}

    for p in profiles:
        country = p.get("country") or "Unknown"
        by_country[country] = by_country.get(country, 0) + 1

        for tech in p.get("techAreas") or []:
            by_tech[tech] = by_tech.get(tech, 0) + 1

        years = p.get("yearsInProgram") or 0
        bucket = _years_bucket(years)
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
        help="Number of profiles to request per search page (default: 100)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Seconds to wait between API requests (default: 0.2)",
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
