import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
import sqlite3
from pathlib import Path
from dataclasses import dataclass, asdict
from src.config import TEAM_PALETTE, FREE_AGENT_COLOR, NFL_TEAM_COLORS, NFL_TEAM_NAMES
from src.optimizer import get_cached_or_live_projections, get_league_scoring_settings, calculate_projected_points

def resolve_nfl_team(val: Any, fallback: str = "FA") -> str:
    """Safely resolve and canonicalize NFL franchise abbreviation."""
    if val is None or pd.isna(val):
        candidate = str(fallback or "FA").strip().upper()
    else:
        candidate = str(val).strip().upper()
    if not candidate or candidate in ("NAN", "NONE", "NULL", "FA", ""):
        candidate = str(fallback or "FA").strip().upper()
    if not candidate or candidate in ("NAN", "NONE", "NULL", ""):
        return "FA"

    # Canonicalize historical Sleeper franchise codes across seasons
    aliases = {
        "LA": "LAR",
        "JAC": "JAX",
        "WSH": "WAS",
        "OAK": "LV",
        "SD": "LAC",
        "STL": "LAR",
    }
    return aliases.get(candidate, candidate)



def get_player_selection_options(
    df_player_stats: pd.DataFrame,
    df_rosters: pd.DataFrame,
    pos_filter: str = "ALL",
    owner_filter: str = "Rostered Only",
    search_query: str = ""
) -> Dict[str, str]:
    """
    Generate dictionary of player labels mapped to player_id for Marimo dropdowns.
    Filters by position, fantasy team ownership, and search query.
    Sorted by mean_points DESC.
    """
    if df_player_stats is None or df_player_stats.empty:
        return {}

    # Relevant players: scored points or currently on a roster
    rostered_pids = set(df_rosters['player_id'].astype(str).unique()) if df_rosters is not None and not df_rosters.empty else set()
    df = df_player_stats.copy()
    df['player_id_str'] = df['player_id'].astype(str)

    mask = (df['mean_points'] > 0) | (df['player_id_str'].isin(rostered_pids))
    df = df[mask].copy()

    # Position filter
    if pos_filter and pos_filter != "ALL":
        df = df[df['position'] == pos_filter]

    # Owner filter
    if owner_filter and owner_filter != "ALL":
        if owner_filter == "Rostered Only":
            df = df[df['player_id_str'].isin(rostered_pids)]
        elif owner_filter == "Free Agents":
            df = df[~df['player_id_str'].isin(rostered_pids)]
        else:
            df = df[df['current_owner'] == owner_filter]

    # Search query
    if search_query and search_query.strip():
        q = search_query.strip().lower()
        match_mask = (
            df['player_name'].astype(str).str.lower().str.contains(q) |
            df['nfl_team'].astype(str).str.lower().str.contains(q) |
            df['position'].astype(str).str.lower().str.contains(q)
        )
        df = df[match_mask]

    # Sort by mean_points DESC, then total_points DESC
    df = df.sort_values(by=['mean_points', 'total_points'], ascending=[False, False])

    # Cap options if not filtering to rostered only, to keep dropdown sleek and responsive
    has_search = bool(search_query and search_query.strip())
    if not has_search and owner_filter in ('ALL', 'Free Agents') and len(df) > 50:
        df = df.head(50)
    elif has_search and len(df) > 50:
        df = df.head(50)

    options = {}
    for _, r in df.iterrows():
        p_name = str(r['player_name'])
        pos = str(r['position'])
        nfl = str(r['nfl_team']) if r['nfl_team'] else "FA"
        ppg = float(r['mean_points']) if pd.notna(r['mean_points']) else 0.0
        owner = str(r.get('current_owner', 'Free Agent'))
        pid = str(r['player_id'])

        if owner and owner != 'Free Agent':
            label = f"{p_name} ({pos} • {nfl} • {ppg:.1f} PPG • {owner})"
        else:
            label = f"{p_name} ({pos} • {nfl} • {ppg:.1f} PPG)"

        # Ensure label uniqueness
        if label in options:
            label = f"{label} #{pid}"
        options[label] = pid

    return options



@dataclass
class PlayerProfile:
    """Typed domain representation of an individual player's statistical profile and metrics."""
    player_id: str
    player_name: str
    position: str
    nfl_team: str
    owner_name: str
    team_name: str
    headshot_url: str
    injury_status: str
    age: Optional[int]
    years_exp: Optional[int]
    games_played: int
    total_active_weeks: int
    missed_games: int
    availability_pct: float
    health_assessment: str
    health_color: str
    health_badge_bg: str
    mean_points: float
    std_points: float
    cv: float
    consistency_tier: str
    consistency_desc: str
    floor_points: float
    ceiling_points: float
    median_points: float
    total_points: float
    pos_rank: int
    trade_value: float
    weekly_df: pd.DataFrame
    best_week: Optional[int]
    best_pts: Optional[float]
    best_season: str
    worst_week: Optional[int]
    worst_pts: Optional[float]
    career_best_str: str
    tot_pass_yd: float
    tot_pass_td: float
    tot_pass_int: float
    tot_rush_yd: float
    tot_rush_td: float
    tot_rec: float
    tot_rec_yd: float
    tot_rec_td: float
    baseline: float
    vorp: float
    scarcity_weight: float
    elite_multiplier: float
    injury_discount: float
    raw_trade_value: float
    mean_2025: float
    gp_2025: int
    total_2025: float
    history_by_season: Dict[str, Any]
    history_summary_str: str
    proj_beat_count: int
    proj_total_games: int
    proj_beat_pct: float
    proj_net_diff: float
    proj_avg_diff: float
    team_color: str

    def __getitem__(self, key: str) -> Any:
        """Allow backwards-compatible dict-like access."""
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Allow backwards-compatible dict-like .get() access."""
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary if needed."""
        return asdict(self)


