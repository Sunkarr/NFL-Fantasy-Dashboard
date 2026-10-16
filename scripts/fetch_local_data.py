#!/usr/bin/env bash
""":"
# Python wrapper to allow running directly as ./scripts/fetch_local_data.py
exec python3 "$0" "$@"
"""

import os
import sys
import sqlite3
import argparse
import subprocess
from pathlib import Path

# Add project root to sys.path so src imports work reliably from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import DB_PATH, DEFAULT_LEAGUE_ID
from src.sync import run_full_sync
from src.db import get_connection

AZURE_HOST = "azureuser@9.160.37.59"
REMOTE_DB_PATH = "/home/azureuser/NFL-Fantasy/data/fantasy.db"


def fetch_from_sleeper(league_id: str, mode: str, force_players: bool):
    """Fetch league data directly from Sleeper API and update local data/fantasy.db."""
    print("=" * 60)
    print(f"📥 Fetching Sleeper data directly from API into: {DB_PATH}")
    print(f"   League ID: {league_id} | Mode: {mode} | Force Players: {force_players}")
    print("=" * 60)
    run_full_sync(league_id=league_id, mode=mode, force_players=force_players, db_path=DB_PATH)
    print("\n✅ Local database successfully updated!")


def fetch_from_azure(azure_host: str = AZURE_HOST):
    """Download the production database directly from the Azure VM via scp."""
    print("=" * 60)
    print(f"📥 Pulling production database from Azure VM: {azure_host}")
    print(f"   Remote: {REMOTE_DB_PATH} -> Local: {DB_PATH}")
    print("=" * 60)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["scp", f"{azure_host}:{REMOTE_DB_PATH}", str(DB_PATH)]
    try:
        subprocess.run(cmd, check=True)
        print(f"\n✅ Successfully downloaded production database to {DB_PATH}")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error pulling from Azure: {e}", file=sys.stderr)
        sys.exit(1)


def show_database_info():
    """Print an overview of tables, row counts, and schema."""
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}. Run with --sync or --from-azure first.")
        return

    conn = get_connection(DB_PATH)
    cur = conn.cursor()

    print("\n" + "=" * 60)
    print(f"📊 NFL Fantasy SQLite Database: {DB_PATH}")
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"   File size: {size_mb:.2f} MB")
    print("=" * 60)

    # Sync metadata
    cur.execute("SELECT key, value FROM sync_metadata")
    meta = dict(cur.fetchall())
    if meta:
        print("\n🕒 Sync Metadata:")
        for k, v in meta.items():
            if k == "league_scoring_settings":
                continue
            print(f"   • {k}: {v}")

    # Tables & Row Counts
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cur.fetchall()]

    print("\n📋 Tables & Row Counts:")
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = cur.fetchone()[0]
        cur.execute(f"PRAGMA table_info({t})")
        cols = [c[1] for c in cur.fetchall()]
        print(f"   • {t:<24} {cnt:>7,} rows  (Cols: {', '.join(cols[:5])}{'...' if len(cols) > 5 else ''})")

    conn.close()


def run_sql_query(query: str):
    """Execute a single SQL query and print nicely formatted results."""
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}. Run with --sync first.")
        return

    try:
        import pandas as pd
        conn = get_connection(DB_PATH)
        df = pd.read_sql_query(query, conn)
        conn.close()

        print("\n" + "-" * 70)
        print(f"🔍 Query: {query.strip()}")
        print("-" * 70)
        if df.empty:
            print("(0 rows returned)")
        else:
            try:
                from tabulate import tabulate
                print(tabulate(df, headers="keys", tablefmt="psql", showindex=False))
            except ImportError:
                print(df.to_string(index=False))
            print(f"\n({len(df)} rows)")
    except Exception as e:
        print(f"\n❌ SQL Error: {e}", file=sys.stderr)


