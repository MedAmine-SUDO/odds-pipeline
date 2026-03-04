"""
query.py — Quick inspection of the collected odds database.
Run: python src/query.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "odds.db"


def banner(title: str):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")


def run():
    if not DB_PATH.exists():
        print("No database found. Run pipeline.py first.")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Total rows
    banner("Total rows collected")
    cur.execute("SELECT COUNT(*) as total FROM odds")
    print(f"  {cur.fetchone()['total']:,} rows")

    # Snapshots collected
    banner("Snapshots collected (by pulled_at)")
    cur.execute("SELECT pulled_at, COUNT(*) as rows FROM odds GROUP BY pulled_at ORDER BY pulled_at DESC LIMIT 10")
    for r in cur.fetchall():
        print(f"  {r['pulled_at']}  →  {r['rows']:>4} rows")

    # Latest prices per game
    banner("Latest odds — all active games")
    cur.execute("""
        SELECT home_team, away_team, commence_time, bookmaker, team, price, pulled_at
        FROM odds
        WHERE pulled_at = (SELECT MAX(pulled_at) FROM odds)
        ORDER BY commence_time, bookmaker, team
    """)
    rows = cur.fetchall()
    if not rows:
        print("  No data yet.")
    else:
        for r in rows:
            print(f"  {r['home_team']} vs {r['away_team']}  |  {r['bookmaker']:<20}  {r['team']:<25}  ${r['price']}")

    # Price movement for one team across snapshots
    banner("Price movement example (first team found)")
    cur.execute("SELECT DISTINCT team FROM odds LIMIT 1")
    row = cur.fetchone()
    if row:
        team = row["team"]
        cur.execute("""
            SELECT pulled_at, price FROM odds
            WHERE team = ?
            ORDER BY pulled_at
        """, (team,))
        print(f"  Team: {team}")
        for r in cur.fetchall():
            print(f"  {r['pulled_at']}  →  ${r['price']}")

    con.close()


if __name__ == "__main__":
    run()