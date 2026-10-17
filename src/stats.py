import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, List, Optional


def compute_player_aggregates(df_stats: pd.DataFrame) -> pd.DataFrame:
    """
    Compute mean, std, median, min, max, total points, coefficient of variation (CV),
    positional rank, and pivot weekly points per player.
    """
    if df_stats is None or df_stats.empty:
        return pd.DataFrame()

    agg = df_stats.groupby(['player_id', 'player_name', 'position', 'nfl_team', 'injury_status', 'current_owner']).agg(
        games_played=('points', 'count'),
        total_points=('points', 'sum'),
        mean_points=('points', 'mean'),
        std_points=('points', lambda x: float(np.std(x, ddof=1)) if len(x) > 1 else 0.0),
        median_points=('points', 'median'),
        min_points=('points', 'min'),
        max_points=('points', 'max'),
        total_pass_yd=('pass_yd', 'sum'),
        total_pass_td=('pass_td', 'sum'),
        total_rush_yd=('rush_yd', 'sum'),
        total_rush_td=('rush_td', 'sum'),
        total_rec=('rec', 'sum'),
        total_rec_yd=('rec_yd', 'sum'),
        total_rec_td=('rec_td', 'sum')
    ).reset_index()

    agg['mean_points'] = agg['mean_points'].round(2)
    agg['std_points'] = agg['std_points'].fillna(0.0).round(2)
    agg['total_points'] = agg['total_points'].round(2)
    agg['median_points'] = agg['median_points'].round(2)
    agg['cv'] = np.where(agg['mean_points'] > 0, (agg['std_points'] / agg['mean_points']).round(2), 0.0)

    # Positional Rank within each position based on mean points
    agg['pos_rank'] = agg.groupby('position')['mean_points'].rank(ascending=False, method='min').astype(int)

    # Consistency 3-Tier Classification
    def classify_consistency(sd: float) -> str:
        if sd < 4.5:
            return "🟢 Low Variance"
        elif sd < 9.0:
            return "🟡 Moderate"
        else:
            return "🔴 High Variance"

    agg['consistency_tier'] = agg['std_points'].apply(classify_consistency)

    # Pivot weekly points
    pivot_w = df_stats.pivot(index='player_id', columns='week', values='points').add_prefix('Week ').reset_index()
    merged = pd.merge(agg, pivot_w, on='player_id', how='left')

    # Headshot URLs
    merged['headshot_url'] = merged.apply(
        lambda r: f"https://sleepercdn.com/images/team_logos/nfl/{str(r['nfl_team']).lower()}.png"
        if r['position'] == 'DEF' or str(r['player_id']) == str(r['nfl_team'])
        else f"https://sleepercdn.com/content/nfl/players/{r['player_id']}.jpg",
        axis=1
    )

    return merged


