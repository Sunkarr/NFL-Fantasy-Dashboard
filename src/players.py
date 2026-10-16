import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Tuple
import sqlite3
from pathlib import Path
from src.config import TEAM_PALETTE, FREE_AGENT_COLOR, NFL_TEAM_COLORS, NFL_TEAM_NAMES

def resolve_nfl_team(val: Any, fallback: str = "FA") -> str:
    """Safely resolve NFL franchise abbreviation without NaN / None / 'nan' strings."""
    if val is None or pd.isna(val):
        candidate = str(fallback or "FA").strip().upper()
    else:
        candidate = str(val).strip().upper()
    if not candidate or candidate in ("NAN", "NONE", "NULL", "FA", ""):
        candidate = str(fallback or "FA").strip().upper()
    if not candidate or candidate in ("NAN", "NONE", "NULL", ""):
        return "FA"
    return candidate



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


def get_player_detailed_analytics(
    player_id: str,
    df_player_stats: pd.DataFrame,
    df_nfl_stats: pd.DataFrame,
    df_matchups: pd.DataFrame,
    df_rosters: pd.DataFrame,
    val_df: Optional[pd.DataFrame] = None,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Extract comprehensive player analytics:
    - Metadata (Name, Position, NFL Team, Owner, Headshot, Age, Experience)
    - Current Health & Durability Score (% games played, active injury status)
    - Scoring profile (PPG, Std Dev, Consistency Tier, Floor, Ceiling, Median, Total Points)
    - Market Trade Value (0-100 scale)
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
                    f_status = "Started" if m_info['started'] == 1 else "Bench"
                else:
                    f_status = "Free Agent" if team_name == "Free Agent" else "Rostered"
            else:
                points_2025_list.append(pts)
                week_label = f"'{s[-2:]} W{w}"
                f_status = f"{s} Season"

            weekly_records.append({
                'season': s,
                'week': w,
                'week_label': week_label,
                'nfl_team': row_team,
                'bar_color': bar_color,
                'points': pts,
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
                    f_status = "Started" if m_info['started'] == 1 else "Bench"
                else:
                    f_status = "Free Agent" if team_name == "Free Agent" else "Rostered"
                row_team = resolve_nfl_team(sr.get('nfl_team'), fallback=nfl_team)
                bar_color = NFL_TEAM_COLORS.get(row_team, '#00338D')
                weekly_records.append({
                    'season': '2026',
                    'week': w,
                    'week_label': f"Week {w}",
                    'nfl_team': row_team,
                    'bar_color': bar_color,
                    'points': pts,
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

    df_weekly = pd.DataFrame(weekly_records) if weekly_records else pd.DataFrame(columns=['season', 'week', 'week_label', 'points', 'nfl_team', 'bar_color', 'fantasy_status'])

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
        past_seasons = sorted([s for s in df_weekly['season'].unique() if str(s) != '2026'], reverse=True)
        for s_val in past_seasons:
            s_rows = df_weekly[df_weekly['season'] == s_val]
            s_pts = s_rows['points'].tolist()
            if s_pts:
                s_mean = round(float(np.mean(s_pts)), 1)
                s_gp = len(s_pts)
                history_by_season[str(s_val)] = {'mean': s_mean, 'gp': s_gp, 'total': round(float(sum(s_pts)), 1)}
                history_snippets.append(f"{s_val}: <strong>{s_mean:.1f} PPG</strong> ({s_gp} G)")
    history_summary_str = " • ".join(history_snippets)
    # Consistency Tier
    if std_points < 4.5:
        consistency_tier = "🟢 Rock Solid"
        consistency_desc = "Highly predictable scoring week-to-week"
    elif std_points < 9.0:
        consistency_tier = "🟡 Moderate"
        consistency_desc = "Standard fantasy volatility with steady baseline"
    else:
        consistency_tier = "🔴 Boom / Bust"
        consistency_desc = "Extreme scoring variance (high ceiling, low floor)"

    # Health & Availability Assessment
    total_active_weeks = max(total_active_weeks, games_played)
    availability_pct = round((games_played / total_active_weeks) * 100, 1) if total_active_weeks > 0 else 0.0
    missed_games = max(0, total_active_weeks - games_played)

    if injury_status in ['IR', 'Out', 'PUP', 'Injured Reserve']:
        health_assessment = "🚨 Currently Sidelined (Inactive / Injured)"
        health_color = "#dc2626"
        health_badge_bg = "#fee2e2"
    elif injury_status in ['Questionable', 'Doubtful', 'Probable']:
        health_assessment = "⚠️ Active Concern (Injury Risk for Next Matchup)"
        health_color = "#b45309"
        health_badge_bg = "#fef3c7"
    elif missed_games == 0:
        health_assessment = "🛡️ Ironman (100% Season Availability - High Durability)"
        health_color = "#16a34a"
        health_badge_bg = "#f0fdf4"
    elif missed_games == 1:
        health_assessment = f"✅ High Durability (Missed only 1 of {total_active_weeks} weeks)"
        health_color = "#16a34a"
        health_badge_bg = "#f0fdf4"
    elif missed_games == 2:
        health_assessment = f"⚠️ Moderate Risk (Missed 2 of {total_active_weeks} weeks)"
        health_color = "#b45309"
        health_badge_bg = "#fef3c7"
    else:
        health_assessment = f"🚨 High Absence History (Missed {missed_games} of {total_active_weeks} weeks)"
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

    # Best and Worst game
    best_week = None
    best_pts = None
    worst_week = None
    worst_pts = None
    if not df_weekly.empty:
        best_row = df_weekly.sort_values(by='points', ascending=False).iloc[0]
        worst_row = df_weekly.sort_values(by='points', ascending=True).iloc[0]
        best_week = int(best_row['week'])
        best_pts = float(best_row['points'])
        worst_week = int(worst_row['week'])
        worst_pts = float(worst_row['points'])

    # Totals for stat categories
    tot_pass_yd = float(df_weekly['pass_yd'].sum()) if 'pass_yd' in df_weekly.columns else 0.0
    tot_pass_td = float(df_weekly['pass_td'].sum()) if 'pass_td' in df_weekly.columns else 0.0
    tot_pass_int = float(df_weekly['pass_int'].sum()) if 'pass_int' in df_weekly.columns else 0.0
    tot_rush_yd = float(df_weekly['rush_yd'].sum()) if 'rush_yd' in df_weekly.columns else 0.0
    tot_rush_td = float(df_weekly['rush_td'].sum()) if 'rush_td' in df_weekly.columns else 0.0
    tot_rec = float(df_weekly['rec'].sum()) if 'rec' in df_weekly.columns else 0.0
    tot_rec_yd = float(df_weekly['rec_yd'].sum()) if 'rec_yd' in df_weekly.columns else 0.0
    tot_rec_td = float(df_weekly['rec_td'].sum()) if 'rec_td' in df_weekly.columns else 0.0

    return {
        'player_id': pid_str,
        'player_name': player_name,
        'position': position,
        'nfl_team': nfl_team,
        'owner_name': owner_name,
        'team_name': team_name,
        'headshot_url': headshot_url,
        'injury_status': injury_status,
        'age': p_row.get('age'),
        'years_exp': p_row.get('years_exp'),
        'games_played': games_played,
        'total_active_weeks': total_active_weeks,
        'missed_games': missed_games,
        'availability_pct': availability_pct,
        'health_assessment': health_assessment,
        'health_color': health_color,
        'health_badge_bg': health_badge_bg,
        'mean_points': mean_points,
        'std_points': std_points,
        'cv': cv,
        'consistency_tier': consistency_tier,
        'consistency_desc': consistency_desc,
        'floor_points': floor_points,
        'ceiling_points': ceiling_points,
        'median_points': median_points,
        'total_points': total_points,
        'pos_rank': pos_rank,
        'trade_value': trade_value,
        'weekly_df': df_weekly,
        'best_week': best_week,
        'best_pts': best_pts,
        'worst_week': worst_week,
        'worst_pts': worst_pts,
        'tot_pass_yd': tot_pass_yd,
        'tot_pass_td': tot_pass_td,
        'tot_pass_int': tot_pass_int,
        'tot_rush_yd': tot_rush_yd,
        'tot_rush_td': tot_rush_td,
        'tot_rec': tot_rec,
        'tot_rec_yd': tot_rec_yd,
        'tot_rec_td': tot_rec_td,
        'baseline': baseline,
        'vorp': vorp,
        'scarcity_weight': scarcity_weight,
        'elite_multiplier': elite_multiplier,
        'injury_discount': injury_discount,
        'raw_trade_value': raw_trade_value,
        'mean_2025': mean_2025,
        'gp_2025': gp_2025,
        'total_2025': total_2025,
        'history_by_season': history_by_season,
        'history_summary_str': history_summary_str,
        'team_color': NFL_TEAM_COLORS.get(nfl_team.upper(), '#00338D'),
    }


def get_player_comparison_analytics(
    player_a_id: str,
    player_b_id: str,
    df_player_stats: pd.DataFrame,
    df_nfl_stats: pd.DataFrame,
    df_matchups: pd.DataFrame,
    df_rosters: pd.DataFrame,
    val_df: Optional[pd.DataFrame] = None,
    db_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Compute head-to-head comparison analytics between two players:
    - Weekly head-to-head game match record (who won which week)
    - Side-by-side metric table with highlighted winner
    - Automated Verdict & Executive Recommendation
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
        'metric': 'Volatility / Std Dev (Lower is Safer)',
        'val_a': f"±{sd_a:.2f} FPTS",
        'val_b': f"±{sd_b:.2f} FPTS",
        'winner': w_sd,
        'diff': f"{abs(sd_a - sd_b):.2f} SD"
    })

    # 3. Consistency Tier
    metrics_comp.append({
        'metric': 'Consistency Profile',
        'val_a': data_a['consistency_tier'],
        'val_b': data_b['consistency_tier'],
        'winner': w_sd,
        'diff': '—'
    })

    # 4. Availability & Health (higher is better)
    av_a = data_a['availability_pct']
    av_b = data_b['availability_pct']
    w_av = 'A' if av_a > av_b else ('B' if av_b > av_a else 'Tie')
    metrics_comp.append({
        'metric': 'Season Availability (% Played)',
        'val_a': f"{av_a:.1f}% ({data_a['games_played']}/{data_a['total_active_weeks']} Wks)",
        'val_b': f"{av_b:.1f}% ({data_b['games_played']}/{data_b['total_active_weeks']} Wks)",
        'winner': w_av,
        'diff': f"{abs(av_a - av_b):.1f}%"
    })

    # 5. Weekly Ceiling (Max points - higher is better)
    ceil_a = data_a['ceiling_points']
    ceil_b = data_b['ceiling_points']
    w_ceil = 'A' if ceil_a > ceil_b else ('B' if ceil_b > ceil_a else 'Tie')
    metrics_comp.append({
        'metric': 'Weekly Ceiling (Season High)',
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
        'metric': 'Weekly Floor (Season Low)',
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
        'metric': 'Market Trade Value (0-100 TV)',
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
        'metric': 'Cumulative Fantasy Output',
        'val_a': f"{tot_a:.1f} FPTS",
        'val_b': f"{tot_b:.1f} FPTS",
        'winner': w_tot,
        'diff': f"+{abs(tot_a - tot_b):.1f}"
    })

    # Automated AI / Analytical Verdict Formulation
    verdict_bullets = []

    # Scoring edge
    if abs(ppg_a - ppg_b) >= 2.0:
        higher_scorer = data_a['player_name'] if ppg_a > ppg_b else data_b['player_name']
        diff_ppg = abs(ppg_a - ppg_b)
        verdict_bullets.append(f"<strong>Scoring Dominance:</strong> {higher_scorer} holds a decisive scoring edge of <strong>+{diff_ppg:.1f} PPG</strong>.")
    elif abs(ppg_a - ppg_b) >= 0.5:
        higher_scorer = data_a['player_name'] if ppg_a > ppg_b else data_b['player_name']
        diff_ppg = abs(ppg_a - ppg_b)
        verdict_bullets.append(f"<strong>Scoring Edge:</strong> {higher_scorer} slightly edges out with <strong>+{diff_ppg:.1f} PPG</strong>.")
    else:
        verdict_bullets.append("<strong>Scoring Parity:</strong> Both players offer virtually identical average weekly scoring output.")

    # Consistency edge
    if abs(sd_a - sd_b) >= 2.5:
        more_consistent = data_a['player_name'] if sd_a < sd_b else data_b['player_name']
        diff_sd = abs(sd_a - sd_b)
        verdict_bullets.append(f"<strong>Stability Advantage:</strong> {more_consistent} provides much greater week-to-week predictability (±{min(sd_a, sd_b):.1f} vs ±{max(sd_a, sd_b):.1f} SD, a {diff_sd:.1f} point variance advantage).")
    elif abs(sd_a - sd_b) >= 1.0:
        more_consistent = data_a['player_name'] if sd_a < sd_b else data_b['player_name']
        verdict_bullets.append(f"<strong>Reliability:</strong> {more_consistent} offers a modestly safer floor with lower scoring deviation.")

    # Ceiling edge
    if abs(ceil_a - ceil_b) >= 5.0:
        high_upside = data_a['player_name'] if ceil_a > ceil_b else data_b['player_name']
        diff_ceil = abs(ceil_a - ceil_b)
        verdict_bullets.append(f"<strong>Tournament Upside:</strong> {high_upside} has demonstrated true game-breaking ceiling ({max(ceil_a, ceil_b):.1f} max FPTS vs {min(ceil_a, ceil_b):.1f} FPTS, +{diff_ceil:.1f} peak).")

    # Durability / Health edge
    if av_a != av_b:
        durable = data_a['player_name'] if av_a > av_b else data_b['player_name']
        fragile = data_b['player_name'] if av_a > av_b else data_a['player_name']
        verdict_bullets.append(f"<strong>Durability & Health:</strong> {durable} ({max(av_a, av_b):.0f}% availability) has proven more reliable than {fragile} ({min(av_a, av_b):.0f}% availability, {abs(data_a['missed_games'] - data_b['missed_games'])} more missed games).")
    else:
        verdict_bullets.append(f"<strong>Durability Parity:</strong> Both players have played the exact same number of games ({data_a['games_played']} games, {av_a:.0f}% availability).")

    # Recommendation
    if ppg_a > ppg_b and sd_a <= sd_b:
        rec_text = f"Clear Advantage: <strong>{data_a['player_name']}</strong> dominates in both raw scoring (+{abs(ppg_a - ppg_b):.1f} PPG) and consistency. He is the superior asset in starting lineups and trades."
    elif ppg_b > ppg_a and sd_b <= sd_a:
        rec_text = f"Clear Advantage: <strong>{data_b['player_name']}</strong> dominates in both raw scoring (+{abs(ppg_a - ppg_b):.1f} PPG) and consistency. He is the superior asset in starting lineups and trades."
    elif ppg_a > ppg_b:
        rec_text = f"Risk/Reward Tradeoff: <strong>{data_a['player_name']}</strong> provides higher scoring upside (+{abs(ppg_a - ppg_b):.1f} PPG), while <strong>{data_b['player_name']}</strong> offers greater safety and floor."
    else:
        rec_text = f"Risk/Reward Tradeoff: <strong>{data_b['player_name']}</strong> provides higher scoring upside (+{abs(ppg_a - ppg_b):.1f} PPG), while <strong>{data_a['player_name']}</strong> offers greater safety and floor."

    return {
        'player_a': data_a,
        'player_b': data_b,
        'h2h_df': df_h2h,
        'wins_a': wins_a,
        'wins_b': wins_b,
        'ties': ties,
        'metrics_comp': metrics_comp,
        'verdict_bullets': verdict_bullets,
        'recommendation': rec_text,
        'combined_chart_df': df_combined_chart
    }


def _build_profile_header_html(data: Dict[str, Any], owner_colors: Optional[Dict[str, str]] = None) -> str:
    pos_colors = {
        'QB': '#f43f5e',
        'RB': '#06b6d4',
        'WR': '#3b82f6',
        'TE': '#f59e0b',
        'K': '#a855f7',
        'DEF': '#64748b'
    }
    pos_color = pos_colors.get(data['position'], '#2563eb')
    owner_col = (owner_colors or {}).get(data['owner_name'], '#64748b')

    inj = data['injury_status']
    if inj == 'Healthy':
        inj_html = "<span style='display:inline-flex; align-items:center; gap:5px; background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:12px; padding:3px 10px; font-weight:700; font-size:0.75rem;'><span style='width:6px; height:6px; border-radius:50%; background:#22c55e;'></span>Active</span>"
    elif inj in ['Questionable', 'Probable']:
        inj_html = f"<span style='display:inline-flex; align-items:center; gap:5px; background:#fef3c7; border:1px solid #fde68a; color:#b45309; border-radius:12px; padding:3px 10px; font-weight:700; font-size:0.75rem;'><span style='width:6px; height:6px; border-radius:50%; background:#eab308;'></span>{inj}</span>"
    else:
        inj_html = f"<span style='display:inline-flex; align-items:center; gap:5px; background:#fee2e2; border:1px solid #fca5a5; color:#991b1b; border-radius:12px; padding:3px 10px; font-weight:700; font-size:0.75rem;'><span style='width:6px; height:6px; border-radius:50%; background:#ef4444;'></span>{inj}</span>"

    meta_parts = []
    if pd.notna(data.get('age')) and data['age']:
        meta_parts.append(f"Age {int(data['age'])}")
    if pd.notna(data.get('years_exp')) and data['years_exp'] is not None:
        exp = int(data['years_exp'])
        meta_parts.append("Rookie" if exp == 0 else f"{exp}y Exp")
    meta_str = " • ".join(meta_parts) if meta_parts else ""

    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:18px 22px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,0.03); font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:16px;'>
        <div style='display:flex; align-items:center; gap:18px;'>
            <img src='{data['headshot_url']}' style='width:68px; height:68px; border-radius:50%; object-fit:cover; background:#f1f5f9; border:2.5px solid {pos_color}; box-shadow:0 2px 8px rgba(0,0,0,0.08);' onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'" />
            <div>
                <div style='display:flex; align-items:center; gap:8px; flex-wrap:wrap;'>
                    <span style='font-size:1.45rem; font-weight:800; color:#0f172a;'>{data['player_name']}</span>
                    <span style='background:{pos_color}; color:#ffffff; font-weight:800; font-size:0.75rem; border-radius:6px; padding:3px 9px;'>{data['position']}</span>
                    <span style='background:#f1f5f9; color:#475569; font-weight:700; font-size:0.75rem; border-radius:6px; padding:3px 9px; border:1px solid #e2e8f0;'>{data['nfl_team']}</span>
                    {inj_html}
                </div>
                <div style='display:flex; align-items:center; gap:10px; margin-top:5px; font-size:0.8rem; color:#64748b;'>
                    <span style='display:inline-flex; align-items:center; gap:5px;'>
                        <span style='width:8px; height:8px; border-radius:50%; background:{owner_col};'></span>
                        <strong style='color:#334155;'>Owner:</strong> {data['owner_name']}
                    </span>
                    {f"<span>•</span><span>{meta_str}</span>" if meta_str else ""}
                    <span>•</span>
                    <span>Position Rank: <strong style='color:#1d4ed8;'>#{data['pos_rank']} {data['position']}</strong></span>
                </div>
            </div>
        </div>
        <div style='display:flex; align-items:center; gap:12px; flex-wrap:wrap;'>
            <!-- Trade Value Calculation Breakdown -->
            <div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:6px 12px; display:flex; align-items:center; gap:8px;'>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#64748b; text-transform:uppercase;'>PPG (Score)</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#0f172a;'>{data['mean_points']:.1f}</div>
                </div>
                <div style='color:#cbd5e1; font-weight:700; font-size:0.85rem;'>-</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#64748b; text-transform:uppercase;'>Baseline</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#64748b;'>{data.get('baseline', 8.0):.1f}</div>
                </div>
                <div style='color:#cbd5e1; font-weight:700; font-size:0.85rem;'>➔</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#059669; text-transform:uppercase;'>VORP</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#059669;'>+{data.get('vorp', 0.0):.1f}</div>
                </div>
                <div style='color:#cbd5e1; font-weight:700; font-size:0.85rem;'>×</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#64748b; text-transform:uppercase;'>Scarcity</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#0f172a;'>{data.get('scarcity_weight', 1.0):.2f}x</div>
                </div>
                <div style='color:#cbd5e1; font-weight:700; font-size:0.85rem;'>×</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#7c3aed; text-transform:uppercase;'>Tier Multi</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#7c3aed;'>{data.get('elite_multiplier', 1.0):.2f}x</div>
                </div>
                {f"<div style='color:#cbd5e1; font-weight:700; font-size:0.85rem;'>×</div><div style='text-align:center;'><div style='font-size:0.62rem; font-weight:700; color:#dc2626; text-transform:uppercase;'>Health</div><div style='font-size:0.95rem; font-weight:800; color:#dc2626;'>{data['injury_discount']:.2f}x</div></div>" if data.get('injury_discount', 1.0) < 1.0 else ""}
            </div>

            <!-- TV Badge -->
            <div style='background:#faf5ff; border:1px solid #e9d5ff; border-radius:10px; padding:8px 16px; text-align:right;'>
                <div style='font-size:0.68rem; color:#7c3aed; font-weight:700; text-transform:uppercase;'>Trade Value</div>
                <div style='font-size:1.35rem; font-weight:900; color:#6b21a8;'>{data['trade_value']:.1f} <span style='font-size:0.75rem; color:#a855f7; font-weight:600;'>TV</span></div>
            </div>
        </div>
        <div style='width:100%;'>
            <details style='font-size:0.78rem; color:#475569; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:8px 12px; cursor:pointer;'>
                <summary style='font-weight:700; color:#4f46e5; user-select:none;'>💡 Trade Value (TV) Formula & Calculation Breakdown (Click to expand)</summary>
                <div style='margin-top:8px; line-height:1.55; display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:10px; padding-top:6px; border-top:1px solid #e2e8f0;'>
                    <div>
                        <strong style='color:#0f172a;'>1. Baseline ({data.get('baseline', 8.0):.1f} FPTS):</strong><br/>
                        Waiver replacement baseline for {data['position']}. The scoring level freely available without trading.
                    </div>
                    <div>
                        <strong style='color:#059669;'>2. VORP (+{data.get('vorp', 0.0):.1f}):</strong><br/>
                        <em>Value Over Replacement</em> = PPG ({data['mean_points']:.1f}) - Baseline ({data.get('baseline', 8.0):.1f}). Real points gained over a waiver replacement.
                    </div>
                    <div>
                        <strong style='color:#0f172a;'>3. Scarcity ({data.get('scarcity_weight', 1.0):.2f}×):</strong><br/>
                        Positional scarcity factor. Premium RBs and WRs are much scarcer in fantasy drafts/trades than QBs and TEs.
                    </div>
                    <div>
                        <strong style='color:#7c3aed;'>4. Tier Multi ({data.get('elite_multiplier', 1.0):.2f}×):</strong><br/>
                        Superstar premium. Elite top-tier players single-handedly decide weekly fantasy matchups.
                    </div>
                </div>
                <div style='margin-top:8px; font-size:0.76rem; color:#334155; background:#eff6ff; padding:5px 10px; border-radius:6px; border-left:3px solid #3b82f6;'>
                    <strong>Calculation:</strong> {data['mean_points']:.1f} PPG - {data.get('baseline', 8.0):.1f} Base = +{data.get('vorp', 0.0):.1f} VORP × {data.get('scarcity_weight', 1.0):.2f} (Scarcity) × {data.get('elite_multiplier', 1.0):.2f} (Tier Multi) {f"× {data.get('injury_discount'):.2f} (Availability)" if data.get('injury_discount', 1.0) < 0.99 else ""} ➔ <strong>{data['trade_value']:.1f} Trade Value (0-100 Benchmark)</strong>
                </div>
            </details>
        </div>
    </div>
    """


def _build_profile_kpi_html(data: Dict[str, Any]) -> str:
    return f"""
    <div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:16px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'>
        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>⚡ Season PPG</div>
            <div style='font-size:1.45rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'>{data['mean_points']:.2f} <span style='font-size:0.8rem; font-weight:600; color:#64748b;'>FPTS</span></div>
            <div style='font-size:0.74rem; color:#1d4ed8; font-weight:700;'>#{data['pos_rank']} at {data['position']}</div>
        </div>

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>🎯 Consistency</div>
            <div style='font-size:1.25rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'>{data['consistency_tier']}</div>
            <div style='font-size:0.74rem; color:#64748b;'>Std Dev: <strong>±{data['std_points']:.1f} FPTS</strong></div>
        </div>

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>🩺 Health & Availability</div>
            <div style='font-size:1.45rem; font-weight:800; color:{data['health_color']}; margin:3px 0 1px 0;'>{data['availability_pct']:.0f}% <span style='font-size:0.8rem; font-weight:600; color:#94a3b8;'>({data['games_played']}/{data['total_active_weeks']} G)</span></div>
            <div style='font-size:0.72rem; color:{data['health_color']}; font-weight:600;'>{data['health_assessment']}</div>
        </div>

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>📈 Floor & Ceiling</div>
            <div style='font-size:1.2rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'><span style='color:#dc2626;'>{data['floor_points']:.1f}</span> — <span style='color:#16a34a;'>{data['ceiling_points']:.1f}</span></div>
            <div style='font-size:0.74rem; color:#64748b;'>Median: <strong>{data['median_points']:.1f} FPTS</strong></div>
        </div>

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>🏆 Cumulative Output</div>
            <div style='font-size:1.45rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'>{data['total_points']:.1f} <span style='font-size:0.8rem; font-weight:600; color:#64748b;'>FPTS</span></div>
            <div style='font-size:0.74rem; color:#64748b;'>Peak: <strong>{data['ceiling_points']:.1f}</strong> (Wk {data['best_week'] or 1})</div>
            {f"<div style='font-size:0.72rem; color:#475569; margin-top:3px; padding-top:3px; border-top:1px dashed #e2e8f0;'>History: {data['history_summary_str']}</div>" if data.get('history_summary_str') else ""}
        </div>

    </div>
    """


def _build_chart_header_html(data: Dict[str, Any]) -> str:
    df_w = data.get('weekly_df', pd.DataFrame())
    unique_teams = []
    if not df_w.empty and 'nfl_team' in df_w.columns:
        for t in df_w.sort_values(by=['season', 'week'], ascending=[False, False])['nfl_team'].dropna().unique():
            t_clean = resolve_nfl_team(t, fallback="")
            if t_clean and t_clean not in ('FA', '') and t_clean not in unique_teams:
                unique_teams.append(t_clean)

    curr_team = resolve_nfl_team(data.get('nfl_team'), fallback="")
    if curr_team and curr_team not in ('FA', '') and curr_team not in unique_teams:
        unique_teams.insert(0, curr_team)

    if not unique_teams and curr_team:
        unique_teams = [curr_team]

    team_badges = []
    for t_code in unique_teams:
        t_col = NFL_TEAM_COLORS.get(t_code, '#00338D')
        t_full = NFL_TEAM_NAMES.get(t_code, t_code)
        team_badges.append(
            f"<span style='display:inline-flex; align-items:center; gap:5px; font-size:0.75rem; color:#475569; font-weight:600;'><span style='display:inline-block; width:10px; height:10px; background:{t_col}; border-radius:2px;'></span> {t_full}</span>"
        )
    team_badges_html = " ".join(team_badges)

    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px 14px 0 0; padding:12px 18px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;'>
        <div style='display:flex; align-items:center; gap:12px; flex-wrap:wrap;'>
            <span style='font-weight:800; font-size:0.96rem; color:#0f172a;'>📊 Weekly Game Logs & Multi-Season History</span>
            <span style='display:inline-flex; align-items:center; gap:5px; font-size:0.75rem; color:#dc2626; font-weight:700;'><span style='display:inline-block; width:14px; height:2px; background:#dc2626; border-top:2px dashed #dc2626;'></span> 2026 Avg: {data['mean_points']:.1f} FPTS</span>
            {team_badges_html}
        </div>
        <div style='font-size:0.74rem; color:#64748b;'>↔ Horizontally scrollable • Newest games first • Hover bars for box-score details</div>
    </div>
    """


def _build_profile_log_table_html(data: Dict[str, Any]) -> str:
    df_w = data['weekly_df']
    game_rows = []
    if not df_w.empty:
        # Sort chronologically reverse: 2026 latest first, then 2025
        df_sorted = df_w.sort_values(by=['season', 'week'], ascending=[False, False]) if 'season' in df_w.columns else df_w.sort_values(by='week', ascending=False)
        for _, wr in df_sorted.iterrows():
            w_pts = float(wr['points'])
            diff_pts = round(w_pts - data['mean_points'], 1)
            if diff_pts > 0:
                diff_html = f"<span style='color:#16a34a; font-weight:700; font-size:0.78rem;'>+{diff_pts:.1f}</span>"
            elif diff_pts < 0:
                diff_html = f"<span style='color:#dc2626; font-weight:700; font-size:0.78rem;'>{diff_pts:.1f}</span>"
            else:
                diff_html = "<span style='color:#64748b; font-size:0.78rem;'>0.0</span>"

            s_val = str(wr.get('season', '2026'))
            s_badge = f"<span style='background:#eff6ff; color:#1d4ed8; font-weight:800; font-size:0.72rem; border-radius:4px; padding:2px 6px; border:1px solid #bfdbfe;'>2026</span>" if s_val == '2026' else f"<span style='background:#f1f5f9; color:#64748b; font-weight:700; font-size:0.72rem; border-radius:4px; padding:2px 6px;'>{s_val}</span>"

            team_val = resolve_nfl_team(wr.get('nfl_team'), fallback=data.get('nfl_team', 'FA'))
            t_color = NFL_TEAM_COLORS.get(team_val.upper(), '#00338D')
            team_badge = f"<span style='background:{t_color}18; color:{t_color}; border:1px solid {t_color}40; font-weight:800; font-size:0.72rem; border-radius:4px; padding:2px 6px;'>{team_val}</span>"

            f_stat = str(wr.get('fantasy_status', '—'))
            if f_stat == 'Started':
                f_stat_html = "<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:6px; padding:2px 7px; font-weight:700; font-size:0.72rem;'>Started</span>"
            elif f_stat == 'Bench':
                f_stat_html = "<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#64748b; border-radius:6px; padding:2px 7px; font-weight:600; font-size:0.72rem;'>Bench</span>"
            elif 'Season' in f_stat:
                f_stat_html = "<span style='color:#94a3b8; font-size:0.74rem;'>Historical</span>"
            else:
                f_stat_html = f"<span style='color:#94a3b8; font-size:0.75rem;'>{f_stat}</span>"

            stats_snippets = []
            if wr.get('pass_yd', 0) > 0 or wr.get('pass_td', 0) > 0:
                stats_snippets.append(f"{int(wr['pass_yd'])} Yds, {int(wr['pass_td'])} TD" + (f", {int(wr['pass_int'])} INT" if wr.get('pass_int', 0) > 0 else ""))
            if wr.get('rush_yd', 0) > 0 or wr.get('rush_td', 0) > 0:
                stats_snippets.append(f"{int(wr['rush_yd'])} Rush Yds, {int(wr['rush_td'])} TD")
            if wr.get('rec', 0) > 0 or wr.get('rec_yd', 0) > 0:
                stats_snippets.append(f"{int(wr['rec'])} Rec, {int(wr['rec_yd'])} Yds" + (f", {int(wr['rec_td'])} TD" if wr.get('rec_td', 0) > 0 else ""))
            stats_desc = " • ".join(stats_snippets) if stats_snippets else "—"

            game_rows.append(f"""
            <tr style='border-bottom:1px solid #f1f5f9; height:44px; {"background:#fafcff;" if s_val == "2026" else ""}'>
                <td style='padding:8px 14px; font-weight:700; color:#0f172a; white-space:nowrap;'>{s_badge} <span style='margin-left:4px;'>Week {int(wr['week'])}</span></td>
                <td style='padding:8px 14px; text-align:center;'>{team_badge}</td>
                <td style='padding:8px 14px; text-align:right; font-weight:800; font-size:0.95rem; color:#0f172a;'>{w_pts:.1f}</td>
                <td style='padding:8px 14px; text-align:right;'>{diff_html}</td>
                <td style='padding:8px 14px; text-align:center;'>{f_stat_html}</td>
                <td style='padding:8px 14px; color:#475569; font-size:0.8rem;'>{stats_desc}</td>
            </tr>
            """)

    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:16px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'>
        <div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'>
            <span>📜 Complete Game Log (2026 & 2025 History)</span>
            <span style='font-size:0.75rem; color:#64748b; font-weight:500;'>{len(game_rows)} Total Games Recorded</span>
        </div>
        <div style='overflow-x:auto;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.84rem;'>
                <thead>
                    <tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px;'>
                        <th style='padding:10px 14px; text-align:left; width:130px;'>Season / Week</th>
                        <th style='padding:10px 14px; text-align:center; width:90px;'>NFL Team</th>
                        <th style='padding:10px 14px; text-align:right; width:100px;'>Fantasy Pts</th>
                        <th style='padding:10px 14px; text-align:right; width:110px;'>vs 2026 Avg</th>
                        <th style='padding:10px 14px; text-align:center; width:110px;'>Lineup Slot</th>
                        <th style='padding:10px 14px; text-align:left;'>Key Box Score Stats</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(game_rows) if game_rows else "<tr><td colspan='6' style='padding:16px; text-align:center; color:#94a3b8;'>No weekly box score logs recorded yet.</td></tr>"}
                </tbody>
            </table>
        </div>
    </div>
    """


def render_player_profile_view(
    data: Dict[str, Any],
    owner_colors: Optional[Dict[str, str]] = None,
    mo: Any = None
) -> Any:
    """
    Produce clean Marimo-native rendered view for a single player profile.
    Combines reactive KPI cards, Altair weekly chart, and box score game log table.
    """
    if mo is None:
        import marimo as mo

    if not data:
        return mo.md("Please select a player to view stats.")

    from src.visual import build_player_weekly_bar_chart
    chart = build_player_weekly_bar_chart(
        weekly_df=data['weekly_df'],
        mean_points=data['mean_points'],
        player_name=data['player_name'],
        position=data['position'],
        chart_width=860,
        chart_height=300
    )

    header_html = _build_profile_header_html(data, owner_colors)
    kpi_html = _build_profile_kpi_html(data)
    chart_header = _build_chart_header_html(data)
    log_html = _build_profile_log_table_html(data)

    chart_widget = mo.ui.altair_chart(chart).style({
        'overflow-x': 'auto',
        'width': '100%',
        'background': '#ffffff',
        'border-radius': '12px',
        'padding': '6px 0'
    })

    return mo.vstack([
        mo.Html(header_html),
        mo.Html(kpi_html),
        mo.Html(chart_header),
        chart_widget,
        mo.Html(log_html)
    ], gap=1)


def _build_comp_headers_html(comp_data: Dict[str, Any], owner_colors: Optional[Dict[str, str]] = None) -> str:
    p_a = comp_data['player_a']
    p_b = comp_data['player_b']

    pos_colors = {
        'QB': '#f43f5e',
        'RB': '#06b6d4',
        'WR': '#3b82f6',
        'TE': '#f59e0b',
        'K': '#a855f7',
        'DEF': '#64748b'
    }

    def make_player_header(p, col_theme, is_a=True):
        pos_col = pos_colors.get(p['position'], '#2563eb')
        inj = p['injury_status']
        if inj == 'Healthy':
            inj_b = "<span style='color:#16a34a; font-weight:700; font-size:0.75rem;'>● Active</span>"
        else:
            inj_b = f"<span style='color:#dc2626; font-weight:700; font-size:0.75rem;'>● {inj}</span>"

        return f"""
        <div style='background:#ffffff; border:2px solid {col_theme}; border-radius:14px; padding:16px 20px; box-shadow:0 2px 8px rgba(0,0,0,0.04); flex:1; min-width:280px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'>
            <div style='display:flex; align-items:center; gap:16px;'>
                <img src='{p['headshot_url']}' style='width:64px; height:64px; border-radius:50%; object-fit:cover; background:#f8fafc; border:2.5px solid {col_theme};' onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'" />
                <div style='flex:1;'>
                    <div style='font-size:0.72rem; font-weight:700; color:{col_theme}; text-transform:uppercase;'>Player {'A' if is_a else 'B'}</div>
                    <div style='font-size:1.3rem; font-weight:800; color:#0f172a; line-height:1.2;'>{p['player_name']}</div>
                    <div style='display:flex; align-items:center; gap:6px; margin-top:4px;'>
                        <span style='background:{pos_col}; color:#fff; font-weight:800; font-size:0.72rem; border-radius:5px; padding:2px 7px;'>{p['position']}</span>
                        <span style='background:#f1f5f9; color:#475569; font-weight:700; font-size:0.72rem; border-radius:5px; padding:2px 7px;'>{p['nfl_team']}</span>
                        {inj_b}
                    </div>
                    <div style='font-size:0.76rem; color:#64748b; margin-top:4px;'>Owner: <strong>{p['owner_name']}</strong></div>
                </div>
                <div style='text-align:right;'>
                    <div style='font-size:0.7rem; color:#64748b; font-weight:600; text-transform:uppercase;'>PPG</div>
                    <div style='font-size:1.55rem; font-weight:800; color:{col_theme};'>{p['mean_points']:.1f}</div>
                    <div style='font-size:0.72rem; color:#64748b;'>#{p['pos_rank']} {p['position']}</div>
                </div>
            </div>
        </div>
        """

    head_a = make_player_header(p_a, '#2563eb', is_a=True)
    head_b = make_player_header(p_b, '#059669', is_a=False)

    return f"""
    <div style='display:flex; gap:14px; flex-wrap:wrap; margin-bottom:14px;'>
        {head_a}
        {head_b}
    </div>
    """


def _build_comp_banner_html(comp_data: Dict[str, Any]) -> str:
    p_a = comp_data['player_a']
    p_b = comp_data['player_b']
    score_a = comp_data['wins_a']
    score_b = comp_data['wins_b']
    ties = comp_data['ties']

    if score_a > score_b:
        h2h_sub = f"🏆 <strong>{p_a['player_name']}</strong> outscored <strong>{p_b['player_name']}</strong> in {score_a} of {score_a + score_b + ties} weeks"
    elif score_b > score_a:
        h2h_sub = f"🏆 <strong>{p_b['player_name']}</strong> outscored <strong>{p_a['player_name']}</strong> in {score_b} of {score_a + score_b + ties} weeks"
    else:
        h2h_sub = f"🤝 Even split: Both players tied {score_a} — {score_b}"

    return f"""
    <div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:10px 16px; margin-bottom:16px; text-align:center; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size:0.86rem; color:#334155;'>
        {h2h_sub}
    </div>
    """


def _build_comp_verdict_html(comp_data: Dict[str, Any]) -> str:
    bullets_html = "".join([f"<li style='margin-bottom:6px;'>{b}</li>" for b in comp_data['verdict_bullets']])
    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:18px 22px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,0.03); font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'>
        <div style='display:flex; align-items:center; gap:8px; margin-bottom:10px;'>
            <span style='font-size:1.15rem;'>🧠</span>
            <span style='font-weight:800; font-size:0.95rem; color:#0f172a;'>Automated Comparison Analysis & Verdict</span>
        </div>
        <ul style='margin:0 0 12px 18px; padding:0; font-size:0.84rem; color:#334155; line-height:1.5;'>
            {bullets_html}
        </ul>
        <div style='background:#f8fafc; border-left:3px solid #2563eb; padding:10px 14px; border-radius:6px; font-size:0.84rem; color:#0f172a;'>
            💡 {comp_data['recommendation']}
        </div>
    </div>
    """


def _build_comp_tape_html(comp_data: Dict[str, Any]) -> str:
    p_a = comp_data['player_a']
    p_b = comp_data['player_b']

    metric_rows = []
    for m in comp_data['metrics_comp']:
        w = m['winner']
        style_a = "background:#eff6ff; font-weight:800; color:#1d4ed8;" if w == 'A' else "color:#475569;"
        style_b = "background:#ecfdf5; font-weight:800; color:#047857;" if w == 'B' else "color:#475569;"
        badge_a = " <span style='color:#1d4ed8; font-size:0.8rem;'>✓</span>" if w == 'A' else ""
        badge_b = " <span style='color:#047857; font-size:0.8rem;'>✓</span>" if w == 'B' else ""

        metric_rows.append(f"""
        <tr style='border-bottom:1px solid #f1f5f9; height:44px;'>
            <td style='padding:8px 16px; text-align:right; width:36%; {style_a}'>{m['val_a']}{badge_a}</td>
            <td style='padding:8px 12px; text-align:center; width:28%; font-weight:700; color:#0f172a; font-size:0.82rem; background:#fafbfc;'>{m['metric']}</td>
            <td style='padding:8px 16px; text-align:left; width:36%; {style_b}'>{badge_b}{m['val_b']}</td>
        </tr>
        """)

    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-bottom:16px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'>
        <div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'>
            <span>🥊 Tale of the Tape (Metrics Side-by-Side)</span>
            <span style='font-size:0.75rem; color:#64748b;'>✓ Indicates winning metric</span>
        </div>
        <div style='overflow-x:auto;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.84rem;'>
                <thead>
                    <tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px;'>
                        <th style='padding:10px 16px; text-align:right; width:36%; color:#1d4ed8;'>{p_a['player_name']}</th>
                        <th style='padding:10px 12px; text-align:center; width:28%;'>Metric Category</th>
                        <th style='padding:10px 16px; text-align:left; width:36%; color:#047857;'>{p_b['player_name']}</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(metric_rows)}
                </tbody>
            </table>
        </div>
    </div>
    """


def _build_comp_chart_header(comp_data: Dict[str, Any]) -> str:
    p_a = comp_data['player_a']
    p_b = comp_data['player_b']
    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px 14px 0 0; padding:14px 18px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; border-bottom:1px solid #e2e8f0; margin-top:6px;'>
        <div style='display:flex; justify-content:space-between; align-items:center;'>
            <div>
                <span style='font-weight:800; font-size:0.96rem; color:#0f172a;'>📊 Head-to-Head Weekly Fantasy Points Comparison</span>
                <span style='font-size:0.76rem; color:#64748b; margin-left:8px;'>({p_a['player_name']} in Blue vs {p_b['player_name']} in Green)</span>
            </div>
            <div style='font-size:0.74rem; color:#64748b;'>Hover bars to inspect weekly scores</div>
        </div>
    </div>
    """


def _build_comp_h2h_table(comp_data: Dict[str, Any]) -> str:
    p_a = comp_data['player_a']
    p_b = comp_data['player_b']
    score_a = comp_data['wins_a']
    score_b = comp_data['wins_b']

    h2h_rows = []
    for _, hr in comp_data['h2h_df'].sort_values(by='week', ascending=False).iterrows():
        w_key = hr['winner_key']
        if w_key == 'A':
            win_pill = f"<span style='background:#eff6ff; border:1px solid #bfdbfe; color:#1d4ed8; font-weight:800; font-size:0.75rem; border-radius:6px; padding:2px 8px;'>{p_a['player_name']} (+{hr['margin']:.1f})</span>"
        elif w_key == 'B':
            win_pill = f"<span style='background:#ecfdf5; border:1px solid #a7f3d0; color:#047857; font-weight:800; font-size:0.75rem; border-radius:6px; padding:2px 8px;'>{p_b['player_name']} (+{hr['margin']:.1f})</span>"
        else:
            win_pill = "<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#64748b; font-weight:700; font-size:0.75rem; border-radius:6px; padding:2px 8px;'>Tie (0.0)</span>"

        h2h_rows.append(f"""
        <tr style='border-bottom:1px solid #f1f5f9; height:42px;'>
            <td style='padding:8px 14px; font-weight:700; color:#0f172a;'>Week {int(hr['week'])}</td>
            <td style='padding:8px 14px; text-align:right; font-weight:700; color:{'#1d4ed8' if w_key == 'A' else '#475569'};'>{hr['pts_a']:.1f}</td>
            <td style='padding:8px 14px; text-align:right; font-weight:700; color:{'#047857' if w_key == 'B' else '#475569'};'>{hr['pts_b']:.1f}</td>
            <td style='padding:8px 14px; text-align:center;'>{win_pill}</td>
        </tr>
        """)

    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:16px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'>
        <div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'>
            <span>⚔️ Week-by-Week Head-to-Head Record</span>
            <span style='font-size:0.78rem; font-weight:700; color:#0f172a;'>{p_a['player_name']} {score_a} — {score_b} {p_b['player_name']}</span>
        </div>
        <div style='overflow-x:auto;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.84rem;'>
                <thead>
                    <tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px;'>
                        <th style='padding:10px 14px; text-align:left;'>Week</th>
                        <th style='padding:10px 14px; text-align:right; width:130px; color:#1d4ed8;'>{p_a['player_name']}</th>
                        <th style='padding:10px 14px; text-align:right; width:130px; color:#047857;'>{p_b['player_name']}</th>
                        <th style='padding:10px 14px; text-align:center; width:200px;'>Weekly Winner</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(h2h_rows)}
                </tbody>
            </table>
        </div>
    </div>
    """


def render_player_comparison_view(
    comp_data: Dict[str, Any],
    owner_colors: Optional[Dict[str, str]] = None,
    mo: Any = None
) -> Any:
    """
    Produce clean Marimo-native rendered view for head-to-head player comparison.
    Combines player cards, automated verdict card, tale of the tape table, Altair grouped chart, and weekly matchup table.
    """
    if mo is None:
        import marimo as mo

    if not comp_data:
        return mo.md("Please select two players to compare.")

    from src.visual import build_player_comparison_chart
    chart = build_player_comparison_chart(
        df_comp=comp_data['combined_chart_df'],
        name_a=comp_data['player_a']['player_name'],
        name_b=comp_data['player_b']['player_name'],
        color_a='#2563eb',
        color_b='#059669',
        chart_width=860,
        chart_height=320
    )

    heads_html = _build_comp_headers_html(comp_data, owner_colors)
    banner_html = _build_comp_banner_html(comp_data)
    verdict_html = _build_comp_verdict_html(comp_data)
    tape_html = _build_comp_tape_html(comp_data)
    chart_header = _build_comp_chart_header(comp_data)
    h2h_html = _build_comp_h2h_table(comp_data)

    return mo.vstack([
        mo.Html(heads_html),
        mo.Html(banner_html),
        mo.Html(verdict_html),
        mo.Html(tape_html),
        mo.Html(chart_header),
        mo.ui.altair_chart(chart),
        mo.Html(h2h_html)
    ], gap=1)