EXAMPLE_QUERIES = [
    (
        "Kickers comparison (Scores across Weeks 1-4)",
        """
        SELECT 
            m.week,
            p.full_name AS kicker,
            p.nfl_team,
            t.team_name AS fantasy_team,
            m.points
        FROM weekly_matchup_points m
        JOIN players p ON m.player_id = p.player_id
        JOIN teams t ON m.roster_id = t.roster_id
        WHERE p.position = 'K' AND m.week <= 3
        ORDER BY p.full_name, m.week;
        """
    ),
    (
        "Top 15 Highest Scoring Players (League Matchup Points)",
        """
        SELECT 
            p.full_name,
            p.position,
            p.nfl_team,
            COUNT(m.week) AS games,
            ROUND(AVG(m.points), 2) AS avg_fpts,
            ROUND(MAX(m.points), 2) AS max_fpts,
            ROUND(SUM(m.points), 2) AS total_fpts,
            COALESCE(t.team_name, 'Free Agent') AS fantasy_team
        FROM weekly_matchup_points m
        JOIN players p ON m.player_id = p.player_id
        LEFT JOIN teams t ON m.roster_id = t.roster_id
        WHERE m.week <= 3
        GROUP BY p.player_id
        ORDER BY total_fpts DESC
        LIMIT 15;
        """
    ),
    (
        "Current League Standings & Total Points",
        """
        SELECT 
            roster_id,
            team_name,
            owner_name,
            wins,
            losses,
            ROUND(fpts, 2) AS points_for,
            ROUND(fpts_against, 2) AS points_against
        FROM teams
        ORDER BY wins DESC, fpts DESC;
        """
    ),
    (
        "Roster Overview for all teams (Starters vs Bench)",
        """
        SELECT 
            t.team_name,
            p.position,
            p.full_name,
            p.injury_status,
            CASE WHEN r.is_starter = 1 THEN 'STARTER' ELSE 'BENCH' END AS lineup_slot
        FROM current_rosters r
        JOIN teams t ON r.roster_id = t.roster_id
        JOIN players p ON r.player_id = p.player_id
        ORDER BY t.team_name, r.is_starter DESC, p.position;
        """
    ),
    (
        "Injured Starters on Active Fantasy Rosters",
        """
        SELECT 
            t.team_name,
            p.full_name,
            p.position,
            p.nfl_team,
            p.injury_status
        FROM current_rosters r
        JOIN teams t ON r.roster_id = t.roster_id
        JOIN players p ON r.player_id = p.player_id
        WHERE r.is_starter = 1 
          AND p.injury_status IS NOT NULL 
          AND p.injury_status NOT IN ('Healthy', '')
        ORDER BY t.team_name, p.position;
        """
    ),
    (
        "Latest Completed Roster Moves (Waivers, Trades, Pickups)",
        """
        SELECT 
            CASE WHEN is_preseason = 1 THEN 'Pre-Season' ELSE 'Week ' || round END AS timing,
            type,
            waiver_bid AS bid,
            adds,
            drops,
            created_iso
        FROM roster_moves
        ORDER BY created_at DESC
        LIMIT 10;
        """
    ),
]


def show_examples():
    """List pre-built example queries."""
    print("\n" + "=" * 60)
    print("📚 Pre-built Example SQL Queries:")
    print("=" * 60)
    for idx, (title, query) in enumerate(EXAMPLE_QUERIES, 1):
        print(f"\n[{idx}] {title}")
        print(query.strip())