@dataclass
class PlayerComparison:
    """Typed domain representation of head-to-head player comparison."""
    player_a: PlayerProfile
    player_b: PlayerProfile
    h2h_df: pd.DataFrame
    wins_a: int
    wins_b: int
    ties: int
    metrics_comp: List[Dict[str, Any]]
    verdict_bullets: List[str]
    recommendation: str
    combined_chart_df: pd.DataFrame

    def __getitem__(self, key: str) -> Any:
        """Allow backwards-compatible dict-like access."""
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Allow backwards-compatible dict-like .get() access."""
        return getattr(self, key, default)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary if needed."""
        return asdict(self)

def get_player_detailed_analytics(
    player_id: str,
    df_player_stats: pd.DataFrame,
    df_nfl_stats: pd.DataFrame,
    df_matchups: pd.DataFrame,
    df_rosters: pd.DataFrame,
    val_df: Optional[pd.DataFrame] = None,
    db_path: Optional[str] = None
) -> Optional[PlayerProfile]:
    """
    Extract player statistical profile and performance metrics:
    - Metadata (Name, Position, NFL Team, Owner, Headshot, Age, Experience)
    - Availability & Games Played (% games active, injury status)
    - Scoring distribution (PPG, Std Dev, Variance Tier, Floor, Ceiling, Median, Total Points)
    - Market Trade Value (0-100 VORP benchmark)
    - Weekly Game Log with Fantasy Matchup Status (Started / Bench / FA) and Box Scores
    """
    if not player_id:
        return None

    pid_str = str(player_id)

    # 1. Base player row from df_player_stats
    p_row = None
    if df_player_stats is not None and not df_player_stats.empty:
        sub = df_player_stats[df_player_stats['player_id'].astype(str) == pid_str]
        if not sub.empty:
            p_row = sub.iloc[0]

    # Fallback: query players table directly if not in df_player_stats
    if p_row is None and db_path:
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT player_id, full_name, position, nfl_team, status, injury_status, age, years_exp FROM players WHERE player_id = ?", (pid_str,))
            row = cur.fetchone()
            conn.close()
            if row:
                p_row = pd.Series({
                    'player_id': row[0],
                    'player_name': row[1],
                    'position': row[2],
                    'nfl_team': row[3],
                    'status': row[4],
                    'injury_status': row[5] or 'Healthy',
                    'age': row[6],
                    'years_exp': row[7],
                    'current_owner': 'Free Agent',
                    'games_played': 0,
                    'total_points': 0.0,
                    'mean_points': 0.0,
                    'std_points': 0.0,
                    'cv': 0.0,
                    'min_points': 0.0,
                    'max_points': 0.0,
                    'median_points': 0.0,
                    'pos_rank': 99,
                    'consistency_tier': '—'
                })
        except Exception:
            pass

    if p_row is None:
        return None

    player_name = str(p_row.get('player_name', pid_str))
    position = str(p_row.get('position', 'WR'))
    nfl_team = str(p_row.get('nfl_team', 'FA'))
    injury_status = str(p_row.get('injury_status', 'Healthy') or 'Healthy')

    # Ownership from df_rosters
    owner_name = "Free Agent"
    team_name = "Free Agent"
    is_currently_starter = False
    is_currently_reserve = False
    if df_rosters is not None and not df_rosters.empty:
        r_match = df_rosters[df_rosters['player_id'].astype(str) == pid_str]
        if not r_match.empty:
            team_name = str(r_match.iloc[0].get('team_name', 'Free Agent'))
            owner_name = team_name
            is_currently_starter = bool(r_match.iloc[0].get('is_starter', 0))
            is_currently_reserve = bool(r_match.iloc[0].get('is_reserve', 0))

    # Headshot
    if position == 'DEF' or pid_str == nfl_team:
        headshot_url = f"https://sleepercdn.com/images/team_logos/nfl/{nfl_team.lower()}.png"
    else:
        headshot_url = f"https://sleepercdn.com/content/nfl/players/{pid_str}.jpg"

    # Trade Value and Breakdown components
    trade_value = 0.0
    baseline = 8.0
    vorp = 0.0
    scarcity_weight = 1.0
    elite_multiplier = 1.0
    injury_discount = 1.0
    raw_trade_value = 0.0
    if val_df is not None and not val_df.empty and 'trade_value' in val_df.columns:
        tv_match = val_df[val_df['player_id'].astype(str) == pid_str]
        if not tv_match.empty:
            row_tv = tv_match.iloc[0]
            trade_value = float(row_tv.get('trade_value', 0.0))
            baseline = float(row_tv.get('baseline', 8.0))
            vorp = float(row_tv.get('vorp', 0.0))
            scarcity_weight = float(row_tv.get('scarcity_weight', 1.0))
            elite_multiplier = float(row_tv.get('elite_multiplier', 1.0))
            injury_discount = float(row_tv.get('injury_discount', 1.0))
            raw_trade_value = float(row_tv.get('raw_trade_value', 0.0))

    # Total Season Weeks Completed:
    team_games_played = 0
    if df_nfl_stats is not None and not df_nfl_stats.empty:
        if nfl_team and nfl_team not in ('FA', ''):
            team_stats = df_nfl_stats[df_nfl_stats['nfl_team'] == nfl_team]
            if not team_stats.empty:
                wks_played = team_stats.groupby('week')['points'].sum()
                team_games_played = len([w for w, s in wks_played.items() if s > 0])
        
        # Fallback if team_games_played not found (or FA/Def)
        if team_games_played == 0:
            wk_sums = df_nfl_stats.groupby('week')['points'].sum()
            team_games_played = len([w for w, s in wk_sums.items() if s > 500])

    total_active_weeks = max(team_games_played, 1)

    # Load full historical game logs (both 2025 and 2026) directly from SQLite if available
    all_db_stats = pd.DataFrame()
    if db_path is not None and Path(db_path).exists():
        try:
            with sqlite3.connect(db_path) as conn:
                all_db_stats = pd.read_sql_query("""
                    SELECT season, week, 
                           COALESCE(NULLIF(NULLIF(NULLIF(NULLIF(nfl_team, 'nan'), 'None'), 'NULL'), ''), '') as nfl_team,
                           points, pass_yd, pass_td, pass_int,
                           rush_yd, rush_td, rec, rec_yd, rec_td
                    FROM weekly_nfl_stats
                    WHERE player_id = ?
                    ORDER BY season ASC, week ASC
                """, conn, params=(pid_str,))
        except Exception:
            pass

    # Pre-fetch weekly projections for 2026 to evaluate performance against targets
    scoring_settings = get_league_scoring_settings(db_path=db_path) if db_path else {}
    proj_by_week = {}
    if db_path:
        wks_2026 = []
        if not all_db_stats.empty:
            wks_2026 = all_db_stats[all_db_stats['season'].astype(str) == '2026']['week'].astype(int).unique().tolist()
        elif df_nfl_stats is not None and not df_nfl_stats.empty:
            p_sub_wks = df_nfl_stats[df_nfl_stats['player_id'].astype(str) == pid_str]
            if not p_sub_wks.empty:
                wks_2026 = p_sub_wks['week'].astype(int).unique().tolist()

        for w_val in wks_2026:
            projs_raw = get_cached_or_live_projections(season="2026", week=w_val, db_path=db_path)
            if projs_raw and pid_str in projs_raw:
                p_pts = calculate_projected_points(projs_raw[pid_str], scoring_settings)
                proj_by_week[w_val] = round(float(p_pts), 1)

    p_matchups = df_matchups[df_matchups['player_id'].astype(str) == pid_str].copy() if df_matchups is not None and not df_matchups.empty else pd.DataFrame()
    matchup_by_week = {}
    if not p_matchups.empty:
        for _, mr in p_matchups.iterrows():
            w = int(mr['week'])
            matchup_by_week[w] = {
                'points': float(mr['points']),
                'started': int(mr.get('started', 0)),
                'team_name': mr.get('team_name', 'Free Agent')
            }

    weekly_records = []
    points_2026_list = []
    points_2025_list = []

    if not all_db_stats.empty:
        for _, sr in all_db_stats.iterrows():
            s = str(sr['season'])
            w = int(sr['week'])
            pts = float(sr['points']) if pd.notna(sr['points']) else 0.0
            row_team = resolve_nfl_team(sr.get('nfl_team'), fallback=nfl_team)
            bar_color = NFL_TEAM_COLORS.get(row_team, '#00338D')

            if s == '2026':
                points_2026_list.append(pts)
                week_label = f"Week {w}"
                m_info = matchup_by_week.get(w)
                if m_info:
                    f_status = "Starter" if m_info['started'] == 1 else "Bench"
                else:
                    f_status = "Free Agent" if team_name == "Free Agent" else "Rostered"
            else:
                points_2025_list.append(pts)
                week_label = f"'{s[-2:]} W{w}"
                f_status = f"{s} Season"

            p_proj = proj_by_week.get(w, 0.0) if s == '2026' else 0.0
            diff_proj = round(pts - p_proj, 1) if p_proj > 0 else 0.0

            weekly_records.append({
                'season': s,
                'week': w,
                'week_label': week_label,
                'nfl_team': row_team,
                'bar_color': bar_color,
                'points': pts,
                'projected_points': p_proj,
                'diff_vs_proj': diff_proj,
                'pass_yd': float(sr.get('pass_yd', 0.0)) if pd.notna(sr.get('pass_yd')) else 0.0,
                'pass_td': float(sr.get('pass_td', 0.0)) if pd.notna(sr.get('pass_td')) else 0.0,
                'pass_int': float(sr.get('pass_int', 0.0)) if pd.notna(sr.get('pass_int')) else 0.0,
                'rush_yd': float(sr.get('rush_yd', 0.0)) if pd.notna(sr.get('rush_yd')) else 0.0,
                'rush_td': float(sr.get('rush_td', 0.0)) if pd.notna(sr.get('rush_td')) else 0.0,
                'rec': float(sr.get('rec', 0.0)) if pd.notna(sr.get('rec')) else 0.0,
                'rec_yd': float(sr.get('rec_yd', 0.0)) if pd.notna(sr.get('rec_yd')) else 0.0,
                'rec_td': float(sr.get('rec_td', 0.0)) if pd.notna(sr.get('rec_td')) else 0.0,
                'fantasy_status': f_status
            })
    else:
        # Fallback to df_nfl_stats (current season only)
        p_stats = df_nfl_stats[df_nfl_stats['player_id'].astype(str) == pid_str].copy() if df_nfl_stats is not None and not df_nfl_stats.empty else pd.DataFrame()
        if not p_stats.empty:
            p_stats = p_stats.sort_values(by='week').reset_index(drop=True)
            for _, sr in p_stats.iterrows():
                w = int(sr['week'])
                pts = float(sr['points']) if pd.notna(sr['points']) else 0.0
                points_2026_list.append(pts)
                m_info = matchup_by_week.get(w)
                if m_info:
                    f_status = "Starter" if m_info['started'] == 1 else "Bench"
                else:
                    f_status = "Free Agent" if team_name == "Free Agent" else "Rostered"
                row_team = resolve_nfl_team(sr.get('nfl_team'), fallback=nfl_team)
                bar_color = NFL_TEAM_COLORS.get(row_team, '#00338D')
                p_proj = proj_by_week.get(w, 0.0)
                diff_proj = round(pts - p_proj, 1) if p_proj > 0 else 0.0

                weekly_records.append({
                    'season': '2026',
                    'week': w,
                    'week_label': f"Week {w}",
                    'nfl_team': row_team,
                    'bar_color': bar_color,
                    'points': pts,
                    'projected_points': p_proj,
                    'diff_vs_proj': diff_proj,
                    'pass_yd': float(sr.get('pass_yd', 0.0)) if pd.notna(sr.get('pass_yd')) else 0.0,
                    'pass_td': float(sr.get('pass_td', 0.0)) if pd.notna(sr.get('pass_td')) else 0.0,
                    'pass_int': float(sr.get('pass_int', 0.0)) if pd.notna(sr.get('pass_int')) else 0.0,
                    'rush_yd': float(sr.get('rush_yd', 0.0)) if pd.notna(sr.get('rush_yd')) else 0.0,
                    'rush_td': float(sr.get('rush_td', 0.0)) if pd.notna(sr.get('rush_td')) else 0.0,
                    'rec': float(sr.get('rec', 0.0)) if pd.notna(sr.get('rec')) else 0.0,
                    'rec_yd': float(sr.get('rec_yd', 0.0)) if pd.notna(sr.get('rec_yd')) else 0.0,
                    'rec_td': float(sr.get('rec_td', 0.0)) if pd.notna(sr.get('rec_td')) else 0.0,
                    'fantasy_status': f_status
                })

    df_weekly = pd.DataFrame(weekly_records) if weekly_records else pd.DataFrame(columns=['season', 'week', 'week_label', 'points', 'projected_points', 'diff_vs_proj', 'nfl_team', 'bar_color', 'fantasy_status'])

    # Projection Hit Rate Metrics (evaluated strictly for 2026 games where projection was available)
    eval_proj_games = [r for r in weekly_records if str(r.get('season')) == '2026' and float(r.get('projected_points', 0.0)) > 0]
    if eval_proj_games:
        proj_beat_count = sum(1 for r in eval_proj_games if r['points'] >= r['projected_points'])
        proj_total_games = len(eval_proj_games)
        proj_beat_pct = round((proj_beat_count / proj_total_games) * 100.0, 1)
        actual_sum = sum(r['points'] for r in eval_proj_games)
        proj_sum = sum(r['projected_points'] for r in eval_proj_games)
        proj_net_diff = round(actual_sum - proj_sum, 1)
        proj_avg_diff = round(proj_net_diff / proj_total_games, 1)
    else:
        proj_beat_count = 0
        proj_total_games = 0
        proj_beat_pct = 0.0
        proj_net_diff = 0.0
        proj_avg_diff = 0.0

    # Core Performance Metrics: Focus strictly on current 2026 season games
    points_list = points_2026_list if points_2026_list else (points_2025_list if points_2025_list else [0.0])
    games_played = len(points_2026_list) if points_2026_list else (len(points_list) if weekly_records else 0)
    total_points = round(float(sum(points_list)), 2)
    mean_points = round(float(np.mean(points_list)), 2) if points_list else 0.0
    std_points = round(float(np.std(points_list, ddof=1)), 2) if len(points_list) > 1 else 0.0
    floor_points = round(float(min(points_list)), 2) if points_list else 0.0
    ceiling_points = round(float(max(points_list)), 2) if points_list else 0.0
    median_points = round(float(np.median(points_list)), 2) if points_list else 0.0
    cv = round((std_points / mean_points), 2) if mean_points > 0 else 0.0

    # Multi-Season Historical Summary (e.g. 2025, 2024, etc.)
    mean_2025 = round(float(np.mean(points_2025_list)), 2) if points_2025_list else 0.0
    gp_2025 = len(points_2025_list)
    total_2025 = round(float(sum(points_2025_list)), 2) if points_2025_list else 0.0

    history_by_season = {}
    history_snippets = []
    if not df_weekly.empty:
        # Include current season 2026 and past seasons, sorted reverse chronologically
        all_seasons = sorted([s for s in df_weekly['season'].unique()], key=lambda x: int(x) if str(x).isdigit() else 0, reverse=True)
        for s_val in all_seasons:
            s_rows = df_weekly[df_weekly['season'] == s_val]
            s_pts = s_rows['points'].tolist()
            if s_pts:
                s_mean = round(float(np.mean(s_pts)), 1)
                s_gp = len(s_pts)
                history_by_season[str(s_val)] = {'mean': s_mean, 'gp': s_gp, 'total': round(float(sum(s_pts)), 1)}
                history_snippets.append(f"{s_val}: <strong>{s_mean:.1f} PPG</strong> ({s_gp} G)")
    history_summary_str = " • ".join(history_snippets)
    # Variance / Volatility Profile (based on standard deviation of weekly scores)
    if std_points < 4.5:
        consistency_tier = "🟢 Low Variance"
        consistency_desc = "Consistent weekly output (Std Dev < 4.5 FPTS)"
    elif std_points < 9.0:
        consistency_tier = "🟡 Moderate"
        consistency_desc = "Standard scoring spread (Std Dev 4.5–9.0 FPTS)"
    else:
        consistency_tier = "🔴 High Variance"
        consistency_desc = "Wide scoring spread (high ceiling, low floor)"

    # Health & Availability Assessment
    total_active_weeks = max(total_active_weeks, games_played)
    availability_pct = round((games_played / total_active_weeks) * 100, 1) if total_active_weeks > 0 else 0.0
    missed_games = max(0, total_active_weeks - games_played)

    if injury_status in ['IR', 'Out', 'PUP', 'Injured Reserve']:
        health_assessment = "🚨 Sidelined (Inactive / Injury Status)"
        health_color = "#dc2626"
        health_badge_bg = "#fee2e2"
    elif injury_status in ['Questionable', 'Doubtful', 'Probable']:
        health_assessment = f"⚠️ Injury Watch ({injury_status})"
        health_color = "#b45309"
        health_badge_bg = "#fef3c7"
    elif missed_games == 0:
        health_assessment = f"🛡️ 100% Availability ({games_played}/{total_active_weeks} Active Weeks)"
        health_color = "#16a34a"
        health_badge_bg = "#f0fdf4"
    elif missed_games == 1:
        health_assessment = f"✅ High Availability ({games_played}/{total_active_weeks} Active Weeks)"
        health_color = "#16a34a"
        health_badge_bg = "#f0fdf4"
    elif missed_games == 2:
        health_assessment = f"⚠️ Moderate Absence ({missed_games} Missed of {total_active_weeks} Weeks)"
        health_color = "#b45309"
        health_badge_bg = "#fef3c7"
    else:
        health_assessment = f"🚨 Low Availability ({missed_games} Missed of {total_active_weeks} Weeks)"
        health_color = "#dc2626"
        health_badge_bg = "#fee2e2"

    # Pos Rank
    pos_rank = int(p_row.get('pos_rank', 99)) if pd.notna(p_row.get('pos_rank')) else 99

    # Dynamic Trade Value calculation for unrostered / free agent players (or when val_df lookup misses)
    if trade_value <= 0.0 and mean_points > 0:
        rep_baselines = {'QB': 14.5, 'RB': 7.5, 'WR': 8.0, 'TE': 5.5, 'K': 6.5, 'DEF': 5.5}
        sc_weights = {'RB': 1.45, 'WR': 1.30, 'TE': 1.35, 'QB': 0.85, 'K': 0.30, 'DEF': 0.40}
        baseline = rep_baselines.get(position, 8.0)
        scarcity_weight = sc_weights.get(position, 1.0)
        vorp = max(0.0, round(mean_points - baseline, 1))

        elite_multiplier = 1.00
        if position in ["RB", "WR"]:
            if pos_rank <= 3: elite_multiplier = 1.35
            elif pos_rank <= 6: elite_multiplier = 1.22
            elif pos_rank <= 12: elite_multiplier = 1.12
            elif pos_rank <= 20: elite_multiplier = 1.05
        elif position == "TE":
            if pos_rank <= 2: elite_multiplier = 1.40
            elif pos_rank <= 5: elite_multiplier = 1.20
        elif position == "QB":
            if pos_rank <= 2: elite_multiplier = 1.25
            elif pos_rank <= 5: elite_multiplier = 1.10

        injury_discount = 1.00
        if injury_status in ["Out", "IR", "PUP", "Doubtful", "NA", "Sus"]:
            injury_discount = 0.60
        elif injury_status == "Questionable":
            injury_discount = 0.90

        raw_trade_value = ((vorp * 3.5 * scarcity_weight) + (mean_points * 1.1 * scarcity_weight)) * elite_multiplier * injury_discount
        max_benchmark = 125.0
        if val_df is not None and not val_df.empty and 'raw_trade_value' in val_df.columns:
            max_benchmark = max(float(val_df['raw_trade_value'].max()), 1.0)
        trade_value = round(min(98.0, max(1.0, (raw_trade_value / max_benchmark) * 98.0)), 1)

    # Best and Worst game (Current Season 2026 vs Career)
    best_week = None
    best_pts = None
    best_season = '2026'
    worst_week = None
    worst_pts = None
    career_best_str = ""

    df_2026_w = df_weekly[df_weekly['season'].astype(str) == '2026'] if not df_weekly.empty else pd.DataFrame()
    if not df_2026_w.empty:
        best_2026_row = df_2026_w.sort_values(by='points', ascending=False).iloc[0]
        best_week = int(best_2026_row['week'])
        best_pts = float(best_2026_row['points'])
        best_season = '2026'
        worst_2026_row = df_2026_w.sort_values(by='points', ascending=True).iloc[0]
        worst_week = int(worst_2026_row['week'])
        worst_pts = float(worst_2026_row['points'])
    elif not df_weekly.empty:
        best_row = df_weekly.sort_values(by='points', ascending=False).iloc[0]
        best_week = int(best_row['week'])
        best_pts = float(best_row['points'])
        best_season = str(best_row['season'])
        worst_row = df_weekly.sort_values(by='points', ascending=True).iloc[0]
        worst_week = int(worst_row['week'])
        worst_pts = float(worst_row['points'])

    if not df_weekly.empty and best_pts is not None:
        career_best_row = df_weekly.sort_values(by='points', ascending=False).iloc[0]
        c_pts = float(career_best_row['points'])
        c_wk = int(career_best_row['week'])
        c_season = str(career_best_row['season'])
        if c_pts > best_pts:
            career_best_str = f" <span style='font-size:0.68rem; color:#64748b;'>• Career: {c_pts:.1f} ('{c_season[-2:]} W{c_wk})</span>" 

    # Totals for stat categories
    tot_pass_yd = float(df_weekly['pass_yd'].sum()) if 'pass_yd' in df_weekly.columns else 0.0
    tot_pass_td = float(df_weekly['pass_td'].sum()) if 'pass_td' in df_weekly.columns else 0.0
    tot_pass_int = float(df_weekly['pass_int'].sum()) if 'pass_int' in df_weekly.columns else 0.0
    tot_rush_yd = float(df_weekly['rush_yd'].sum()) if 'rush_yd' in df_weekly.columns else 0.0
    tot_rush_td = float(df_weekly['rush_td'].sum()) if 'rush_td' in df_weekly.columns else 0.0
    tot_rec = float(df_weekly['rec'].sum()) if 'rec' in df_weekly.columns else 0.0
    tot_rec_yd = float(df_weekly['rec_yd'].sum()) if 'rec_yd' in df_weekly.columns else 0.0
    tot_rec_td = float(df_weekly['rec_td'].sum()) if 'rec_td' in df_weekly.columns else 0.0

    age_val = int(p_row.get('age')) if pd.notna(p_row.get('age')) and p_row.get('age') else None
    exp_val = int(p_row.get('years_exp')) if pd.notna(p_row.get('years_exp')) and p_row.get('years_exp') is not None else None

    return PlayerProfile(
        player_id=pid_str,
        player_name=player_name,
        position=position,
        nfl_team=nfl_team,
        owner_name=owner_name,
        team_name=team_name,
        headshot_url=headshot_url,
        injury_status=injury_status,
        age=age_val,
        years_exp=exp_val,
        games_played=games_played,
        total_active_weeks=total_active_weeks,
        missed_games=missed_games,
        availability_pct=availability_pct,
        health_assessment=health_assessment,
        health_color=health_color,
        health_badge_bg=health_badge_bg,
        mean_points=mean_points,
        std_points=std_points,
        cv=cv,
        consistency_tier=consistency_tier,
        consistency_desc=consistency_desc,
        floor_points=floor_points,
        ceiling_points=ceiling_points,
        median_points=median_points,
        total_points=total_points,
        pos_rank=pos_rank,
        trade_value=trade_value,
        weekly_df=df_weekly,
        best_week=best_week,
        best_pts=best_pts,
        best_season=best_season,
        worst_week=worst_week,
        worst_pts=worst_pts,
        career_best_str=career_best_str,
        tot_pass_yd=tot_pass_yd,
        tot_pass_td=tot_pass_td,
        tot_pass_int=tot_pass_int,
        tot_rush_yd=tot_rush_yd,
        tot_rush_td=tot_rush_td,
        tot_rec=tot_rec,
        tot_rec_yd=tot_rec_yd,
        tot_rec_td=tot_rec_td,
        baseline=baseline,
        vorp=vorp,
        scarcity_weight=scarcity_weight,
        elite_multiplier=elite_multiplier,
        injury_discount=injury_discount,
        raw_trade_value=raw_trade_value,
        mean_2025=mean_2025,
        gp_2025=gp_2025,
        total_2025=total_2025,
        history_by_season=history_by_season,
        history_summary_str=history_summary_str,
        proj_beat_count=proj_beat_count,
        proj_total_games=proj_total_games,
        proj_beat_pct=proj_beat_pct,
        proj_net_diff=proj_net_diff,
        proj_avg_diff=proj_avg_diff,
        team_color=NFL_TEAM_COLORS.get(nfl_team.upper(), '#00338D'),
    )


