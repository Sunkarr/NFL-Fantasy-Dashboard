import pandas as pd
import sys
import json
import datetime
import argparse
import threading
import time
from pathlib import Path
from typing import Tuple, Optional
import requests
from src.config import DB_PATH, PLAYERS_CACHE_FILE, DEFAULT_LEAGUE_ID
from src.db import init_db, get_connection, set_sync_metadata

_scheduler_thread = None
_scheduler_lock = threading.Lock()
_sync_in_progress = threading.RLock()


def sync_players(db_path: Path = DB_PATH, cache_file: Path = PLAYERS_CACHE_FILE, force_refresh: bool = False) -> int:
    """Download and cache Sleeper players database (~5MB) and insert into SQLite."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Refresh cache if older than 2 hours (7200s) to keep injury statuses strictly up to date
    cache_ttl_seconds = 7200
    cache_stale = False
    if cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            if (time.time() - mtime) > cache_ttl_seconds:
                cache_stale = True
        except Exception:
            cache_stale = True

    if not cache_file.exists() or force_refresh or cache_stale:
        res = requests.get("https://api.sleeper.app/v1/players/nfl", timeout=15)
        res.raise_for_status()
        players_data = res.json()
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(players_data, f)
    else:
        with open(cache_file, "r", encoding="utf-8") as f:
            players_data = json.load(f)

    conn = get_connection(db_path)
    cur = conn.cursor()
    now = datetime.datetime.now().isoformat()

    rows = []
    for pid, p in players_data.items():
        name = p.get("full_name")
        if not name:
            fname = p.get("first_name", "")
            lname = p.get("last_name", "")
            name = f"{fname} {lname}".strip() or "Unknown"

        pos = p.get("position") or "UNKNOWN"
        team = p.get("team") or "FA"
        status = p.get("status") or "Active"
        inj = p.get("injury_status") or "Healthy"
        age = p.get("age")
        years_exp = p.get("years_exp")

        rows.append((
            str(pid),
            name,
            pos,
            team,
            status,
            inj,
            int(age) if age is not None else None,
            int(years_exp) if years_exp is not None else None,
            now
        ))

    cur.executemany('''
        INSERT OR REPLACE INTO players 
        (player_id, full_name, position, nfl_team, status, injury_status, age, years_exp, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', rows)
    conn.commit()
    conn.close()
    return len(rows)


def sync_league_and_rosters(league_id: str = DEFAULT_LEAGUE_ID, db_path: Path = DB_PATH) -> Tuple[str, int]:
    """Sync league info, owners, standings, and current rosters."""
    l_res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}", timeout=10)
    l_res.raise_for_status()
    league_info = l_res.json()
    season = str(league_info.get("season", datetime.datetime.now().year))
    try:
        from src.optimizer import get_current_nfl_week
        current_week = get_current_nfl_week()
    except Exception:
        current_week = int(league_info.get("settings", {}).get("leg", 1))

    # Persist detected season in metadata
    set_sync_metadata("active_season", season, db_path=db_path)
    set_sync_metadata("current_week", str(current_week), db_path=db_path)

    u_res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/users", timeout=10)
    u_res.raise_for_status()
    users_data = u_res.json()
    user_map = {
        u["user_id"]: {
            "owner_name": u.get("display_name", "Unknown"),
            "team_name": u.get("metadata", {}).get("team_name") or u.get("display_name", "Unknown")
        }
        for u in users_data
    }

    r_res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/rosters", timeout=10)
    r_res.raise_for_status()
    rosters_data = r_res.json()

    conn = get_connection(db_path)
    cur = conn.cursor()
    now = datetime.datetime.now().isoformat()

    team_rows = []
    roster_rows = []

    for r in rosters_data:
        rid = r["roster_id"]
        oid = r.get("owner_id")
        user_meta = user_map.get(oid, {})
        owner_name = user_meta.get("owner_name", f"Owner {rid}")
        team_name = user_meta.get("team_name", owner_name)

        settings = r.get("settings", {})
        wins = settings.get("wins", 0)
        losses = settings.get("losses", 0)
        fpts = float(settings.get("fpts", 0.0) + (settings.get("fpts_decimal", 0) / 100.0))
        fpts_against = float(settings.get("fpts_against", 0.0) + (settings.get("fpts_against_decimal", 0) / 100.0))

        team_rows.append((rid, league_id, oid, team_name, owner_name, wins, losses, fpts, fpts_against, now))

        players = set(str(p) for p in (r.get("players") or []))
        starters = set(str(p) for p in (r.get("starters") or []))
        reserve = set(str(p) for p in (r.get("reserve") or []))
        all_roster_pids = players | reserve

        for pid in all_roster_pids:
            is_st = 1 if pid in starters else 0
            is_res = 1 if pid in reserve else 0
            roster_rows.append((league_id, rid, pid, is_st, is_res, now))

    # For active week, overlay the latest week-specific starters from matchups endpoint
    try:
        m_res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/matchups/{current_week}", timeout=8)
        if m_res.status_code == 200:
            m_data = m_res.json()
            wk_starters = {}
            for m in m_data:
                rid = m.get("roster_id")
                st = set(str(p) for p in (m.get("starters") or []))
                if rid is not None and st:
                    wk_starters[rid] = st
            if wk_starters:
                updated_roster_rows = []
                for (lid, rid, pid, is_st, is_res, upd) in roster_rows:
                    if rid in wk_starters:
                        is_st = 1 if pid in wk_starters[rid] else 0
                    updated_roster_rows.append((lid, rid, pid, is_st, is_res, upd))
                roster_rows = updated_roster_rows
    except Exception as e:
        print(f"[Sync Note] Could not overlay week {current_week} starters: {e}")

    cur.executemany('''
        INSERT OR REPLACE INTO teams 
        (roster_id, league_id, owner_id, team_name, owner_name, wins, losses, fpts, fpts_against, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', team_rows)

    cur.execute("DELETE FROM current_rosters WHERE league_id = ?", (league_id,))
    cur.executemany('''
        INSERT INTO current_rosters 
        (league_id, roster_id, player_id, is_starter, is_reserve, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', roster_rows)

    conn.commit()
    conn.close()
    return season, current_week


def sync_weekly_data(
    season: str,
    max_week: int,
    league_id: str = DEFAULT_LEAGUE_ID,
    mode: str = "incremental",
    db_path: Path = DB_PATH
) -> Tuple[int, int]:
    """Sync matchup points and global NFL stats (incremental or full)."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    now = datetime.datetime.now().isoformat()

    cur.execute("SELECT DISTINCT week FROM weekly_matchup_points WHERE league_id = ? AND season = ?", (league_id, season))
    existing_pts_weeks = {row[0] for row in cur.fetchall()}

    try:
        cur.execute("SELECT DISTINCT week FROM weekly_team_matchups WHERE league_id = ? AND season = ? AND points > 0", (league_id, season))
        existing_team_weeks = {row[0] for row in cur.fetchall()}
    except Exception:
        existing_team_weeks = set()

    # A week is only considered existing if both player points and team matchups are present
    existing_weeks = existing_pts_weeks & existing_team_weeks

    if mode == "incremental":
        all_possible = set(range(1, max_week + 1))
        weeks_to_sync = sorted(list((all_possible - existing_weeks) | {max_week}))
    else:
        weeks_to_sync = list(range(1, max_week + 1))

    # Load league scoring rules and player teams map
    cur.execute("SELECT value FROM sync_metadata WHERE key = 'league_scoring_settings'")
    m_row = cur.fetchone()
    scoring_rules = json.loads(m_row[0]) if m_row else {}

    cur.execute("SELECT player_id, nfl_team FROM players")
    player_teams = dict(cur.fetchall())
    nfl_def_teams = {'ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE','DAL','DEN','DET','GB','HOU','IND','JAX','KC','LAC','LAR','LV','MIA','MIN','NE','NO','NYG','NYJ','PHI','PIT','SEA','SF','TB','TEN','WAS'}

    matchup_rows = []
    team_matchup_rows = []
    stats_rows = []

    for w in weeks_to_sync:
        # Matchups
        try:
            m_res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/matchups/{w}", timeout=10)
            if m_res.status_code == 200:
                matchups = m_res.json()
                for m in matchups:
                    rid = m.get("roster_id")
                    mid = m.get("matchup_id")
                    team_pts = float(m.get("points") or 0.0)

                    if rid is not None and mid is not None:
                        team_matchup_rows.append((
                            league_id,
                            season,
                            w,
                            rid,
                            mid,
                            team_pts,
                            now
                        ))

                    players_pts = m.get("players_points") or {}
                    starters = set(m.get("starters") or [])

                    for pid, pts in players_pts.items():
                        matchup_rows.append((
                            league_id,
                            season,
                            w,
                            rid,
                            str(pid),
                            float(pts) if pts is not None else 0.0,
                            1 if str(pid) in starters else 0,
                            now
                        ))
        except Exception as e:
            print(f"Error fetching matchups for week {w}: {e}")

        # Global NFL Stats
        try:
            s_res = requests.get(f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{w}", timeout=15)
            if s_res.status_code == 200:
                stats_dict = s_res.json()
                for pid, st in stats_dict.items():
                    if scoring_rules:
                        pts = 0.0
                        for k, weight in scoring_rules.items():
                            if k in st:
                                pts += float(st[k]) * float(weight)
                        pts = round(pts, 2)
                    else:
                        pts = float(st.get("pts_ppr", st.get("pts_half_ppr", st.get("pts_std", 0.0))))

                    team = player_teams.get(pid, "FA")
                    if pid in nfl_def_teams:
                        team = pid

                    stats_rows.append((
                        season,
                        w,
                        str(pid),
                        team,
                        pts,
                        float(st.get("pass_yd", 0.0)),
                        float(st.get("pass_td", 0.0)),
                        float(st.get("pass_int", 0.0)),
                        float(st.get("rush_yd", 0.0)),
                        float(st.get("rush_td", 0.0)),
                        float(st.get("rec", 0.0)),
                        float(st.get("rec_yd", 0.0)),
                        float(st.get("rec_td", 0.0)),
                        now
                    ))
        except Exception as e:
            print(f"Error fetching stats for week {w}: {e}")

    if matchup_rows:
        cur.executemany('''
            INSERT OR REPLACE INTO weekly_matchup_points 
            (league_id, season, week, roster_id, player_id, points, started, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', matchup_rows)

    if team_matchup_rows:
        cur.executemany('''
            INSERT OR REPLACE INTO weekly_team_matchups
            (league_id, season, week, roster_id, matchup_id, points, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', team_matchup_rows)

    if stats_rows:
        cur.executemany('''
            INSERT OR REPLACE INTO weekly_nfl_stats 
            (season, week, player_id, nfl_team, points, pass_yd, pass_td, pass_int, rush_yd, rush_td, rec, rec_yd, rec_td, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', stats_rows)

    conn.commit()
    conn.close()
    return len(matchup_rows), len(stats_rows)

def sync_historical_season_stats(
    season: str = "2025",
    max_week: int = 18,
    league_id: str = DEFAULT_LEAGUE_ID,
    db_path: Path = DB_PATH,
    truncate: bool = False
) -> int:
    """
    Fetch full historical regular season player stats (Weeks 1 to max_week) from Sleeper API
    and calculate fantasy points according to league-specific scoring rules.
    Accurately maps NFL teams per game using nflverse historical rosters.
    """
    conn = get_connection(db_path)
    cur = conn.cursor()
    now = datetime.datetime.now().isoformat()

    if truncate:
        cur.execute("DELETE FROM weekly_nfl_stats WHERE season = ?", (str(season),))
        conn.commit()
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Truncated existing weekly_nfl_stats records for season {season}.")

    # Load league scoring rules
    cur.execute("SELECT value FROM sync_metadata WHERE key = 'league_scoring_settings'")
    m_row = cur.fetchone()
    scoring_rules = json.loads(m_row[0]) if m_row else {}

    cur.execute("SELECT player_id, nfl_team FROM players")
    player_teams = dict(cur.fetchall())
    nfl_def_teams = {'ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE','DAL','DEN','DET','GB','HOU','IND','JAX','KC','LAC','LAR','LV','MIA','MIN','NE','NO','NYG','NYJ','PHI','PIT','SEA','SF','TB','TEN','WAS'}

    # Load historical roster dataset from nflverse to accurately associate players with their team for that year/week
    # e.g. Kenneth Walker was SEA in 2024 and 2025, KC in 2026.
    # Uses .csv.gz to avoid pyarrow Parquet repetition level histogram mismatch errors.
    week_team_map = {}
    season_team_map = {}
    try:
        roster_cache_file = db_path.parent / f"roster_{season}.csv.gz"
        if not roster_cache_file.exists():
            r_url = f"https://github.com/nflverse/nflverse-data/releases/download/rosters/roster_{season}.csv.gz"
            r_resp = requests.get(r_url, timeout=15)
            if r_resp.status_code == 200:
                with open(roster_cache_file, "wb") as f:
                    f.write(r_resp.content)
        if roster_cache_file.exists():
            r_df = pd.read_csv(roster_cache_file, compression='gzip', low_memory=False)
            clean_r = r_df.dropna(subset=['sleeper_id']).copy()
            clean_r['sleeper_id'] = clean_r['sleeper_id'].astype(str).str.split('.').str[0]
            week_team_map = clean_r.set_index(['sleeper_id', 'week'])['team'].to_dict()
            season_team_map = clean_r.groupby('sleeper_id')['team'].last().to_dict()
            print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Loaded {len(season_team_map)} historical player team mappings for {season} from nflverse.")
    except Exception as re:
        print(f"Note: Could not load historical nflverse roster for {season}: {re}")

    total_rows = 0
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Syncing historical regular season {season} stats...")

    insert_sql = (
        "INSERT OR REPLACE INTO weekly_nfl_stats "
        "(season, week, player_id, nfl_team, points, pass_yd, pass_td, pass_int, rush_yd, rush_td, rec, rec_yd, rec_td, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    for w in range(1, max_week + 1):
        try:
            res = requests.get(f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{w}", timeout=15)
            if res.status_code != 200:
                continue
            stats_dict = res.json()
            rows = []
            for pid, st in stats_dict.items():
                pts = 0.0
                for k, weight in scoring_rules.items():
                    if k in st:
                        pts += float(st[k]) * float(weight)
                pts = round(pts, 2)

                if st.get('gp', 0) > 0 or pts != 0 or st.get('off_snp', 0) > 0:
                    pid_str = str(pid)
                    if pid in nfl_def_teams:
                        team = pid
                    else:
                        team = week_team_map.get((pid_str, w)) or season_team_map.get(pid_str) or player_teams.get(pid, 'FA')

                    rows.append((
                        str(season),
                        w,
                        pid_str,
                        team,
                        pts,
                        float(st.get('pass_yd', 0.0)),
                        float(st.get('pass_td', 0.0)),
                        float(st.get('pass_int', 0.0)),
                        float(st.get('rush_yd', 0.0)),
                        float(st.get('rush_td', 0.0)),
                        float(st.get('rec', 0.0)),
                        float(st.get('rec_yd', 0.0)),
                        float(st.get('rec_td', 0.0)),
                        now
                    ))
            if rows:
                cur.executemany(insert_sql, rows)
                conn.commit()
                total_rows += len(rows)
        except Exception as e:
            print(f"Error syncing {season} week {w}: {e}")

    conn.close()
    print(f"Synced {total_rows} historical player records for season {season}.")
    return total_rows



def sync_transactions(
    league_id: str = DEFAULT_LEAGUE_ID,
    season: Optional[str] = None,
    max_week: int = 18,
    db_path: Path = DB_PATH
) -> int:
    """
    Sync completed league transactions (waivers, free agent pickups, trades) into SQLite.
    Draft picks are excluded. Pre-season roster moves are tagged with is_preseason=1.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    now_iso = datetime.datetime.now().isoformat()

    all_rows = []
    rounds_to_check = range(1, min(max_week + 2, 19))

    for r in rounds_to_check:
        try:
            res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/transactions/{r}", timeout=10)
            if res.status_code != 200:
                continue
            txs = res.json()
            if not txs:
                continue

            for t in txs:
                if t.get("status") != "complete":
                    continue

                tid = str(t.get("transaction_id"))
                tx_type = str(t.get("type", "unknown"))
                created_ms = t.get("created") or 0
                created_dt = datetime.datetime.fromtimestamp(created_ms / 1000.0) if created_ms else datetime.datetime.now()
                created_iso = created_dt.isoformat()

                # Determine if pre-season move (round 1 before Sept 9th)
                is_preseason = 1 if (r == 1 and (created_dt.month < 9 or (created_dt.month == 9 and created_dt.day < 9))) else 0

                roster_ids = json.dumps(t.get("roster_ids") or [])
                adds = json.dumps(t.get("adds") or {})
                drops = json.dumps(t.get("drops") or {})

                waiver_bid = 0
                settings = t.get("settings") or {}
                if isinstance(settings, dict) and "waiver_bid" in settings:
                    waiver_bid = int(settings.get("waiver_bid") or 0)

                all_rows.append((
                    tid,
                    league_id,
                    str(season or created_dt.year),
                    r,
                    is_preseason,
                    int(created_ms),
                    created_iso,
                    tx_type,
                    "complete",
                    roster_ids,
                    adds,
                    drops,
                    waiver_bid,
                    now_iso
                ))
        except Exception as e:
            print(f"Error fetching transactions for round {r}: {e}")

    if all_rows:
        cur.executemany('''
            INSERT OR REPLACE INTO roster_moves
            (transaction_id, league_id, season, round, is_preseason, created_at, created_iso, type, status, roster_ids, adds, drops, waiver_bid, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', all_rows)
        conn.commit()

    conn.close()
    return len(all_rows)


def run_full_sync(
    league_id: str = DEFAULT_LEAGUE_ID,
    mode: str = "incremental",
    force_players: bool = False,
    db_path: Path = DB_PATH
) -> None:
    """Orchestrate players, league, weekly stats, and transactions download."""
    with _sync_in_progress:
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting sync (mode={mode})...")
        p_count = sync_players(db_path=db_path, force_refresh=force_players)
        print(f"Synced {p_count} players.")

        season, current_week = sync_league_and_rosters(league_id=league_id, db_path=db_path)
        print(f"Synced league & rosters for season {season}, active week {current_week}.")

        m_count, s_count = sync_weekly_data(
            season=season,
            max_week=current_week,
            league_id=league_id,
            mode=mode,
            db_path=db_path
        )
        print(f"Synced {m_count} matchup scores and {s_count} NFL player stats entries.")

        # Ensure historical seasons 2025 and 2024 are available for player profiles & charts
        for hist_season in ["2025", "2024"]:
            try:
                conn = get_connection(db_path)
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM weekly_nfl_stats WHERE season = ?", (hist_season,))
                cnt_hist = c.fetchone()[0]
                conn.close()
                if cnt_hist < 1000:
                    print(f"Historical {hist_season} season stats not found (count={cnt_hist}). Syncing {hist_season}...")
                    sync_historical_season_stats(season=hist_season, db_path=db_path)
            except Exception as he:
                print(f"[Historical {hist_season} Sync Note]: {he}")

        # Sync completed roster moves / transactions
        try:
            t_count = sync_transactions(
                league_id=league_id,
                season=season,
                max_week=current_week,
                db_path=db_path
            )
            print(f"Synced {t_count} completed transactions.")
        except Exception as te:
            print(f"[Transactions Sync Note]: {te}")

        # Proactively refresh current week projections with latest Sleeper estimates
        try:
            from src.optimizer import get_cached_or_live_projections
            get_cached_or_live_projections(season=season, week=current_week, force_refresh=True, db_path=db_path)
            print(f"Synced latest matchup projections for season {season}, week {current_week}.")
        except Exception as pe:
            print(f"[Projections Sync Note]: {pe}")

        now_iso = datetime.datetime.now().isoformat()
        set_sync_metadata("last_sync", now_iso, db_path=db_path)
        set_sync_metadata("last_sync_success", now_iso, db_path=db_path)
        print("Data sync completed successfully.")


def _scheduler_worker(league_id: str, db_path: Path):
    """
    Background worker thread running on the exact hour and half-hour (:00 and :30).
    Runs indefinitely without blocking main thread.
    """
    try:
        from src.db import get_last_sync_time
        last_dt = get_last_sync_time(db_path)
        has_matchups = False
        if db_path.exists():
            try:
                conn_chk = get_connection(db_path)
                cur_chk = conn_chk.cursor()
                cur_chk.execute("SELECT COUNT(*) FROM weekly_team_matchups WHERE points > 0")
                has_matchups = (cur_chk.fetchone()[0] > 0)
                conn_chk.close()
            except Exception:
                has_matchups = False

        if last_dt is None or not has_matchups or (datetime.datetime.now() - last_dt).total_seconds() > 1800:
            print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [Sync Scheduler] Triggering initial background sync...")
            run_full_sync(league_id=league_id, mode="incremental", db_path=db_path)
    except Exception as e:
        print(f"[Sync Scheduler Initial Error]: {e}", file=sys.stderr)

    while True:
        try:
            now = datetime.datetime.now()
            minute = now.minute
            second = now.second

            # Target next :00 or :30 boundary
            if minute < 30:
                target_min = 30
            else:
                target_min = 60

            seconds_to_wait = (target_min - minute) * 60 - second
            if seconds_to_wait <= 0:
                seconds_to_wait = 1800  # Fallback: 30 minutes

            time.sleep(seconds_to_wait)
            run_full_sync(league_id=league_id, mode="incremental", db_path=db_path)
        except Exception as e:
            print(f"[Sync Scheduler Error]: {e}", file=sys.stderr)
            time.sleep(60)


def start_background_scheduler(league_id: str = DEFAULT_LEAGUE_ID, db_path: Path = DB_PATH) -> bool:
    """Start persistent background scheduler thread if not already running."""
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _scheduler_thread = threading.Thread(
                target=_scheduler_worker,
                args=(league_id, db_path),
                daemon=True,
                name="SleeperSyncScheduler"
            )
            _scheduler_thread.start()
            return True
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync Sleeper NFL Fantasy data into SQLite.")
    parser.add_argument("--league-id", default=DEFAULT_LEAGUE_ID, help="Sleeper League ID")
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental", help="Sync mode")
    parser.add_argument("--force-players", action="store_true", help="Force refresh of players database")
    args = parser.parse_args()

    run_full_sync(
        league_id=args.league_id,
        mode=args.mode,
        force_players=args.force_players
    )
