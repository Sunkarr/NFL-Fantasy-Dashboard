import sqlite3
import datetime
from pathlib import Path
from typing import Tuple, Optional
import pandas as pd
from src.config import DB_PATH, DEFAULT_LEAGUE_ID


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


def init_db(db_path: Path = DB_PATH):
    """Create SQLite tables if they do not exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS players (
            player_id TEXT PRIMARY KEY,
            full_name TEXT,
            position TEXT,
            nfl_team TEXT,
            status TEXT,
            injury_status TEXT,
            age INTEGER,
            years_exp INTEGER,
            updated_at TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS teams (
            roster_id INTEGER,
            league_id TEXT,
            owner_id TEXT,
            team_name TEXT,
            owner_name TEXT,
            wins INTEGER,
            losses INTEGER,
            fpts REAL,
            fpts_against REAL DEFAULT 0.0,
            updated_at TIMESTAMP,
            PRIMARY KEY (roster_id, league_id)
        )
    ''')

    # Ensure fpts_against exists if table was previously created
    cur.execute("PRAGMA table_info(teams);")
    cols = [c[1] for c in cur.fetchall()]
    if 'fpts_against' not in cols:
        cur.execute("ALTER TABLE teams ADD COLUMN fpts_against REAL DEFAULT 0.0;")

    cur.execute('''
        CREATE TABLE IF NOT EXISTS current_rosters (
            league_id TEXT,
            roster_id INTEGER,
            player_id TEXT,
            is_starter INTEGER,
            is_reserve INTEGER DEFAULT 0,
            updated_at TIMESTAMP,
            PRIMARY KEY (league_id, roster_id, player_id)
        )
    ''')

    # Ensure is_reserve exists if table was previously created
    cur.execute("PRAGMA table_info(current_rosters);")
    roster_cols = [c[1] for c in cur.fetchall()]
    if 'is_reserve' not in roster_cols:
        cur.execute("ALTER TABLE current_rosters ADD COLUMN is_reserve INTEGER DEFAULT 0;")

    cur.execute('''
        CREATE TABLE IF NOT EXISTS weekly_matchup_points (
            league_id TEXT,
            season TEXT,
            week INTEGER,
            roster_id INTEGER,
            player_id TEXT,
            points REAL,
            started INTEGER,
            updated_at TIMESTAMP,
            PRIMARY KEY (league_id, season, week, roster_id, player_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS weekly_team_matchups (
            league_id TEXT,
            season TEXT,
            week INTEGER,
            roster_id INTEGER,
            matchup_id INTEGER,
            points REAL,
            updated_at TIMESTAMP,
            PRIMARY KEY (league_id, season, week, roster_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS weekly_nfl_stats (
            season TEXT,
            week INTEGER,
            player_id TEXT,
            nfl_team TEXT,
            points REAL,
            pass_yd REAL,
            pass_td REAL,
            pass_int REAL,
            rush_yd REAL,
            rush_td REAL,
            rec REAL,
            rec_yd REAL,
            rec_td REAL,
            updated_at TIMESTAMP,
            PRIMARY KEY (season, week, player_id)
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS roster_moves (
            transaction_id TEXT PRIMARY KEY,
            league_id TEXT,
            season TEXT,
            round INTEGER,
            is_preseason INTEGER DEFAULT 0,
            created_at INTEGER,
            created_iso TEXT,
            type TEXT,
            status TEXT,
            roster_ids TEXT,
            adds TEXT,
            drops TEXT,
            waiver_bid INTEGER DEFAULT 0,
            updated_at TIMESTAMP
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS sync_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    conn.commit()
    conn.close()


def set_sync_metadata(key: str, value: str, db_path: Path = DB_PATH) -> None:
    """Set or update key-value pair in sync_metadata table."""
    init_db(db_path)
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO sync_metadata (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_sync_metadata(key: str, db_path: Path = DB_PATH) -> Optional[str]:
    """Retrieve value for a key from sync_metadata."""
    if not db_path.exists():
        return None
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("SELECT value FROM sync_metadata WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def get_last_sync_time(db_path: Path = DB_PATH) -> Optional[datetime.datetime]:
    """Retrieve the timestamp of the last successful data fetch."""
    for key in ("last_sync_success", "last_sync", "last_sync_time"):
        val = get_sync_metadata(key, db_path)
        if val:
            try:
                return datetime.datetime.fromisoformat(val)
            except (ValueError, TypeError):
                pass
    return None


def format_last_sync(dt: Optional[datetime.datetime]) -> str:
    """Return a clean human-readable representation of the last sync time."""
    if dt is None:
        return "Not synced yet"
    now = datetime.datetime.now()
    diff = now - dt
    seconds = int(diff.total_seconds())

    if seconds < 60:
        return f"{seconds}s ago"
    elif seconds < 3600:
        return f"{seconds // 60}m ago"
    elif seconds < 86400:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m ago"
    else:
        return dt.strftime("%b %d, %H:%M")


def get_active_season(db_path: Path = DB_PATH, league_id: str = DEFAULT_LEAGUE_ID) -> str:
    """
    Determine the active season for the league.
    Prefers the season stored in sync_metadata, otherwise queries weekly_matchup_points,
    and falls back to the current calendar year.
    """
    val = get_sync_metadata("active_season", db_path)
    if val:
        return val

    if db_path.exists():
        conn = get_connection(db_path)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT DISTINCT season FROM weekly_matchup_points WHERE league_id = ? ORDER BY season DESC LIMIT 1",
                (league_id,)
            )
            row = cur.fetchone()
            if row and row[0]:
                conn.close()
                return str(row[0])
        except Exception:
            pass
        finally:
            conn.close()

    return str(datetime.datetime.now().year)


def load_league_data(
    db_path: Path = DB_PATH,
    league_id: str = DEFAULT_LEAGUE_ID,
    season: Optional[str] = None
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load core dataframes for the league strictly filtered to the active season."""
    if not db_path.exists():
        empty = pd.DataFrame()
        return empty, empty, empty, empty

    conn = get_connection(db_path)

    # Resolve active season if not provided
    if season is None:
        season = get_active_season(db_path, league_id)

    # 1. Teams
    teams = pd.read_sql_query('''
        SELECT roster_id, league_id, owner_id, team_name, owner_name, wins, losses, fpts, fpts_against
        FROM teams
        WHERE league_id = ?
        ORDER BY wins DESC, fpts DESC
    ''', conn, params=(league_id,))

    # 2. Current Rosters with player metadata and team affiliation
    rosters = pd.read_sql_query('''
        SELECT r.roster_id, t.team_name, r.league_id, r.player_id, r.is_starter,
               COALESCE(r.is_reserve, 0) as is_reserve,
               p.full_name as player_name, p.position, p.nfl_team, p.status, p.injury_status,
               p.age, p.years_exp
        FROM current_rosters r
        JOIN teams t ON r.roster_id = t.roster_id AND r.league_id = t.league_id
        JOIN players p ON r.player_id = p.player_id
        WHERE r.league_id = ?
    ''', conn, params=(league_id,))

    # 3. Weekly Matchup Points (filtered strictly to active season)
    if season:
        matchups = pd.read_sql_query('''
            SELECT m.season, m.week, m.roster_id, t.team_name, m.player_id, p.full_name as player_name,
                   p.position, p.nfl_team, m.points, m.started
            FROM weekly_matchup_points m
            JOIN teams t ON m.roster_id = t.roster_id AND m.league_id = t.league_id
            JOIN players p ON m.player_id = p.player_id
            WHERE m.league_id = ? AND m.season = ?
        ''', conn, params=(league_id, season))

        # 4. Weekly NFL Stats with player metadata & ownership (filtered strictly to season)
        nfl_stats = pd.read_sql_query('''
            SELECT s.season, s.week, s.player_id, p.full_name as player_name, p.position, 
                   COALESCE(s.nfl_team, p.nfl_team, 'FA') as nfl_team,
                   p.injury_status, COALESCE(t.team_name, 'Free Agent') as current_owner,
                   s.points, s.pass_yd, s.pass_td, s.pass_int, s.rush_yd, s.rush_td, s.rec, s.rec_yd, s.rec_td
            FROM weekly_nfl_stats s
            JOIN players p ON s.player_id = p.player_id
            LEFT JOIN current_rosters r ON s.player_id = r.player_id AND r.league_id = ?
            LEFT JOIN teams t ON r.roster_id = t.roster_id AND r.league_id = t.league_id
            WHERE s.season = ?
        ''', conn, params=(league_id, season))
    else:
        matchups = pd.read_sql_query('''
            SELECT m.season, m.week, m.roster_id, t.team_name, m.player_id, p.full_name as player_name,
                   p.position, p.nfl_team, m.points, m.started
            FROM weekly_matchup_points m
            JOIN teams t ON m.roster_id = t.roster_id AND m.league_id = t.league_id
            JOIN players p ON m.player_id = p.player_id
            WHERE m.league_id = ?
        ''', conn, params=(league_id,))

        nfl_stats = pd.read_sql_query('''
            SELECT s.season, s.week, s.player_id, p.full_name as player_name, p.position, 
                   COALESCE(s.nfl_team, p.nfl_team, 'FA') as nfl_team,
                   p.injury_status, COALESCE(t.team_name, 'Free Agent') as current_owner,
                   s.points, s.pass_yd, s.pass_td, s.pass_int, s.rush_yd, s.rush_td, s.rec, s.rec_yd, s.rec_td
            FROM weekly_nfl_stats s
            JOIN players p ON s.player_id = p.player_id
            LEFT JOIN current_rosters r ON s.player_id = r.player_id AND r.league_id = ?
            LEFT JOIN teams t ON r.roster_id = t.roster_id AND r.league_id = t.league_id
        ''', conn, params=(league_id,))

    conn.close()
    return teams, rosters, matchups, nfl_stats