def get_player_comparison_analytics(
    player_a_id: str,
    player_b_id: str,
    df_player_stats: pd.DataFrame,
    df_nfl_stats: pd.DataFrame,
    df_matchups: pd.DataFrame,
    df_rosters: pd.DataFrame,
    val_df: Optional[pd.DataFrame] = None,
    db_path: Optional[str] = None
) -> Optional[PlayerComparison]:
    """
    Compute head-to-head statistical comparison between two players:
    - Weekly scoring matchup record (head-to-head differential)
    - Side-by-side metric comparison table with advantage indicators
    - Deterministic statistical comparison summary
    - Grouped comparison weekly dataframe
    """
    data_a = get_player_detailed_analytics(player_a_id, df_player_stats, df_nfl_stats, df_matchups, df_rosters, val_df, db_path)
    data_b = get_player_detailed_analytics(player_b_id, df_player_stats, df_nfl_stats, df_matchups, df_rosters, val_df, db_path)

    if not data_a or not data_b:
        return None

    # Filter strictly to current 2026 regular season games for head-to-head comparison
    df_cur_a = data_a['weekly_df'][data_a['weekly_df']['season'].astype(str) == '2026'].copy() if not data_a['weekly_df'].empty else pd.DataFrame()
    df_cur_b = data_b['weekly_df'][data_b['weekly_df']['season'].astype(str) == '2026'].copy() if not data_b['weekly_df'].empty else pd.DataFrame()

    weeks_a = set(df_cur_a['week']) if not df_cur_a.empty else set()
    weeks_b = set(df_cur_b['week']) if not df_cur_b.empty else set()
    all_weeks = sorted(list(weeks_a.union(weeks_b)))
    if not all_weeks:
        all_weeks = [1, 2, 3, 4]

    pts_map_a = dict(zip(df_cur_a['week'], df_cur_a['points'])) if not df_cur_a.empty else {}
    pts_map_b = dict(zip(df_cur_b['week'], df_cur_b['points'])) if not df_cur_b.empty else {}

    h2h_rows = []
    wins_a = 0
    wins_b = 0
    ties = 0

    combined_chart_rows = []

    for w in all_weeks:
        pa = pts_map_a.get(w, 0.0)
        pb = pts_map_b.get(w, 0.0)

        if pa > pb:
            winner = data_a['player_name']
            winner_key = 'A'
            wins_a += 1
            margin = pa - pb
        elif pb > pa:
            winner = data_b['player_name']
            winner_key = 'B'
            wins_b += 1
            margin = pb - pa
        else:
            winner = "Tie"
            winner_key = 'Tie'
            ties += 1
            margin = 0.0

        h2h_rows.append({
            'week': w,
            'week_label': f"Week {w}",
            'pts_a': pa,
            'pts_b': pb,
            'winner': winner,
            'winner_key': winner_key,
            'margin': round(margin, 1)
        })

        combined_chart_rows.append({
            'week': w,
            'week_label': f"Week {w}",
            'player_name': data_a['player_name'],
            'points': pa,
            'position': data_a['position'],
            'nfl_team': data_a['nfl_team']
        })
        combined_chart_rows.append({
            'week': w,
            'week_label': f"Week {w}",
            'player_name': data_b['player_name'],
            'points': pb,
            'position': data_b['position'],
            'nfl_team': data_b['nfl_team']
        })

    df_combined_chart = pd.DataFrame(combined_chart_rows)
    df_h2h = pd.DataFrame(h2h_rows)

    # Metric Comparison Matrix
    metrics_comp = []

    # 1. Season PPG (higher is better)
    ppg_a = data_a['mean_points']
    ppg_b = data_b['mean_points']
    w_ppg = 'A' if ppg_a > ppg_b else ('B' if ppg_b > ppg_a else 'Tie')
    metrics_comp.append({
        'metric': 'Season Average (PPG)',
        'val_a': f"{ppg_a:.2f} FPTS",
        'val_b': f"{ppg_b:.2f} FPTS",
        'winner': w_ppg,
        'diff': f"+{abs(ppg_a - ppg_b):.2f}"
    })

    # 2. Consistency / Std Dev (lower is better)
    sd_a = data_a['std_points']
    sd_b = data_b['std_points']
    w_sd = 'A' if sd_a < sd_b else ('B' if sd_b < sd_a else 'Tie')
    metrics_comp.append({
        'metric': 'Scoring Variance (Std Dev)',
        'val_a': f"±{sd_a:.2f} FPTS",
        'val_b': f"±{sd_b:.2f} FPTS",
        'winner': w_sd,
        'diff': f"{abs(sd_a - sd_b):.2f} SD"
    })

    # 3. Variance Profile
    metrics_comp.append({
        'metric': 'Variance Category',
        'val_a': data_a['consistency_tier'],
        'val_b': data_b['consistency_tier'],
        'winner': w_sd,
        'diff': '—'
    })

    # 4. Availability & Active Games (higher is better)
    av_a = data_a['availability_pct']
    av_b = data_b['availability_pct']
    w_av = 'A' if av_a > av_b else ('B' if av_b > av_a else 'Tie')
    metrics_comp.append({
        'metric': 'Season Availability (% Active)',
        'val_a': f"{av_a:.1f}% ({data_a['games_played']}/{data_a['total_active_weeks']} Wks)",
        'val_b': f"{av_b:.1f}% ({data_b['games_played']}/{data_b['total_active_weeks']} Wks)",
        'winner': w_av,
        'diff': f"{abs(av_a - av_b):.1f}%"
    })

    # Projection Beat Rate (higher is better)
    if data_a.get('proj_total_games', 0) > 0 or data_b.get('proj_total_games', 0) > 0:
        bp_a = data_a.get('proj_beat_pct', 0.0)
        bp_b = data_b.get('proj_beat_pct', 0.0)
        w_bp = 'A' if bp_a > bp_b else ('B' if bp_b > bp_a else 'Tie')
        metrics_comp.append({
            'metric': 'Projection Beat Rate (% Games)',
            'val_a': f"{bp_a:.0f}% ({data_a.get('proj_beat_count',0)}/{data_a.get('proj_total_games',0)} G)",
            'val_b': f"{bp_b:.0f}% ({data_b.get('proj_beat_count',0)}/{data_b.get('proj_total_games',0)} G)",
            'winner': w_bp,
            'diff': f"{abs(bp_a - bp_b):.0f}%"
        })

    # 5. Weekly Ceiling (Max points - higher is better)
    ceil_a = data_a['ceiling_points']
    ceil_b = data_b['ceiling_points']
    w_ceil = 'A' if ceil_a > ceil_b else ('B' if ceil_b > ceil_a else 'Tie')
    metrics_comp.append({
        'metric': 'Peak Score (Season High)',
        'val_a': f"{ceil_a:.1f} FPTS",
        'val_b': f"{ceil_b:.1f} FPTS",
        'winner': w_ceil,
        'diff': f"+{abs(ceil_a - ceil_b):.1f}"
    })

    # 6. Weekly Floor (Min points - higher is better)
    flr_a = data_a['floor_points']
    flr_b = data_b['floor_points']
    w_flr = 'A' if flr_a > flr_b else ('B' if flr_b > flr_a else 'Tie')
    metrics_comp.append({
        'metric': 'Floor Score (Season Low)',
        'val_a': f"{flr_a:.1f} FPTS",
        'val_b': f"{flr_b:.1f} FPTS",
        'winner': w_flr,
        'diff': f"+{abs(flr_a - flr_b):.1f}"
    })

    # 7. Positional Rank (lower number is better)
    rk_a = data_a['pos_rank']
    rk_b = data_b['pos_rank']
    w_rk = 'A' if rk_a < rk_b else ('B' if rk_b < rk_a else 'Tie')
    metrics_comp.append({
        'metric': 'Positional Rank',
        'val_a': f"#{rk_a} {data_a['position']}",
        'val_b': f"#{rk_b} {data_b['position']}",
        'winner': w_rk,
        'diff': f"Δ{abs(rk_a - rk_b)}"
    })

    # 8. Trade Market Value (higher is better)
    tv_a = data_a['trade_value']
    tv_b = data_b['trade_value']
    w_tv = 'A' if tv_a > tv_b else ('B' if tv_b > tv_a else 'Tie')
    metrics_comp.append({
        'metric': 'Trade Value (VORP Model)',
        'val_a': f"{tv_a:.1f} TV",
        'val_b': f"{tv_b:.1f} TV",
        'winner': w_tv,
        'diff': f"+{abs(tv_a - tv_b):.1f}"
    })

    # 9. Total Fantasy Points (higher is better)
    tot_a = data_a['total_points']
    tot_b = data_b['total_points']
    w_tot = 'A' if tot_a > tot_b else ('B' if tot_b > tot_a else 'Tie')
    metrics_comp.append({
        'metric': 'Total Fantasy Points',
        'val_a': f"{tot_a:.1f} FPTS",
        'val_b': f"{tot_b:.1f} FPTS",
        'winner': w_tot,
        'diff': f"+{abs(tot_a - tot_b):.1f}"
    })

    # Deterministic Metric Comparison & Statistical Summary
    verdict_bullets = []

    # Scoring edge
    if abs(ppg_a - ppg_b) >= 2.0:
        higher_scorer = data_a['player_name'] if ppg_a > ppg_b else data_b['player_name']
        diff_ppg = abs(ppg_a - ppg_b)
        verdict_bullets.append(f"<strong>Scoring Advantage:</strong> {higher_scorer} holds an edge of <strong>+{diff_ppg:.1f} PPG</strong>.")
    elif abs(ppg_a - ppg_b) >= 0.5:
        higher_scorer = data_a['player_name'] if ppg_a > ppg_b else data_b['player_name']
        diff_ppg = abs(ppg_a - ppg_b)
        verdict_bullets.append(f"<strong>Scoring Edge:</strong> {higher_scorer} slightly edges out with <strong>+{diff_ppg:.1f} PPG</strong>.")
    else:
        verdict_bullets.append("<strong>Scoring Parity:</strong> Both players offer virtually identical average weekly scoring output.")

    # Consistency / Variance edge
    if abs(sd_a - sd_b) >= 2.5:
        more_consistent = data_a['player_name'] if sd_a < sd_b else data_b['player_name']
        diff_sd = abs(sd_a - sd_b)
        verdict_bullets.append(f"<strong>Lower Volatility:</strong> {more_consistent} provides more consistent week-to-week scoring (±{min(sd_a, sd_b):.1f} vs ±{max(sd_a, sd_b):.1f} SD, a {diff_sd:.1f} point variance advantage).")
    elif abs(sd_a - sd_b) >= 1.0:
        more_consistent = data_a['player_name'] if sd_a < sd_b else data_b['player_name']
        verdict_bullets.append(f"<strong>Variance Advantage:</strong> {more_consistent} offers lower scoring dispersion week-to-week.")

    # Ceiling edge
    if abs(ceil_a - ceil_b) >= 5.0:
        high_upside = data_a['player_name'] if ceil_a > ceil_b else data_b['player_name']
        diff_ceil = abs(ceil_a - ceil_b)
        verdict_bullets.append(f"<strong>Peak Upside:</strong> {high_upside} has demonstrated higher peak scoring ({max(ceil_a, ceil_b):.1f} max FPTS vs {min(ceil_a, ceil_b):.1f} FPTS, +{diff_ceil:.1f} peak).")

    # Availability / Health edge
    if av_a != av_b:
        durable = data_a['player_name'] if av_a > av_b else data_b['player_name']
        fragile = data_b['player_name'] if av_a > av_b else data_a['player_name']
        verdict_bullets.append(f"<strong>Availability:</strong> {durable} ({max(av_a, av_b):.0f}% availability) has played more games than {fragile} ({min(av_a, av_b):.0f}% availability, {abs(data_a['missed_games'] - data_b['missed_games'])} fewer missed games).")
    else:
        verdict_bullets.append(f"<strong>Availability Parity:</strong> Both players have played the exact same number of games ({data_a['games_played']} games, {av_a:.0f}% availability).")

    # Statistical Summary Note
    if ppg_a > ppg_b and sd_a <= sd_b:
        rec_text = f"Statistical Edge: <strong>{data_a['player_name']}</strong> leads in both average scoring (+{abs(ppg_a - ppg_b):.1f} PPG) and lower weekly variance."
    elif ppg_b > ppg_a and sd_b <= sd_a:
        rec_text = f"Statistical Edge: <strong>{data_b['player_name']}</strong> leads in both average scoring (+{abs(ppg_a - ppg_b):.1f} PPG) and lower weekly variance."
    elif ppg_a > ppg_b:
        rec_text = f"Tradeoff: <strong>{data_a['player_name']}</strong> provides higher average scoring (+{abs(ppg_a - ppg_b):.1f} PPG), while <strong>{data_b['player_name']}</strong> offers lower variance and higher floor."
    else:
        rec_text = f"Tradeoff: <strong>{data_b['player_name']}</strong> provides higher average scoring (+{abs(ppg_a - ppg_b):.1f} PPG), while <strong>{data_a['player_name']}</strong> offers lower variance and higher floor."

    return PlayerComparison(
        player_a=data_a,
        player_b=data_b,
        h2h_df=df_h2h,
        wins_a=wins_a,
        wins_b=wins_b,
        ties=ties,
        metrics_comp=metrics_comp,
        verdict_bullets=verdict_bullets,
        recommendation=rec_text,
        combined_chart_df=df_combined_chart
    )


# ==============================================================================
# PRESENTATION & VIEW LAYER EXPORTS (Separation of Concerns)
# ==============================================================================
from src.views_players import (
    render_player_profile_view,
    render_player_comparison_view,
    _build_profile_header_html,
    _build_profile_kpi_html,
    _build_chart_header_html,
    _build_profile_log_table_html,
    _build_comp_headers_html,
    _build_comp_banner_html,
    _build_comp_verdict_html,
    _build_comp_tape_html,
    _build_comp_chart_header,
    _build_comp_h2h_table,
)

# Domain aliases for clean API nomenclature
get_player_profile = get_player_detailed_analytics
compare_players = get_player_comparison_analytics
