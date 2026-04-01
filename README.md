# mvp-visuals

An open-source project that scrapes the public
[Microsoft MVP directory](https://mvp.microsoft.com/en-US/search?target=Profile&program=MVP)
and publishes interactive visualisations via **GitHub Pages**.

## Live site

Once GitHub Pages is enabled for this repository (pointing at the `docs/` folder
or the dedicated *github-pages* environment), the dashboard will be available at:

```
https://<your-org>.github.io/mvp-visuals/
```

The dashboard shows:

- **MVPs by Country / Region** – horizontal bar chart (top 30)
- **MVPs by Technology Area** – horizontal bar chart (top 30)
- **MVPs by Length of Service** – doughnut chart (grouped in buckets)

## Repository layout

```
.
├── .github/
│   └── workflows/
│       └── scrape.yml          # Runs the scraper weekly and deploys Pages
├── docs/
│   ├── index.html              # GitHub Pages dashboard (Chart.js)
│   └── data/
│       └── mvps.json           # Scraped MVP data (committed by CI)
├── scraper/
│   ├── scrape_mvps.py          # Python scraper
│   └── requirements.txt
└── README.md
```

## Running the scraper locally

```bash
# Install dependencies
pip install -r scraper/requirements.txt

# Fetch all profiles (writes docs/data/mvps.json)
python scraper/scrape_mvps.py

# Fetch only the first 500 profiles (useful for testing)
python scraper/scrape_mvps.py --top 500

# Custom output path
python scraper/scrape_mvps.py --out /tmp/mvps.json
```

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--out` | `docs/data/mvps.json` | Output JSON file path |
| `--top` | *(all)* | Maximum number of profiles to fetch |
| `--page-size` | `100` | Profiles per API request |
| `--delay` | `0.5` | Seconds to wait between requests |

## Data format (`docs/data/mvps.json`)

```jsonc
{
  "lastUpdated": "2025-01-01T00:00:00Z",
  "totalProfiles": 3500,
  "summary": {
    "byCountry":         { "United States": 800, … },
    "byTechArea":        { "Azure": 600, … },
    "byLengthOfService": { "1 year": 120, "2–3 years": 340, … }
  },
  "profiles": [
    {
      "id": "…",
      "displayName": "Jane Doe",
      "country": "United States",
      "stateOrProvince": "WA",
      "city": "Seattle",
      "techAreas": ["Azure", "Developer Technologies"],
      "firstAwardYear": 2018,
      "consecutiveYears": 7,
      "profileUrl": "https://mvp.microsoft.com/…"
    }
  ]
}
```

## Automated updates (GitHub Actions)

The workflow in `.github/workflows/scrape.yml`:

1. Runs **every Sunday at 02:00 UTC** (and can be triggered manually).
2. Installs Python dependencies.
3. Executes the scraper to refresh `docs/data/mvps.json`.
4. Commits the updated data file back to the repository.
5. Deploys the `docs/` folder to GitHub Pages.

To trigger a manual run go to **Actions → Scrape MVP data and update GitHub Pages → Run workflow**.

## Enabling GitHub Pages

1. Go to **Settings → Pages**.
2. Set *Source* to **GitHub Actions**.
3. The next workflow run will deploy the site automatically.

## Licence

MIT – see [LICENSE](LICENSE) (add a licence file of your choice).
