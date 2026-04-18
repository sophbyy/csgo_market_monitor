# CS:GO Market Monitor

Detect Steam bot accounts used by CS:GO/CS2 trading platforms (market.csgo.com, lis-skins.com, avan.market). These are auto-registered accounts that hold marketplace inventory and share common traits: low Steam level, high-value CS2 inventories, minimal gaming activity, and Russian firstname+lastname naming patterns.

## How It Works

```
Discovery ──► Batch pre-filter ──► Enrichment ──► Evaluate ──► CSV
(groups,       (100 IDs/call,      (level,        (bot         (output/
 search,        reject private      games,         criteria)     bot_profiles.csv)
 friends,       & recent)           inventory)
 urls)
```

1. **Discover** profile URLs via Steam groups, community search, friend crawling, or direct input
2. **Pre-filter** in batches of 100 via `GetPlayerSummaries` + `GetPlayerBans` (reject private/recently active)
3. **Enrich** passing profiles: Steam level, owned games/playtime, inventory value (SIH or API)
4. **Detect** Russian name patterns against vanity URL / nickname
5. **Evaluate** against bot criteria (level 0-10, inactive 30+ days, playtime <= 10h, inventory >= $500)
6. **Export** matching profiles to CSV with 13 data columns

## Prerequisites

- **Python 3.10+**
- **Steam Web API key** from https://steamcommunity.com/dev
- **Chromium** installed automatically by Playwright
- **(Recommended) Steam Inventory Helper** Chrome extension for inventory valuation

## Setup

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd csgo_market_monitor

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Chromium for Playwright
playwright install chromium

# 5. Configure environment
cp .env.example .env
# Edit .env and set your STEAM_API_KEY (required)
# Optionally set SIH_EXTENSION_PATH for inventory valuation
```

## Configuration

Edit `.env` with your settings:

```bash
# Required
STEAM_API_KEY=your_steam_api_key_here

# Recommended - path to unpacked SIH Chrome extension folder
# Needed for reliable inventory valuation (Steam API has strict rate limits)
# SIH_EXTENSION_PATH=/path/to/steam-inventory-helper
```

| Setting | Default | Description |
|---|---|---|
| `steam_api_key` | *(required)* | Steam Web API key |
| `sih_extension_path` | `""` | Path to unpacked SIH extension directory (empty = API-only fallback) |
| `profile_dir` | `browser_profile` | Persistent Playwright browser profile directory |
| `output_csv` | `output/bot_profiles.csv` | Output CSV file path |
| `min_delay_seconds` | `5.0` | Minimum delay between profiles (seconds) |
| `max_delay_seconds` | `9.0` | Maximum delay between profiles (seconds) |

## Usage

### 1. Crawl Steam groups (primary method)

Crawl member lists of Steam groups associated with trading platforms. Uses the XML API (~1,000 members per page). Supports resume — if interrupted, re-run the same command to continue from the last completed page.

```bash
# Crawl a single group (all pages)
python main.py --group market_csgo_com

# Crawl with a page limit
python main.py --group market_csgo_com --group-max-pages 5

# Crawl multiple groups
python main.py --group market_csgo_com tradeit_gg csmoney_com

# Use full group URL
python main.py --group https://steamcommunity.com/groups/market_csgo_com
```

### 2. Search Steam Community

Search `steamcommunity.com/search/users/` using Russian name pattern combinations. Opens a browser window (requires Chromium).

```bash
# Run with default 20 search queries
python main.py --search

# Run with more queries for broader coverage
python main.py --search --search-queries 50
```

### 3. Crawl friend networks

BFS-crawl friend lists starting from known bot SteamID64s. Bot accounts on the same platform often share friend connections.

```bash
# Crawl from a single seed account (default depth: 2)
python main.py --crawl-friends 76561199425533187

# Multiple seeds with custom depth
python main.py --crawl-friends 76561199425533187 76561199432874507 --crawl-depth 3

# Shallow crawl (direct friends only)
python main.py --crawl-friends 76561199425533187 --crawl-depth 0
```

### 4. Process specific profile URLs

Directly evaluate known Steam profile URLs without any discovery step.

```bash
# Single profile
python main.py --urls https://steamcommunity.com/id/hakimchistyakov

# Multiple profiles (vanity URLs and SteamID64 URLs both work)
python main.py --urls \
  https://steamcommunity.com/id/hakimchistyakov \
  https://steamcommunity.com/profiles/76561198012345678