def interactive_sql_shell():
    """Interactive SQL query prompt with auto-formatting and helpers."""
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}. Syncing first...")
        fetch_from_sleeper(DEFAULT_LEAGUE_ID, mode="incremental", force_players=False)

    print("\n" + "=" * 60)
    print("💻 Interactive SQL Shell (data/fantasy.db)")
    print("   Type your SQL queries below (end with ';' or press Enter).")
    print("   Commands: '.tables', '.schema [table]', '.example [1-6]', 'exit'")
    print("=" * 60 + "\n")

    conn = get_connection(DB_PATH)

    while True:
        try:
            line = input("sql> ").strip()
            if not line:
                continue

            if line.lower() in ("exit", "quit", "\\q"):
                print("Bye!")
                break

            if line.lower() == ".tables":
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                for t in cur.fetchall():
                    print(f"  • {t[0]}")
                continue

            if line.lower().startswith(".schema"):
                parts = line.split()
                cur = conn.cursor()
                if len(parts) > 1:
                    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (parts[1],))
                else:
                    cur.execute("SELECT sql FROM sqlite_master WHERE type='table'")
                for s in cur.fetchall():
                    if s[0]:
                        print(f"\n{s[0]};")
                continue

            if line.lower() == ".examples":
                show_examples()
                continue

            if line.lower().startswith(".example"):
                parts = line.split()
                if len(parts) > 1 and parts[1].isdigit():
                    idx = int(parts[1]) - 1
                    if 0 <= idx < len(EXAMPLE_QUERIES):
                        run_sql_query(EXAMPLE_QUERIES[idx][1])
                        continue
                print(f"Usage: .example 1  (choose 1 to {len(EXAMPLE_QUERIES)})")
                continue

            # Execute custom query
            run_sql_query(line)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Sleeper Fantasy data locally and explore in SQL."
    )
    parser.add_argument(
        "--sync", action="store_true", help="Download/sync latest data from Sleeper API into data/fantasy.db"
    )
    parser.add_argument(
        "--from-azure", action="store_true", help="Download data/fantasy.db directly from Azure VM via scp"
    )
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="incremental", help="Sync mode (default: incremental)"
    )
    parser.add_argument(
        "--force-players", action="store_true", help="Force refresh full NFL players database (~5MB)"
    )
    parser.add_argument(
        "--league-id", default=DEFAULT_LEAGUE_ID, help=f"Sleeper League ID (default: {DEFAULT_LEAGUE_ID})"
    )
    parser.add_argument(
        "--info", action="store_true", help="Display local database table statistics and schema"
    )
    parser.add_argument(
        "-q", "--query", type=str, help="Execute a custom SQL query and print formatted results"
    )
    parser.add_argument(
        "--example", type=int, choices=range(1, len(EXAMPLE_QUERIES) + 1), help=f"Run one of the pre-built example queries (1-{len(EXAMPLE_QUERIES)})"
    )
    parser.add_argument(
        "--sync-2024", action="store_true", help="Download and calculate full historical 2024 season stats"
    )
    parser.add_argument(
        "--sync-2025", action="store_true", help="Download and calculate full historical 2025 season stats"
    )
    parser.add_argument(
        "--sync-season", type=str, help="Download and calculate historical season stats for any specific year (e.g. 2024, 2023)"
    )
    parser.add_argument(
        "-t", "--truncate", action="store_true", help="Truncate/delete existing records for the target season (or current season on --sync) before loading fresh data"
    )
    parser.add_argument(
        "--examples", action="store_true", help="List all pre-built example SQL queries"
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true", help="Open interactive SQL shell"
    )

    args = parser.parse_args()

    # If no flags provided, show info or sync if DB missing
    if len(sys.argv) == 1:
        if not DB_PATH.exists():
            fetch_from_sleeper(args.league_id, args.mode, args.force_players)
        show_database_info()
        print("\n💡 Tip: Run with '-i' for an interactive SQL prompt, or '--examples' for sample queries.")
        return

    if args.from_azure:
        fetch_from_azure()

    if args.sync:
        if args.truncate:
            from src.db import get_connection
            with get_connection(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("DELETE FROM weekly_nfl_stats WHERE season = '2026'")
                c.execute("DELETE FROM matchups WHERE season = '2026'")
                conn.commit()
            print("🗑️  Truncated 2026 weekly_nfl_stats and matchups before sync.")
        fetch_from_sleeper(args.league_id, args.mode, args.force_players)

    if args.sync_2024:
        from src.sync import sync_historical_season_stats
        print("=" * 60)
        print(f"📥 Fetching 2024 historical season stats with league scoring rules into: {DB_PATH}")
        if args.truncate:
            print("🗑️  Truncate flag active: Existing 2024 records will be wiped before loading.")
        print("=" * 60)
        sync_historical_season_stats(season="2024", db_path=DB_PATH, truncate=args.truncate)
        print("[SUCCESS] Historical 2024 stats successfully updated!")

    if args.sync_2025:
        from src.sync import sync_historical_season_stats
        print("=" * 60)
        print(f"📥 Fetching 2025 historical season stats with league scoring rules into: {DB_PATH}")
        if args.truncate:
            print("🗑️  Truncate flag active: Existing 2025 records will be wiped before loading.")
        print("=" * 60)
        sync_historical_season_stats(season="2025", db_path=DB_PATH, truncate=args.truncate)
        print("[SUCCESS] Historical 2025 stats successfully updated!")

    if args.sync_season:
        from src.sync import sync_historical_season_stats
        target_s = str(args.sync_season).strip()
        print("=" * 60)
        print(f"📥 Fetching {target_s} historical season stats with league scoring rules into: {DB_PATH}")
        if args.truncate:
            print(f"🗑️  Truncate flag active: Existing {target_s} records will be wiped before loading.")
        print("=" * 60)
        sync_historical_season_stats(season=target_s, db_path=DB_PATH, truncate=args.truncate)
        print(f"[SUCCESS] Historical {target_s} stats successfully updated!")

    if args.info:
        show_database_info()

    if args.examples:
        show_examples()

    if args.example:
        title, q = EXAMPLE_QUERIES[args.example - 1]
        print(f"\n▶ Running Example {args.example}: {title}")
        run_sql_query(q)

    if args.query:
        run_sql_query(args.query)

    if args.interactive:
        interactive_sql_shell()


if __name__ == "__main__":
    main()