def get_team_roster_analytics(
    team_name: str,
    df_rosters: pd.DataFrame,
    df_player_stats: pd.DataFrame,
    df_teams: pd.DataFrame,
    val_df: Optional[pd.DataFrame] = None,
    week: Optional[int] = None,
    season: Optional[str] = None,
    db_path: Optional[str] = None,
    league_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compute dedicated team-level metrics:
    - Starting Lineup vs Bench subsets
    - Injury breakdown (Healthy vs Injured count)
    - Variance metrics (Low vs High Variance)
    - Top-10 elite asset metrics
    - Positional output breakdown and total PPG
    - Starters and bench injury lists for detailed tooltip pinpoints
    - Average positional rank for Starters, Bench, and Total (excluding IR)
    """
    if df_rosters is None or df_rosters.empty or df_player_stats is None or df_player_stats.empty:
        return {}

    team_roster = df_rosters[df_rosters['team_name'] == team_name].copy()
    if team_roster.empty:
        return {}

    merged = team_roster.copy()
    if 'is_reserve' not in merged.columns:
        merged['is_reserve'] = 0
    else:
        merged['is_reserve'] = merged['is_reserve'].fillna(0).astype(int)

    if 'is_starter' not in merged.columns:
        merged['is_starter'] = 0
    else:
        merged['is_starter'] = merged['is_starter'].fillna(0).astype(int)

    if df_player_stats is not None and not df_player_stats.empty:
        stats_cols = [
            'player_id', 'games_played', 'total_points', 'mean_points', 'std_points',
            'median_points', 'min_points', 'max_points', 'cv', 'pos_rank',
            'consistency_tier', 'headshot_url'
        ] + [c for c in df_player_stats.columns if c.startswith('Week ')]
        available_cols = [c for c in stats_cols if c in df_player_stats.columns]
        merged = pd.merge(merged, df_player_stats[available_cols], on='player_id', how='left')

    # Fill defaults for un-played/un-matched players
    if 'player_name' not in merged.columns:
        merged['player_name'] = merged['player_id'].astype(str)
    else:
        merged['player_name'] = merged['player_name'].fillna(merged['player_id'].astype(str))

    if 'position' not in merged.columns:
        merged['position'] = 'WR'
    else:
        merged['position'] = merged['position'].fillna('WR')

    if 'nfl_team' not in merged.columns:
        merged['nfl_team'] = ''
    else:
        merged['nfl_team'] = merged['nfl_team'].fillna('')

    if 'mean_points' not in merged.columns:
        merged['mean_points'] = 0.0
    else:
        merged['mean_points'] = merged['mean_points'].fillna(0.0)

    if 'std_points' not in merged.columns:
        merged['std_points'] = 0.0
    else:
        merged['std_points'] = merged['std_points'].fillna(0.0)

    if 'games_played' not in merged.columns:
        merged['games_played'] = 0
    else:
        merged['games_played'] = merged['games_played'].fillna(0).astype(int)

    if 'pos_rank' not in merged.columns:
        merged['pos_rank'] = 99
    else:
        merged['pos_rank'] = merged['pos_rank'].fillna(99).astype(int)

    if 'consistency_tier' not in merged.columns:
        merged['consistency_tier'] = '—'
    else:
        merged['consistency_tier'] = merged['consistency_tier'].fillna('—')

    if 'injury_status' not in merged.columns:
        merged['injury_status'] = 'Healthy'
    else:
        merged['injury_status'] = merged['injury_status'].fillna('Healthy')

    if 'headshot_url' not in merged.columns or merged['headshot_url'].isna().any():
        merged['headshot_url'] = merged.apply(
            lambda r: f"https://sleepercdn.com/images/team_logos/nfl/{str(r.get('nfl_team', '')).lower()}.png"
            if r.get('position') == 'DEF' or str(r.get('player_id')) == str(r.get('nfl_team'))
            else f"https://sleepercdn.com/content/nfl/players/{r.get('player_id')}.jpg",
            axis=1
        )

    # Calculate or map player trade values (0-100 scale)
    if val_df is None and df_rosters is not None and not df_rosters.empty and df_player_stats is not None and not df_player_stats.empty:
        try:
            from src.trades import calculate_player_trade_values
            val_df = calculate_player_trade_values(df_rosters, df_player_stats)
        except Exception:
            val_df = None

    if val_df is not None and not val_df.empty and 'trade_value' in val_df.columns:
        val_map = val_df.drop_duplicates(subset=['player_id']).set_index('player_id')['trade_value'].to_dict()
        merged['trade_value'] = merged['player_id'].map(val_map).fillna(1.0).round(1)
    else:
        merged['trade_value'] = 0.0

    # Determine bye teams and live matchup starters for the target week
    try:
        from src.optimizer import get_current_nfl_week, get_nfl_bye_teams, is_player_on_bye, get_week_matchup_starters
        from src.config import DB_PATH, CURRENT_SEASON, DEFAULT_LEAGUE_ID
        target_week = week if week is not None else get_current_nfl_week()
        target_season = season if season is not None else CURRENT_SEASON
        target_league_id = league_id or DEFAULT_LEAGUE_ID
        bye_teams = get_nfl_bye_teams(season=target_season, week=target_week, db_path=db_path or DB_PATH)
        week_starters_map = get_week_matchup_starters(league_id=target_league_id, week=target_week)
    except Exception:
        bye_teams = set()
        week_starters_map = {}

    # Overlay live week matchup starters if available
    team_info = df_teams[df_teams['team_name'] == team_name] if df_teams is not None and not df_teams.empty else pd.DataFrame()
    roster_id = team_info['roster_id'].iloc[0] if not team_info.empty else (team_roster['roster_id'].iloc[0] if 'roster_id' in team_roster.columns else None)
    if roster_id is not None and week_starters_map:
        live_starters = set(str(p) for p in (week_starters_map.get(roster_id) or week_starters_map.get(str(roster_id)) or []))
        if live_starters:
            merged['is_starter'] = merged['player_id'].astype(str).isin(live_starters).astype(int)

    # Assign fantasy starting slots
    def assign_slots(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['slot'] = 'BN'
        starters = df[df['is_starter'] == 1].copy()

        # Slot assignment order
        pos_counts = {'QB': 1, 'RB': 2, 'WR': 2, 'TE': 1, 'K': 1, 'DEF': 1}
        allocated_ids = set()

        for pos, count in pos_counts.items():
            candidates = starters[starters['position'] == pos].sort_values(by='mean_points', ascending=False)
            assigned = candidates.head(count)['player_id'].tolist()
            allocated_ids.update(assigned)
            df.loc[df['player_id'].isin(assigned), 'slot'] = pos

        # FLEX
        flex_candidates = starters[
            (~starters['player_id'].isin(allocated_ids)) &
            (starters['position'].isin(['RB', 'WR', 'TE']))
        ].sort_values(by='mean_points', ascending=False)
        if not flex_candidates.empty:
            flex_id = flex_candidates.iloc[0]['player_id']
            df.loc[df['player_id'] == flex_id, 'slot'] = 'FLEX'
            allocated_ids.add(flex_id)

        # Starters must strictly be those allocated to a starting slot
        df.loc[df['slot'].isin(['QB', 'RB', 'WR', 'TE', 'FLEX', 'K', 'DEF']), 'is_starter'] = 1
        df.loc[df['slot'] == 'BN', 'is_starter'] = 0

        # Assign IR slot to reserve / IR players on bench
        is_ir = (
            (df['is_reserve'] == 1) |
            (df['injury_status'].astype(str).str.strip().str.upper().isin(['IR', 'PUP'])) |
            (df.get('status', pd.Series(dtype=object, index=df.index)).astype(str).str.strip().isin(['Injured Reserve', 'Physically Unable to Perform']))
        )
        df.loc[(df['is_starter'] == 0) & is_ir, 'slot'] = 'IR'

        # Assign BYE slot to bench players whose NFL team is on BYE
        if bye_teams:
            is_bye = (df['is_starter'] == 0) & (df['slot'] != 'IR') & (
                df.apply(lambda r: is_player_on_bye(r.get('nfl_team'), r.get('position'), r.get('player_id'), bye_teams), axis=1)
            )
            df.loc[is_bye, 'slot'] = 'BYE'

        return df

    merged = assign_slots(merged)

    # Sort order: Starters first, then active bench (BN & BYE by position / mean_points), and IR at the very bottom
    slot_order = {'QB': 1, 'RB': 2, 'WR': 3, 'TE': 4, 'FLEX': 5, 'K': 6, 'DEF': 7, 'BN': 8, 'BYE': 8, 'IR': 9}
    pos_order = {'QB': 1, 'RB': 2, 'WR': 3, 'TE': 4, 'K': 5, 'DEF': 6}
    merged['slot_order'] = merged['slot'].map(lambda s: slot_order.get(s, 99))
    merged['pos_order'] = merged['position'].map(lambda p: pos_order.get(p, 99))
    merged = merged.sort_values(by=['slot_order', 'pos_order', 'mean_points'], ascending=[True, True, False]).reset_index(drop=True)

    starters_df = merged[merged['is_starter'] == 1].reset_index(drop=True)
    bench_df = merged[merged['is_starter'] == 0].reset_index(drop=True)

    # Metrics
    starter_ppg = round(float(starters_df['mean_points'].sum()), 1)
    bench_ppg = round(float(bench_df['mean_points'].sum()), 1)
    starter_tv = round(float(starters_df['trade_value'].sum()), 1) if not starters_df.empty else 0.0
    bench_tv = round(float(bench_df['trade_value'].sum()), 1) if not bench_df.empty else 0.0
    total_roster_tv = round(starter_tv + bench_tv, 1)

    # Top assets
    top_10_count = int((merged['pos_rank'] <= 10).sum())
    top_5_count = int((merged['pos_rank'] <= 5).sum())

    # Injuries
    injured_count = int((merged['injury_status'] != 'Healthy').sum())
    starter_injured_count = int((starters_df['injury_status'] != 'Healthy').sum())

    # Detailed lists of injured players for pinpoint tooltips
    injured_starters = starters_df[starters_df['injury_status'] != 'Healthy']
    injured_bench = bench_df[bench_df['injury_status'] != 'Healthy']

    def format_inj_list(df_sub: pd.DataFrame) -> str:
        if df_sub.empty:
            return ""
        items = [f"{r['player_name']} ({r['position']}, {r['injury_status']})" for _, r in df_sub.iterrows()]
        return ", ".join(items)

    starter_inj_details = format_inj_list(injured_starters)
    bench_inj_details = format_inj_list(injured_bench)

    # Average Positional Rank within position (excluding IR, only active starters & bench)
    non_ir_roster = merged[
        (merged['slot'] != 'IR') &
        (merged['injury_status'].astype(str).str.strip().str.upper() != 'IR') &
        (merged.get('is_reserve', 0) != 1)
    ].copy()
    non_ir_starters = non_ir_roster[non_ir_roster['is_starter'] == 1]
    non_ir_bench = non_ir_roster[non_ir_roster['is_starter'] == 0]

    starters_ranks = non_ir_starters[non_ir_starters['pos_rank'] < 99]['pos_rank']
    if starters_ranks.empty:
        starters_ranks = non_ir_starters['pos_rank']
    bench_ranks = non_ir_bench[non_ir_bench['pos_rank'] < 99]['pos_rank']
    if bench_ranks.empty:
        bench_ranks = non_ir_bench['pos_rank']
    all_ranks = non_ir_roster[non_ir_roster['pos_rank'] < 99]['pos_rank']
    if all_ranks.empty:
        all_ranks = non_ir_roster['pos_rank']

    avg_pos_rank_starters = round(float(starters_ranks.mean()), 1) if not starters_ranks.empty else 0.0
    avg_pos_rank_bench = round(float(bench_ranks.mean()), 1) if not bench_ranks.empty else 0.0
    avg_pos_rank_total = round(float(all_ranks.mean()), 1) if not all_ranks.empty else 0.0

    # Positional Breakdown (Starters only)
    pos_breakdown = starters_df.groupby('position')['mean_points'].sum().round(1).to_dict()

    # Team record info
    team_info = df_teams[df_teams['team_name'] == team_name].iloc[0] if not df_teams[df_teams['team_name'] == team_name].empty else None

    ir_count = int((bench_df['slot'] == 'IR').sum())
    bn_count = int(len(bench_df) - ir_count)

    return {
        'team_name': team_name,
        'owner_name': team_info['owner_name'] if team_info is not None else team_name,
        'wins': int(team_info['wins']) if team_info is not None else 0,
        'losses': int(team_info['losses']) if team_info is not None else 0,
        'total_fpts': float(team_info['fpts']) if team_info is not None else 0.0,
        'starter_ppg': starter_ppg,
        'bench_ppg': bench_ppg,
        'starter_tv': starter_tv,
        'bench_tv': bench_tv,
        'total_roster_tv': total_roster_tv,
        'top_10_count': top_10_count,
        'top_5_count': top_5_count,
        'injured_count': injured_count,
        'starter_injured_count': starter_injured_count,
        'starter_inj_details': starter_inj_details,
        'bench_inj_details': bench_inj_details,
        'pos_breakdown': pos_breakdown,
        'total_starters_count': len(starters_df),
        'starters_df': starters_df,
        'bench_df': bench_df,
        'all_roster_df': merged,
        'avg_pos_rank_starters': avg_pos_rank_starters,
        'avg_pos_rank_bench': avg_pos_rank_bench,
        'avg_pos_rank_total': avg_pos_rank_total,
        'ir_count': ir_count,
        'bn_count': bn_count
    }


def get_league_overview_analytics(
    df_teams: pd.DataFrame,
    df_rosters: pd.DataFrame,
    df_player_stats: pd.DataFrame
) -> Dict[str, Any]:
    """
    Compute comprehensive league standings and comparison metrics:
    - Standings table ordered by Wins DESC, then Points For DESC
    - Points For (PF), Points Against (PA), Point Differential (+/-)
    - Starter PPG, Bench Depth PPG, Top-10 Elite Asset Counts, Roster Health
    - Average positional rank for starters and bench (excluding IR)
    - Composite Power Rating
    - League summary KPIs (Actual league average PF per team/week & current starter projection)
    """
    if df_teams is None or df_teams.empty:
        return {}

    standings = []
    total_pf_sum = 0.0
    total_games_sum = 0

    val_df = None
    if df_rosters is not None and not df_rosters.empty and df_player_stats is not None and not df_player_stats.empty:
        try:
            from src.trades import calculate_player_trade_values
            val_df = calculate_player_trade_values(df_rosters, df_player_stats)
        except Exception:
            val_df = None

    for idx, r in df_teams.reset_index(drop=True).iterrows():
        t_name = r['team_name']
        an = get_team_roster_analytics(t_name, df_rosters, df_player_stats, df_teams, val_df=val_df)
        pf = float(r['fpts'])
        pa = float(r['fpts_against']) if 'fpts_against' in r else 0.0
        diff = round(pf - pa, 2)
        total_games = max(1, r['wins'] + r['losses'])
        win_pct = round(r['wins'] / total_games, 3)

        total_pf_sum += pf
        total_games_sum += total_games

        # Composite Power Score (0 - 100)
        # 40% Win %, 35% Starter PPG relative, 25% Total PF relative
        power_score = round((win_pct * 40.0) + (min(1.0, an['starter_ppg'] / 200.0) * 35.0) + (min(1.0, pf / 400.0) * 25.0), 1)

        total_roster = len(an['all_roster_df'])
        healthy_count = total_roster - an['injured_count']
        starter_injured = an['starter_injured_count']
        starters_total = an['total_starters_count']

        standings.append({
            'rank': idx + 1,
            'team_name': t_name,
            'owner_name': r['owner_name'],
            'wins': int(r['wins']),
            'losses': int(r['losses']),
            'win_pct': win_pct,
            'pf': pf,
            'pa': pa,
            'diff': diff,
            'starter_ppg': an['starter_ppg'],
            'bench_ppg': an['bench_ppg'],
            'roster_tv': an.get('total_roster_tv', 0.0),
            'starter_tv': an.get('starter_tv', 0.0),
            'bench_tv': an.get('bench_tv', 0.0),
            'avg_pos_rank_starters': an['avg_pos_rank_starters'],
            'avg_pos_rank_bench': an['avg_pos_rank_bench'],
            'avg_pos_rank_total': an['avg_pos_rank_total'],
            'top_10_count': an['top_10_count'],
            'top_5_count': an['top_5_count'],
            'healthy_count': healthy_count,
            'total_roster_count': total_roster,
            'starter_injured_count': starter_injured,
            'starter_inj_details': an['starter_inj_details'],
            'bench_inj_details': an['bench_inj_details'],
            'starters_total': starters_total,
            'power_score': power_score
        })

    df_standings = pd.DataFrame(standings)

    # Actual historical average scored per team/week (e.g. 1654.98 / 12 = 137.9 FPTS)
    actual_league_avg_ppg = round(total_pf_sum / max(1, total_games_sum), 1)
    
    leader_team = df_standings.iloc[0]
    high_pf_team = df_standings.sort_values(by='pf', ascending=False).iloc[0]
    tough_sched_team = df_standings.sort_values(by='pa', ascending=False).iloc[0]
    deepest_bench_team = df_standings.sort_values(by='bench_ppg', ascending=False).iloc[0]

    return {
        'standings_df': df_standings,
        'avg_starter_ppg': actual_league_avg_ppg,
        'leader_team': leader_team,
        'high_pf_team': high_pf_team,
        'tough_sched_team': tough_sched_team,
        'deepest_bench_team': deepest_bench_team
    }


def get_luck_and_all_play_analytics(
    df_teams: pd.DataFrame,
    df_team_matchups: pd.DataFrame
) -> Dict[str, Any]:
    """
    Compute All-Play Standings, Expected Wins, Schedule Luck Index,
    Record vs Weekly Median, and Weekly Head-to-Head Breakdown.
    """
    if df_teams is None or df_teams.empty or df_team_matchups is None or df_team_matchups.empty:
        return {}

    # Detect completed weeks with positive scoring across all teams
    num_teams = len(df_teams)
    comp_weeks = []
    for w, w_df in df_team_matchups.groupby('week'):
        if len(w_df) >= num_teams and (w_df['points'] > 0).all():
            comp_weeks.append(int(w))
    comp_weeks = sorted(comp_weeks)

    if not comp_weeks:
        return {}

    df_comp = df_team_matchups[df_team_matchups['week'].isin(comp_weeks)].copy()

    # Reconstruct actual head-to-head opponent pairings from matchup_id
    opponents = {}
    for (w, mid), group in df_comp.groupby(['week', 'matchup_id']):
        if len(group) == 2 and mid > 0:
            r1 = group.iloc[0]
            r2 = group.iloc[1]
            opponents[(w, r1['team_name'])] = {
                'opp_name': r2['team_name'],
                'opp_owner': r2.get('owner_name', r2['team_name']),
                'opp_pts': float(r2['points']),
                'pts': float(r1['points']),
                'result': 'W' if r1['points'] > r2['points'] else ('L' if r1['points'] < r2['points'] else 'T'),
                'margin': round(float(r1['points']) - float(r2['points']), 2)
            }
            opponents[(w, r2['team_name'])] = {
                'opp_name': r1['team_name'],
                'opp_owner': r1.get('owner_name', r1['team_name']),
                'opp_pts': float(r1['points']),
                'pts': float(r2['points']),
                'result': 'W' if r2['points'] > r1['points'] else ('L' if r2['points'] < r1['points'] else 'T'),
                'margin': round(float(r2['points']) - float(r1['points']), 2)
            }

    # Calculate weekly ranks and median per week
    weekly_ranks = {}
    weekly_medians = {}
    for w in comp_weeks:
        w_df = df_comp[df_comp['week'] == w]
        weekly_medians[w] = round(float(w_df['points'].median()), 2)
        # Rank within week (1 is highest score)
        w_sorted = w_df.sort_values(by='points', ascending=False).reset_index(drop=True)
        for idx, row in w_sorted.iterrows():
            weekly_ranks[(w, row['team_name'])] = idx + 1

    # Team records and aggregates
    team_data = {}
    for _, tr in df_teams.iterrows():
        t = tr['team_name']
        team_data[t] = {
            'team_name': t,
            'owner_name': tr['owner_name'],
            'actual_wins': int(tr['wins']),
            'actual_losses': int(tr['losses']),
            'actual_fpts': float(tr['fpts']),
            'actual_fpts_against': float(tr.get('fpts_against', 0.0)),
            'ap_wins': 0,
            'ap_losses': 0,
            'ap_ties': 0,
            'median_wins': 0,
            'median_losses': 0,
            'weekly_scores': {},
            'weekly_results': {}
        }

    # All-Play calculation per completed week
    for w in comp_weeks:
        w_df = df_comp[df_comp['week'] == w]
        scores = dict(zip(w_df['team_name'], w_df['points']))
        med_score = weekly_medians[w]

        for t1, s1 in scores.items():
            if t1 not in team_data:
                continue
            team_data[t1]['weekly_scores'][w] = float(s1)

            # Median comparison
            if s1 > med_score:
                team_data[t1]['median_wins'] += 1
            elif s1 < med_score:
                team_data[t1]['median_losses'] += 1

            # Opponent details
            opp_info = opponents.get((w, t1))
            rank_in_week = weekly_ranks.get((w, t1), 0)
            team_data[t1]['weekly_results'][w] = {
                'points': float(s1),
                'rank_in_week': rank_in_week,
                'total_teams_week': len(scores),
                'opp_name': opp_info['opp_name'] if opp_info else 'Unknown',
                'opp_pts': opp_info['opp_pts'] if opp_info else 0.0,
                'result': opp_info['result'] if opp_info else ('W' if s1 > med_score else 'L'),
                'margin': opp_info['margin'] if opp_info else 0.0
            }

            # All-Play head-to-head against every other team
            for t2, s2 in scores.items():
                if t1 == t2:
                    continue
                if s1 > s2:
                    team_data[t1]['ap_wins'] += 1
                elif s1 < s2:
                    team_data[t1]['ap_losses'] += 1
                else:
                    team_data[t1]['ap_ties'] += 1

    # Actual standings ranking for movement comparison
    actual_standings = df_teams.sort_values(by=['wins', 'fpts'], ascending=False).reset_index(drop=True)
    actual_ranks = {row['team_name']: idx + 1 for idx, row in actual_standings.iterrows()}

    # Compile All-Play Table
    table_rows = []
    for t, data in team_data.items():
        tot_ap = data['ap_wins'] + data['ap_losses'] + data['ap_ties']
        ap_win_pct = round(data['ap_wins'] / max(1, tot_ap), 3)
        actual_games = data['actual_wins'] + data['actual_losses']
        actual_win_pct = round(data['actual_wins'] / max(1, actual_games), 3)
        expected_wins = round(ap_win_pct * actual_games, 2)
        luck_diff = round(data['actual_wins'] - expected_wins, 2)

        scores_list = list(data['weekly_scores'].values())
        avg_score = round(float(np.mean(scores_list)), 2) if scores_list else 0.0
        min_score = round(float(np.min(scores_list)), 2) if scores_list else 0.0
        max_score = round(float(np.max(scores_list)), 2) if scores_list else 0.0
        std_score = round(float(np.std(scores_list, ddof=1)), 2) if len(scores_list) > 1 else 0.0

        act_rank = actual_ranks.get(t, 1)

        table_rows.append({
            'team_name': t,
            'owner_name': data['owner_name'],
            'actual_rank': act_rank,
            'actual_record': f"{data['actual_wins']}-{data['actual_losses']}",
            'actual_wins': data['actual_wins'],
            'actual_losses': data['actual_losses'],
            'actual_win_pct': actual_win_pct,
            'ap_record': f"{data['ap_wins']}-{data['ap_losses']}" + (f"-{data['ap_ties']}" if data['ap_ties'] > 0 else ""),
            'ap_wins': data['ap_wins'],
            'ap_losses': data['ap_losses'],
            'ap_win_pct': ap_win_pct,
            'expected_wins': expected_wins,
            'luck_diff': luck_diff,
            'median_record': f"{data['median_wins']}-{data['median_losses']}",
            'median_wins': data['median_wins'],
            'avg_score': avg_score,
            'min_score': min_score,
            'max_score': max_score,
            'std_score': std_score,
            'weekly_results': data['weekly_results']
        })

    df_ap = pd.DataFrame(table_rows).sort_values(
        by=['ap_wins', 'actual_wins', 'avg_score'],
        ascending=[False, False, False]
    ).reset_index(drop=True)

    df_ap['ap_rank'] = df_ap.index + 1
    # Movement: positive means higher in All-Play than actual standings (e.g. actual #4, AP #3 => +1)
    df_ap['rank_diff'] = df_ap['actual_rank'] - df_ap['ap_rank']

    # Identify Key Highlights
    luckiest_team = df_ap.sort_values(by='luck_diff', ascending=False).iloc[0]
    unluckiest_team = df_ap.sort_values(by='luck_diff', ascending=True).iloc[0]
    ap_leader = df_ap.iloc[0]
    median_leader = df_ap.sort_values(by=['median_wins', 'avg_score'], ascending=False).iloc[0]

    return {
        'all_play_df': df_ap,
        'completed_weeks': comp_weeks,
        'luckiest_team': luckiest_team,
        'unluckiest_team': unluckiest_team,
        'ap_leader': ap_leader,
        'median_leader': median_leader,
        'weekly_medians': weekly_medians
    }