def load_team_matchups(
    db_path: Path = DB_PATH,
    league_id: str = DEFAULT_LEAGUE_ID,
    season: Optional[str] = None
) -> pd.DataFrame:
    """
    Load weekly team-level matchup records (scores and head-to-head pairings).
    If the weekly_team_matchups table is empty, reconstructs from weekly_matchup_points.
    """
    if not db_path.exists():
        return pd.DataFrame()

    conn = get_connection(db_path)
    if season is None:
        season = get_active_season(db_path, league_id)

    # 1. Primary: load from weekly_team_matchups
    try:
        df = pd.read_sql_query('''
            SELECT m.season, m.week, m.roster_id, t.team_name, t.owner_name, m.matchup_id, m.points
            FROM weekly_team_matchups m
            JOIN teams t ON m.roster_id = t.roster_id AND m.league_id = t.league_id
            WHERE m.league_id = ? AND m.season = ?
            ORDER BY m.week, m.matchup_id, m.points DESC
        ''', conn, params=(league_id, season))
        if not df.empty and (df['points'] > 0).any():
            conn.close()
            return df
    except Exception:
        pass

    # 2. Fallback: reconstruct from weekly_matchup_points where started == 1
    try:
        df = pd.read_sql_query('''
            SELECT m.season, m.week, m.roster_id, t.team_name, t.owner_name, 0 as matchup_id, SUM(m.points) as points
            FROM weekly_matchup_points m
            JOIN teams t ON m.roster_id = t.roster_id AND m.league_id = t.league_id
            WHERE m.league_id = ? AND m.season = ? AND m.started = 1
            GROUP BY m.season, m.week, m.roster_id, t.team_name, t.owner_name
            ORDER BY m.week, points DESC
        ''', conn, params=(league_id, season))
        conn.close()
        return df
    except Exception:
        conn.close()
        return pd.DataFrame()


def load_roster_moves(
    db_path: Path = DB_PATH,
    league_id: str = DEFAULT_LEAGUE_ID,
    season: Optional[str] = None
) -> pd.DataFrame:
    """Load completed roster moves/transactions from SQLite."""
    if not db_path.exists():
        return pd.DataFrame()

    conn = get_connection(db_path)
    if season is None:
        season = get_active_season(db_path, league_id)

    try:
        df = pd.read_sql_query('''
            SELECT transaction_id, league_id, season, round, is_preseason,
                   created_at, created_iso, type, status, roster_ids,
                   adds, drops, waiver_bid, updated_at
            FROM roster_moves
            WHERE league_id = ? AND season = ? AND status = 'complete'
            ORDER BY created_at DESC
        ''', conn, params=(league_id, season))
        conn.close()
        return df
    except Exception:
        conn.close()
        return pd.DataFrame()