```

### 5. Discovery mode (interactive browser)

Opens a trading platform in a browser for manual exploration. Continuously scans the page for Steam profile URLs. Press Ctrl+C when done to process any found URLs.

```bash
python main.py --discover --platform market.csgo.com
python main.py --discover --platform lis-skins.com
python main.py --discover --platform avan.market
```

### 6. Platform scraper (automated, not recommended)

Automatically scrapes a trading platform for profile URLs. Not recommended — trading platforms are JavaScript SPAs that don't expose bot Steam profile URLs in their DOM or network responses.

```bash
python main.py --platform market.csgo.com --max-pages 5
```

### Run tests

```bash
python -m pytest tests/ -v
```

## Bot Detection Criteria

| Criterion | Threshold | Type |
|---|---|---|
| Steam level | 0-10 | Hard reject if > 10 |
| CS2 inventory value | >= $500 | Hard reject if < $500; required (unknown = rejected) |
| Last activity | >= 30 days ago | Hard reject if active within 30 days |
| Total playtime | <= 10 hours | Hard reject if > 10 hours |
| VAC ban | Recorded in CSV | Informational (positive indicator for bots) |
| Name pattern | Russian firstname+lastname | Informational (recorded, not filtered) |

**Note on missing data:** Steam's API often doesn't return `lastlogoff` (accounts that never used the desktop client) or game details (private by default since 2018). These fields are treated as "unknown" and don't cause rejection. However, `inventory_value` is required — without it, the core $500+ criterion can't be verified.

## Output

### CSV file

Results are written to `output/bot_profiles.csv`:

| Column | Example |
|---|---|
| `steam_id` | `76561198012345678` |
| `profile_url` | `https://steamcommunity.com/id/hakimchistyakov` |
| `nickname` | `Hakimchistyakov` |
| `steam_level` | `1` |
| `vac_banned` | `False` |
| `last_logoff_utc` | `2023-11-14T22:13:20+00:00` |
| `days_since_active` | `145` |
| `total_playtime_hours` | `2.5` |
| `inventory_value_usd` | `847.32` |
| `source_platform` | `market_csgo_com` |
| `name_pattern_match` | `russian_name_digits` |
| `name_pattern_confidence` | `0.95` |
| `collected_at_utc` | `2026-02-21T12:00:00+00:00` |

### Logs

- **Console** — INFO level, real-time progress
- **`app.log`** — persistent log file

### Cache files

- `.cache/profiles.json` — vanity URL resolutions, already-checked profile IDs, group crawl progress
- `.cache/prices.json` — Steam Market item price lookups

Caches persist across runs to avoid redundant API calls and enable resume.

## Rate Limiting

All request rates are managed by a centralized `RateLimiter` with per-domain jitter:

| Domain | Delay | Used for |
|---|---|---|
| `api` | 0.25-0.5s | Steam Web API calls |
| `community` | 2-4s | Steam Community pages (group crawl, search) |
| `market` | 1-2s | Steam Market price lookups |
| `inventory` | 2-3s | Steam inventory endpoint (retries on 403/429) |
| `profile` | 5-9s | Between full profile enrichment cycles |

All API calls use tenacity retry with exponential backoff (2-30s, 3 attempts). The inventory endpoint retries up to 3 times on 403/429 with 5s delays (Steam uses 403 for both "private" and "rate limited").

## SIH (Steam Inventory Helper)

SIH is a closed-source Chrome extension that injects inventory pricing into Steam profile pages. It is the recommended way to check inventory values because Steam's own inventory API is heavily rate-limited.

**Setup:**
1. Install SIH from the Chrome Web Store
2. Find the unpacked extension directory (Chrome → `chrome://extensions/` → Developer mode → note the extension path)
3. Set `SIH_EXTENSION_PATH` in `.env` to the extension directory path

**How it works:**
1. Playwright loads SIH into Chromium via `--load-extension`
2. For each profile, navigates to the inventory page
3. Waits for SIH to inject pricing data into the DOM
4. Reads the total value from SIH's injected elements
5. Falls back to Steam API if SIH fails

**Without SIH:** Inventory value is calculated via Steam's inventory JSON endpoint + Steam Market price lookups. This works for public inventories but is rate-limited (403 errors are common).

## Project Structure

```
main.py                        # Entry point, CLI args, profile enrichment pipeline
src/
├── config.py                  # Settings dataclass, .env loading
├── patterns.py                # Russian name pattern detection (90+ first, 80+ last names)
├── rate_limiter.py            # Centralized per-domain rate limiter with jitter
├── browser/
│   ├── sih_session.py         # Playwright persistent context with SIH extension
│   ├── sih_inventory_reader.py # SIH DOM reader: navigates inventory, reads injected value
│   └── platform_scraper.py    # BasePlatformScraper + trading platform scrapers
├── discovery/
│   ├── group_crawler.py       # Steam group XML API crawler (~1000 members/page)
│   ├── batch_prefilter.py     # Batch pre-filter via GetPlayerSummaries+Bans (100 IDs/call)
│   ├── friend_crawler.py      # BFS friend network crawler
│   └── community_search.py    # Steam Community profile search via Playwright
├── steam/
│   ├── client.py              # Steam Web API client (retry, backoff, rate limiting)
│   └── inventory_value.py     # Inventory fetch + price lookups via Steam Market API
├── pipeline/
│   ├── evaluator.py           # ProfileData, EvaluationResult, filtering logic
│   └── exporter.py            # CSV export (append-mode, 13 columns)
└── storage/
    ├── cache.py               # Thread-safe JSON file cache
    └── profile_cache.py       # Vanity URL cache + checked tracking + group progress
tests/                         # 157 unit tests (pytest)
```

## Known Limitations

- **Inventory access** — Steam's inventory endpoint is heavily rate-limited and returns 403 for both private inventories and rate limiting. SIH is recommended for reliable inventory checks.
- **Last logoff often unavailable** — Steam's API doesn't return `lastlogoff` for accounts that use invisible mode or never used the desktop client. No workaround exists (profile page "Last Online" is friends-only since 2019).
- **Game details private by default** — `GetOwnedGames` returns empty when game details are set to "Friends Only" (the default since 2018). Playtime is unknown for most profiles.
- **Platform scrapers don't find bot profiles** — Trading platforms are JavaScript SPAs that don't expose bot Steam profile URLs. Use `--group`, `--search`, or `--crawl-friends` instead.
