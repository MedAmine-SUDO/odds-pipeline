"""
Sports Odds ETL Pipeline
Pulls live odds from The Odds API, transforms, and stores to CSV + SQLite.
"""

import os
import csv
import sqlite3
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY = os.getenv("ODDS_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = "https://api.the-odds-api.com/v4"
SPORT    = "basketball_nba"
REGIONS  = "us"
MARKETS  = "h2h"

ROOT     = Path(__file__).resolve().parent.parent
CSV_DIR  = ROOT / "data" / "csv"
DB_PATH  = ROOT / "data" / "db" / "odds.db"
LOG_DIR  = ROOT / "logs"

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "pipeline.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── Extract ───────────────────────────────────────────────────────────────────
def fetch_odds() -> list[dict]:
    """Pull raw odds from The Odds API."""
    url = f"{BASE_URL}/sports/{SPORT}/odds"
    params = {
        "apiKey":  API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
    }
    log.info(f"Fetching odds for sport={SPORT} ...")
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    remaining = response.headers.get("x-requests-remaining", "?")
    log.info(f"API quota remaining: {remaining}")
    return response.json()


# ── Transform ─────────────────────────────────────────────────────────────────
def transform(raw: list[dict]) -> list[dict]:
    """Flatten nested odds JSON into clean rows."""
    rows = []
    pulled_at = datetime.now(timezone.utc).isoformat()

    for game in raw:
        game_id      = game.get("id")
        home_team    = game.get("home_team")
        away_team    = game.get("away_team")
        commence_time = game.get("commence_time")

        for bookmaker in game.get("bookmakers", []):
            bookmaker_key  = bookmaker.get("key")
            bookmaker_title = bookmaker.get("title")
            last_update    = bookmaker.get("last_update")

            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    rows.append({
                        "pulled_at":       pulled_at,
                        "game_id":         game_id,
                        "commence_time":   commence_time,
                        "home_team":       home_team,
                        "away_team":       away_team,
                        "bookmaker":       bookmaker_title,
                        "bookmaker_key":   bookmaker_key,
                        "team":            outcome.get("name"),
                        "price":           outcome.get("price"),
                        "last_update":     last_update,
                    })

    log.info(f"Transformed {len(rows)} rows from {len(raw)} games.")
    return rows


# ── Load: CSV ─────────────────────────────────────────────────────────────────
def load_csv(rows: list[dict]) -> Path:
    """Append rows to a daily CSV file."""
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path  = CSV_DIR / f"odds_{date_str}.csv"
    write_header = not csv_path.exists()

    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    log.info(f"CSV written → {csv_path}  ({len(rows)} rows appended)")
    return csv_path


# ── Load: SQLite ──────────────────────────────────────────────────────────────
def load_sqlite(rows: list[dict]) -> None:
    """Upsert rows into SQLite — deduplicates on (game_id, bookmaker_key, team, pulled_at)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS odds (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            pulled_at      TEXT NOT NULL,
            game_id        TEXT NOT NULL,
            commence_time  TEXT,
            home_team      TEXT,
            away_team      TEXT,
            bookmaker      TEXT,
            bookmaker_key  TEXT,
            team           TEXT,
            price          REAL,
            last_update    TEXT,
            UNIQUE(game_id, bookmaker_key, team, pulled_at)
        )
    """)

    inserted = 0
    for row in rows:
        try:
            cur.execute("""
                INSERT INTO odds
                    (pulled_at, game_id, commence_time, home_team, away_team,
                     bookmaker, bookmaker_key, team, price, last_update)
                VALUES
                    (:pulled_at, :game_id, :commence_time, :home_team, :away_team,
                     :bookmaker, :bookmaker_key, :team, :price, :last_update)
            """, row)
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # duplicate — skip silently

    con.commit()
    con.close()
    log.info(f"SQLite → {DB_PATH}  ({inserted} new rows inserted)")


# ── Orchestrate ───────────────────────────────────────────────────────────────
def run():
    log.info("=" * 60)
    log.info("Pipeline started")
    try:
        raw  = fetch_odds()
        if not raw:
            log.warning("No games returned from API.")
            return
        rows = transform(raw)
        load_csv(rows)
        load_sqlite(rows)
        log.info("Pipeline finished successfully ✓")
    except requests.HTTPError as e:
        log.error(f"HTTP error: {e}")
    except Exception as e:
        log.exception(f"Unexpected error: {e}")
    log.info("=" * 60)


if __name__ == "__main__":
    run()