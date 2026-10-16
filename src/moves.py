"""
NFL Fantasy Analytics - Roster Move Revisitor & Grader
Historical evaluation and grading of waiver moves, free agent pickups, and trades.
Evaluated using Zero-Centered Dynamic Quantiles on Net PPG:
- Positive moves (> +0.5 PPG) are curve-graded into B, A, and A+ (top 25%)
- Neutral moves ([-0.5, +0.5] PPG) receive grade C (Fair / Even Swap)
- Negative moves (< -0.5 PPG) are curve-graded into D and F (worst 35%)
- Player tenure / stint bounding: an acquired player's stats accumulate strictly
  while on that team's roster until dropped. When dropped, the grading freezes.
- Re-acquisitions are treated as distinct, independent stints.
Outlier-resistant, mathematically robust, and dynamically calibrated to the league.
"""

import json
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import numpy as np
import pandas as pd

from src.db import get_connection, get_sync_metadata, load_league_data, load_roster_moves
from src.stats import compute_player_aggregates
from src.trades import calculate_player_trade_values


def _format_names(names: List[str]) -> str:
    """Format a list of player names into a readable string."""
    if not names:
        return "None"
    if len(names) == 1:
        return names[0]
    elif len(names) == 2:
        return f"{names[0]} & {names[1]}"
    else:
        return f"{names[0]}, {names[1]} (+{len(names)-2} more)"


def get_roster_move_analytics(
    db_path: Path,
    league_id: str,
    season: Optional[str] = None,
    team_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    sort_by: str = "newest"
) -> Dict[str, Any]:
    """
    Load all completed transactions and compute historical performance & grading.
    Evaluated primarily using Net PPG with Zero-Centered Dynamic Quantile Grading.
    Uses accurate NFL production strictly during each player's tenure on the roster:
    - Added players accumulate fantasy points/PPG only while on this team's roster until dropped.
    - Dropped players are evaluated against the transaction during that same stint duration.
    - Once an acquired player is dropped, the move grading is finalized and frozen.
    - Subsequent acquisitions of the same player begin fresh, independent stints.
    """
    if not db_path.exists():
        return {"moves": [], "kpis": {}, "team_options": ["All Teams"], "type_options": ["All Types"]}

    # Load core data
    teams_df, rosters_df, matchups_df, nfl_stats_df = load_league_data(db_path, league_id, season)
    moves_df = load_roster_moves(db_path, league_id, season)

    if moves_df.empty or teams_df.empty:
        return {"moves": [], "kpis": {}, "team_options": ["All Teams"], "type_options": ["All Types"]}

    # Current league week from metadata with robust dynamic fallbacks
    curr_wk_val = get_sync_metadata("current_week", db_path)
    try:
        current_league_week = int(curr_wk_val) if curr_wk_val else None
    except Exception:
        current_league_week = None

    if not current_league_week or current_league_week < 1:
        try:
            from src.optimizer import get_current_nfl_week
            current_league_week = get_current_nfl_week()
        except Exception:
            current_league_week = int(matchups_df['week'].max()) if not matchups_df.empty else 6

    # Team mapping
    team_name_map = dict(zip(teams_df['roster_id'], teams_df['team_name']))
    owner_name_map = dict(zip(teams_df['roster_id'], teams_df['owner_name']))

    # Player metadata mapping
    conn = get_connection(db_path)
    players_df = pd.read_sql_query('SELECT player_id, full_name, position, nfl_team FROM players', conn)
    conn.close()
    players_map = players_df.set_index('player_id').to_dict('index')

    # Current ownership map from rosters
    current_owner_map = {}
    if not rosters_df.empty:
        current_owner_map = dict(zip(rosters_df['player_id'], rosters_df['team_name']))

    # Trade values calculation
    tv_map = {}
    if not nfl_stats_df.empty and not rosters_df.empty:
        try:
            p_agg = compute_player_aggregates(nfl_stats_df)
            val_df = calculate_player_trade_values(rosters_df, p_agg)
            if not val_df.empty and 'trade_value' in val_df.columns:
                tv_map = dict(zip(val_df['player_id'], val_df['trade_value']))
        except Exception:
            tv_map = {}

    # NFL Season calendar alignment for effective week determination
    # Each fantasy cycle starts on Monday 00:00 UTC (after Sunday games)
    season_str = str(season or datetime.datetime.now().year)
    season_start_defaults = {
        "2026": datetime.datetime(2026, 9, 9, 0, 0, 0),
        "2025": datetime.datetime(2025, 9, 3, 0, 0, 0),
        "2024": datetime.datetime(2024, 9, 5, 0, 0, 0)
    }
    season_start_dt = season_start_defaults.get(season_str, datetime.datetime(int(season_str), 9, 9, 0, 0, 0))
    cycle_start_dt = season_start_dt + datetime.timedelta(days=(7 - season_start_dt.weekday()) % 7)

    def determine_effective_week(created_ms: Optional[int], mtype: str, rnd: int, is_pre: bool) -> Tuple[int, str]:
        if is_pre:
            return 1, "Pre-Season"
        if not created_ms:
            return max(1, rnd), f"Week {max(1, rnd)}"
        dt = datetime.datetime.fromtimestamp(created_ms / 1000.0)
        if dt < season_start_dt:
            return 1, "Pre-Season"
        elif dt < cycle_start_dt:
            return 1, "Week 1"
        else:
            diff_weeks = int((dt - cycle_start_dt).total_seconds() // (7 * 86400))
            calc_wk = diff_weeks + 2
            # Do not project current transactions into future weeks
            calc_wk = min(calc_wk, current_league_week)
            return calc_wk, f"Week {calc_wk}"

    # Sort moves chronologically to build precise add/drop event timelines
    sorted_moves_df = moves_df.sort_values(by=['created_at', 'transaction_id'], ascending=True).copy()

    # Timeline lookup: team_player_drops[roster_id][player_id] = list of drop events
    # team_player_adds[roster_id][player_id] = list of add events
    drops_by_team_player = defaultdict(lambda: defaultdict(list))
    adds_by_team_player = defaultdict(lambda: defaultdict(list))

    for _, r in sorted_moves_df.iterrows():
        raw_adds = json.loads(r['adds']) if r['adds'] else {}
        raw_drops = json.loads(r['drops']) if r['drops'] else {}
        c_ms = r['created_at']
        t_id = r['transaction_id']
        m_tp = r['type']
        r_nd = int(r['round'])
        is_p = bool(r['is_preseason'])
        e_wk, _ = determine_effective_week(c_ms, m_tp, r_nd, is_p)

        for pid, rid in raw_adds.items():
            if rid is not None:
                adds_by_team_player[int(rid)][str(pid)].append({
                    'transaction_id': t_id,
                    'created_at': c_ms or 0,
                    'eff_week': e_wk
                })
        for pid, rid in raw_drops.items():
            if rid is not None:
                drops_by_team_player[int(rid)][str(pid)].append({
                    'transaction_id': t_id,
                    'created_at': c_ms or 0,
                    'eff_week': e_wk
                })

    raw_moves_list = []

    for _, r in moves_df.iterrows():
        raw_adds = json.loads(r['adds']) if r['adds'] else {}
        raw_drops = json.loads(r['drops']) if r['drops'] else {}
        mtype = r['type']
        is_pre = bool(r['is_preseason'])
        rnd = int(r['round'])
        created_ms = r['created_at']

        # Determine effective NFL week and human-readable label
        eff_week, timing_label = determine_effective_week(created_ms, mtype, rnd, is_pre)

        rids = json.loads(r['roster_ids']) if r['roster_ids'] else []

        # For TRADES: EACH participating team gets their own perspective (IN vs OUT)
        if mtype == 'trade' and rids:
            teams_to_process = rids
        else:
            teams_to_process = [rids[0]] if rids else [None]

        # Date formatting in English
        if created_ms:
            dt = datetime.datetime.fromtimestamp(created_ms / 1000.0)
            formatted_date = dt.strftime("%b %d, %H:%M")
        else:
            formatted_date = ""

        waiver_bid = int(r.get('waiver_bid', 0) or 0)

        for rid in teams_to_process:
            team_name = team_name_map.get(rid, f"Team {rid}") if rid is not None else "Unknown"
            owner_name = owner_name_map.get(rid, team_name) if rid is not None else "Unknown"

            if mtype == 'trade':
                team_adds = {pid: to_r for pid, to_r in raw_adds.items() if to_r == rid}
                team_drops = {pid: from_r for pid, from_r in raw_drops.items() if from_r == rid}

                other_rids = [o for o in rids if o != rid]
                partner_names = [team_name_map.get(o, f"Team {o}") for o in other_rids]
                partner_str = ", ".join(partner_names) if partner_names else ""

                category = "Trade"
                category_icon = "🤝"
                n_in = len(team_adds)
                n_out = len(team_drops)
                type_badge = f"{n_in}:{n_out} Trade"
            else:
                team_adds = raw_adds
                team_drops = raw_drops
                partner_str = ""
                n_in = len(team_adds)
                n_out = len(team_drops)

                if team_adds and team_drops:
                    category = "Add & Drop"
                    category_icon = "🔄"
                    type_badge = f"{n_in}:{n_out} Swap" if (n_in != 1 or n_out != 1) else "Add & Drop"
                elif team_adds and not team_drops:
                    category = "Free Add / IR Fill"
                    category_icon = "🆓"
                    type_badge = f"Free Add ({n_in}x)" if n_in > 1 else "Free Add"
                elif team_drops and not team_adds:
                    category = "Pure Drop"
                    category_icon = "✂️"
                    type_badge = f"Pure Drop ({n_out}x)" if n_out > 1 else "Pure Drop"
                else:
                    category = "Other"
                    category_icon = "📝"
                    type_badge = "Roster Move"

            # Skip empty transactions
            if not team_adds and not team_drops:
                continue

            # 1. Added Players Analysis (Incoming Package) with Stint / Tenure Tracking
            added_players_list = []
            pts_in_total = 0.0
            ppg_in_total = 0.0
            started_in_total = 0.0
            bench_in_total = 0.0
            tv_in_total = 0.0

            for pid in team_adds.keys():
                pid_str = str(pid)
                p_info = players_map.get(pid_str, {})
                p_name = p_info.get('full_name', pid_str)
                pos = p_info.get('position', 'WR')
                nfl_t = p_info.get('nfl_team', '')

                if pos == 'DEF' or pid_str == str(nfl_t):
                    hshot = f"https://sleepercdn.com/images/team_logos/nfl/{str(nfl_t).lower()}.png"
                else:
                    hshot = f"https://sleepercdn.com/content/nfl/players/{pid_str}.jpg"

                cur_tv = tv_map.get(pid_str, 1.0)
                tv_in_total += cur_tv

                # Find if/when this team subsequently dropped this player (Stint End)
                future_drops = [
                    d for d in drops_by_team_player[rid][pid_str]
                    if d['created_at'] > (created_ms or 0)
                ]
                if future_drops:
                    # Player was subsequently dropped by this team: stint has concluded
                    first_drop = future_drops[0]
                    drop_eff_wk = first_drop['eff_week']
                    is_p_dropped = True
                    # Player was on roster for weeks: eff_week <= week < drop_eff_wk
                    stint_wks = [w for w in range(eff_week, drop_eff_wk)]
                    if stint_wks:
                        stint_display = f"Wk {min(stint_wks)}–{max(stint_wks)}" if len(stint_wks) > 1 else f"Wk {min(stint_wks)}"
                    else:
                        stint_display = f"Dropped Wk {drop_eff_wk}"
                else:
                    # Player is still on roster for this stint
                    first_drop = None
                    drop_eff_wk = None
                    is_p_dropped = False
                    stint_display = f"Wk {eff_week}–{current_league_week}" if eff_week < current_league_week else f"Wk {eff_week}"

                # Matchup points on fantasy team strictly within stint window
                if is_p_dropped:
                    p_pts_df = matchups_df[
                        (matchups_df['player_id'] == pid_str) &
                        (matchups_df['roster_id'] == rid) &
                        (matchups_df['week'] >= eff_week) &
                        (matchups_df['week'] < drop_eff_wk)
                    ]
                    p_nfl_sub = nfl_stats_df[
                        (nfl_stats_df['player_id'] == pid_str) &
                        (nfl_stats_df['week'] >= eff_week) &
                        (nfl_stats_df['week'] < drop_eff_wk)
                    ] if not nfl_stats_df.empty else pd.DataFrame()
                else:
                    p_pts_df = matchups_df[
                        (matchups_df['player_id'] == pid_str) &
                        (matchups_df['roster_id'] == rid) &
                        (matchups_df['week'] >= eff_week) &
                        (matchups_df['week'] <= current_league_week)
                    ]
                    p_nfl_sub = nfl_stats_df[
                        (nfl_stats_df['player_id'] == pid_str) &
                        (nfl_stats_df['week'] >= eff_week) &
                        (nfl_stats_df['week'] <= current_league_week)
                    ] if not nfl_stats_df.empty else pd.DataFrame()

                st_pts = float(p_pts_df[p_pts_df['started'] == 1]['points'].sum()) if not p_pts_df.empty else 0.0
                bn_pts = float(p_pts_df[p_pts_df['started'] == 0]['points'].sum()) if not p_pts_df.empty else 0.0

                nfl_pts = float(p_nfl_sub['points'].sum()) if not p_nfl_sub.empty else 0.0
                gp = len(p_nfl_sub[p_nfl_sub['points'] > 0]) if not p_nfl_sub.empty else 0
                if nfl_pts > 0 and gp == 0:
                    gp = 1
                ppg = round(nfl_pts / max(1, gp), 1) if nfl_pts > 0 else 0.0

                tot_p_pts = nfl_pts
                pts_in_total += tot_p_pts
                ppg_in_total += ppg
                started_in_total += st_pts
                bench_in_total += bn_pts

                added_players_list.append({
                    'player_id': pid_str,
                    'name': p_name,
                    'position': pos,
                    'nfl_team': nfl_t,
                    'headshot_url': hshot,
                    'trade_value': round(cur_tv, 1),
                    'total_fpts': round(tot_p_pts, 1),
                    'ppg': ppg,
                    'games_played': gp,
                    'started_fpts': round(st_pts, 1),
                    'bench_fpts': round(bn_pts, 1),
                    'is_dropped': is_p_dropped,
                    'drop_eff_week': drop_eff_wk,
                    'stint_display': stint_display
                })

            # Check if entire incoming package has concluded its stint
            if team_adds:
                is_finalized = all(p['is_dropped'] for p in added_players_list)
                move_end_week = max([p['drop_eff_week'] for p in added_players_list if p['drop_eff_week'] is not None]) if is_finalized else current_league_week
            else:
                # Pure Drop: check if manager ever re-acquired the dropped players
                all_readded = True
                readd_wks = []
                for pid in team_drops.keys():
                    fut_adds = [
                        a for a in adds_by_team_player[rid][str(pid)]
                        if a['created_at'] > (created_ms or 0)
                    ]
                    if fut_adds:
                        readd_wks.append(fut_adds[0]['eff_week'])
                    else:
                        all_readded = False
                is_finalized = all_readded and bool(readd_wks)
                move_end_week = max(readd_wks) if is_finalized else current_league_week

            # 2. Dropped / Traded Away Players Analysis (Outgoing Package)
            # Evaluated strictly over the duration that the acquired player was on the roster
            dropped_players_list = []
            pts_out_total = 0.0
            ppg_out_total = 0.0
            tv_out_total = 0.0

            for pid in team_drops.keys():
                pid_str = str(pid)
                p_info = players_map.get(pid_str, {})
                p_name = p_info.get('full_name', pid_str)
                pos = p_info.get('position', 'WR')
                nfl_t = p_info.get('nfl_team', '')

                if pos == 'DEF' or pid_str == str(nfl_t):
                    hshot = f"https://sleepercdn.com/images/team_logos/nfl/{str(nfl_t).lower()}.png"
                else:
                    hshot = f"https://sleepercdn.com/content/nfl/players/{pid_str}.jpg"

                cur_tv = tv_map.get(pid_str, 1.0)
                tv_out_total += cur_tv

                dest_rid = raw_adds.get(pid_str)
                if dest_rid and dest_rid in team_name_map:
                    cur_owner = team_name_map[dest_rid]
                else:
                    cur_owner = current_owner_map.get(pid_str, "Free Agent")

                # Check if this team subsequently re-acquired the dropped player earlier than move_end_week
                fut_readds = [
                    a for a in adds_by_team_player[rid][pid_str]
                    if a['created_at'] > (created_ms or 0)
                ]
                readd_eff_wk = fut_readds[0]['eff_week'] if fut_readds else None
                out_bound_wk = min(move_end_week, readd_eff_wk) if readd_eff_wk else move_end_week

                pts_since_drop = 0.0
                gp_out = 0
                if not nfl_stats_df.empty:
                    if is_finalized:
                        p_nfl_df = nfl_stats_df[
                            (nfl_stats_df['player_id'] == pid_str) &
                            (nfl_stats_df['week'] >= eff_week) &
                            (nfl_stats_df['week'] < out_bound_wk)
                        ]
                    else:
                        p_nfl_df = nfl_stats_df[
                            (nfl_stats_df['player_id'] == pid_str) &
                            (nfl_stats_df['week'] >= eff_week) &
                            (nfl_stats_df['week'] <= current_league_week)
                        ]
                    pts_since_drop = float(p_nfl_df['points'].sum()) if not p_nfl_df.empty else 0.0
                    gp_out = len(p_nfl_df[p_nfl_df['points'] > 0]) if not p_nfl_df.empty else 0
                    if pts_since_drop > 0 and gp_out == 0:
                        gp_out = 1

                ppg_out = round(pts_since_drop / max(1, gp_out), 1) if pts_since_drop > 0 else 0.0

                pts_out_total += pts_since_drop
                ppg_out_total += ppg_out
                tv_out_total += cur_tv

                dropped_players_list.append({
                    'player_id': pid_str,
                    'name': p_name,
                    'position': pos,
                    'nfl_team': nfl_t,
                    'headshot_url': hshot,
                    'trade_value': round(cur_tv, 1),
                    'fpts_since_drop': round(pts_since_drop, 1),
                    'ppg': ppg_out,
                    'games_played': gp_out,
                    'current_owner': cur_owner
                })

            # Calculate Net Points and Net Trade Value
            pts_in_total = round(pts_in_total, 1)
            pts_out_total = round(pts_out_total, 1)
            ppg_in_total = round(ppg_in_total, 1)
            ppg_out_total = round(ppg_out_total, 1)
            started_in_total = round(started_in_total, 1)
            bench_in_total = round(bench_in_total, 1)
            tv_in_total = round(tv_in_total, 1)
            tv_out_total = round(tv_out_total, 1)

            # Determine pending move status:
            # - If move happened for a future week (eff_week > current_league_week): pending
            # - If move happened in current active week and 0 games have completed: pending (unless finalized)
            # - Prior completed weeks (eff_week < current_league_week) are NEVER pending!
            is_pending = False
            total_gp_involved = sum(p['games_played'] for p in added_players_list) + sum(p['games_played'] for p in dropped_players_list)
            if not is_pre:
                if eff_week > current_league_week:
                    is_pending = True
                elif eff_week == current_league_week and not is_finalized:
                    if total_gp_involved == 0:
                        is_pending = True

            # Relative Measure: Net PPG (Avg FPTS per game)
            if category == "Free Add / IR Fill":
                net_ppg = ppg_in_total
                net_fpts = pts_in_total
                net_tv = tv_in_total
            elif category == "Pure Drop":
                net_ppg = -ppg_out_total
                net_fpts = -pts_out_total
                net_tv = -tv_out_total
            else:  # Add & Drop, Trade
                net_ppg = round(ppg_in_total - ppg_out_total, 1)
                net_fpts = round(pts_in_total - pts_out_total, 1)
                net_tv = round(tv_in_total - tv_out_total, 1)

            raw_moves_list.append({
                'transaction_id': r['transaction_id'],
                'created_at': created_ms,
                'formatted_date': formatted_date,
                'timing_label': timing_label,
                'eff_week': eff_week,
                'is_preseason': is_pre,
                'round': rnd,
                'is_pending': is_pending,
                'is_finalized': is_finalized,
                'move_end_week': move_end_week,
                'type': mtype,
                'type_badge': type_badge,
                'waiver_bid': waiver_bid,
                'category': category,
                'category_icon': category_icon,
                'roster_id': rid,
                'team_name': team_name,
                'owner_name': owner_name,
                'partner_name': partner_str,
                'ratio_label': f"{len(added_players_list)}:{len(dropped_players_list)}",
                'added_players': added_players_list,
                'dropped_players': dropped_players_list,
                'ppg_in_total': ppg_in_total,
                'ppg_out_total': ppg_out_total,
                'net_ppg': net_ppg,
                'pts_in_total': pts_in_total,
                'started_in_total': started_in_total,
                'bench_in_total': bench_in_total,
                'pts_out_total': pts_out_total,
                'tv_in_total': tv_in_total,
                'tv_out_total': tv_out_total,
                'net_fpts': net_fpts,
                'net_tv': net_tv
            })

    # DYNAMIC ZERO-CENTERED QUANTILE CALIBRATION
    # Collect completed moves to calculate league-specific percentiles
    completed_moves = [m for m in raw_moves_list if not m['is_pending']]
    pos_moves_ppg = [m['net_ppg'] for m in completed_moves if m['net_ppg'] > 0.5]
    neg_moves_ppg = [m['net_ppg'] for m in completed_moves if m['net_ppg'] < -0.5]

    # Positive Quantiles: B (lower 40%), A (middle 35%), A+ (top 25%)
    if len(pos_moves_ppg) >= 4:
        q_pos_b = round(float(np.percentile(pos_moves_ppg, 40)), 1)
        q_pos_a = round(float(np.percentile(pos_moves_ppg, 75)), 1)
    else:
        q_pos_b = 3.0
        q_pos_a = 7.0

    # Negative Quantiles: D (upper 65%), F (worst 35% of deficits)
    if len(neg_moves_ppg) >= 3:
        q_neg_f = round(float(np.percentile(neg_moves_ppg, 35)), 1)
    else:
        q_neg_f = -6.0

    quantile_thresholds = {
        'pos_b': q_pos_b,
        'pos_a': q_pos_a,
        'neg_f': q_neg_f
    }

    # Assign grades and verdicts based on dynamic zero-centered quantiles
    all_processed_moves = []
    for m in raw_moves_list:
        grade, grade_label, grade_color, verdict = _generate_verdict(
            category=m['category'],
            net_ppg=m['net_ppg'],
            net_fpts=m['net_fpts'],
            net_tv=m['net_tv'],
            ppg_in=m['ppg_in_total'],
            ppg_out=m['ppg_out_total'],
            pts_in=m['pts_in_total'],
            pts_out=m['pts_out_total'],
            started_in=m['started_in_total'],
            added_names=[p['name'] for p in m['added_players']],
            dropped_names=[p['name'] for p in m['dropped_players']],
            partner_name=m['partner_name'],
            is_pending=m['is_pending'],
            is_finalized=m['is_finalized'],
            eff_week=m['eff_week'],
            move_end_week=m['move_end_week'],
            q_thresh=quantile_thresholds
        )
        m_copy = dict(m)
        m_copy['grade'] = grade
        m_copy['grade_label'] = grade_label
        m_copy['grade_color'] = grade_color
        m_copy['verdict'] = verdict
        all_processed_moves.append(m_copy)

    # Available Filter Options
    unique_teams = sorted(list({m['team_name'] for m in all_processed_moves}))
    team_options = ["All Teams"] + unique_teams
    type_options = ["All Types", "Add & Drop", "Free Add / IR Fill", "Pure Drop", "Trades"]

    # Apply Filtering
    filtered_moves = all_processed_moves
    if team_filter and team_filter != "All Teams":
        filtered_moves = [m for m in filtered_moves if m['team_name'] == team_filter]

    if type_filter and type_filter != "All Types":
        if type_filter == "Trades":
            filtered_moves = [m for m in filtered_moves if m['category'] == "Trade"]
        else:
            filtered_moves = [m for m in filtered_moves if m['category'] == type_filter]

    # Apply Sorting
    if sort_by == "best":
        filtered_moves = sorted(filtered_moves, key=lambda m: (m['is_pending'], -m['net_ppg'], -m['net_fpts']))
    elif sort_by == "worst":
        filtered_moves = sorted(filtered_moves, key=lambda m: (m['is_pending'], m['net_ppg'], m['net_fpts']))
    elif sort_by == "net_total":
        filtered_moves = sorted(filtered_moves, key=lambda m: (m['is_pending'], -m['net_fpts']))
    elif sort_by == "net_tv":
        filtered_moves = sorted(filtered_moves, key=lambda m: m['net_tv'], reverse=True)
    else:  # "newest"
        filtered_moves = sorted(filtered_moves, key=lambda m: m['created_at'], reverse=True)

    # Compute KPIs for the current filtered view
    kpis = _compute_move_kpis(filtered_moves, all_processed_moves, team_filter)

    return {
        "moves": filtered_moves,
        "kpis": kpis,
        "team_options": team_options,
        "type_options": type_options,
        "team_filter": team_filter,
        "quantile_thresholds": quantile_thresholds
    }


def _generate_verdict(
    category: str,
    net_ppg: float,
    net_fpts: float,
    net_tv: float,
    ppg_in: float,
    ppg_out: float,
    pts_in: float,
    pts_out: float,
    started_in: float,
    added_names: List[str],
    dropped_names: List[str],
    partner_name: Optional[str] = None,
    is_pending: bool = False,
    is_finalized: bool = False,
    eff_week: int = 1,
    move_end_week: int = 1,
    q_thresh: Optional[Dict[str, float]] = None
) -> Tuple[str, str, str, str]:
    """
    Determine move grade (A+ to F) using Zero-Centered Dynamic Quantiles.
    Ranks relative performance within positive and negative curves without outlier distortion.
    Appends tenure finalization context when acquired players have concluded their roster stint.
    """
    add_str = _format_names(added_names)
    drop_str = _format_names(dropped_names)

    if is_pending:
        tv_desc = f" (Trade Value Delta: {net_tv:+.1f})" if net_tv != 0 else ""
        return "⏳", "Pending", "#64748b", f"Pending: Games for Week {eff_week} have not completed yet. Points and PPG will accumulate after games conclude{tv_desc}."

    th = q_thresh or {'pos_b': 3.0, 'pos_a': 7.0, 'neg_f': -6.0}
    q_b = th.get('pos_b', 3.0)
    q_a = th.get('pos_a', 7.0)
    q_f = th.get('neg_f', -6.0)

    # Note appended to finalized/closed moves
    final_tag = f" [Final: Stint concluded in Week {move_end_week}]" if is_finalized else ""

    # 1. FREE ADD / IR FILL
    if category == "Free Add / IR Fill":
        if net_ppg >= q_a or net_tv >= 25.0:
            return "A+", "Jackpot", "#15803d", f"Jackpot Pickup: {add_str} produced {ppg_in:.1f} PPG with zero acquisition cost (TV {net_tv}).{final_tag}"
        elif net_ppg >= q_b or net_tv >= 15.0:
            return "A", "Top Pickup", "#15803d", f"Top Pickup: {add_str} contributed {ppg_in:.1f} PPG (+{net_fpts:.1f} total pts) as key depth.{final_tag}"
        elif net_ppg > 0.5:
            return "B", "Net Positive", "#2563eb", f"Solid Depth: {add_str} averaged {ppg_in:.1f} PPG.{final_tag}"
        else:
            return "C", "Depth Fill", "#64748b", f"Depth Add: {add_str} recorded minimal fantasy production ({ppg_in:.1f} PPG).{final_tag}"

    # 2. PURE DROP
    elif category == "Pure Drop":
        if net_ppg <= q_f:
            return "F", "Costly Drop", "#b91c1c", f"Costly Drop: {drop_str} put up starter numbers ({ppg_out:.1f} PPG, +{pts_out:.1f} pts) after being cut!{final_tag}"
        elif net_ppg < -0.5:
            return "D", "Lost Depth", "#b45309", f"Lost Depth: {drop_str} produced {ppg_out:.1f} PPG for subsequent teams.{final_tag}"
        else:
            return "C", "Clean Cut", "#64748b", f"Clean Cut: {drop_str} averaged just {ppg_out:.1f} PPG ({pts_out:.1f} pts) after release.{final_tag}"

    # 3. TRADES
    elif category == "Trade":
        partner_txt = f" to {partner_name}" if partner_name else ""
        if net_ppg >= q_a or (net_ppg >= q_b and net_tv >= 20.0):
            return "A+", "Trade Steal", "#15803d", f"Trade Steal: {net_ppg:+.1f} Net PPG (Top 25% of league moves)! {add_str} ({ppg_in:.1f} PPG) vastly outproduced {drop_str} ({ppg_out:.1f} PPG).{final_tag}"
        elif net_ppg >= q_b:
            return "A", "Great Trade", "#15803d", f"Strong Trade: {net_ppg:+.1f} Net PPG edge gained via {add_str}.{final_tag}"
        elif net_ppg > 0.5:
            return "B", "Trade Win", "#2563eb", f"Trade Win: {net_ppg:+.1f} PPG advantage for {add_str} ({ppg_in:.1f} PPG) over {drop_str} ({ppg_out:.1f} PPG).{final_tag}"
        elif -0.5 <= net_ppg <= 0.5:
            return "C", "Fair Trade", "#64748b", f"Fair Trade: Virtually identical production ({net_ppg:+.1f} PPG) between {add_str} ({ppg_in:.1f}) and {drop_str} ({ppg_out:.1f}).{final_tag}"
        elif net_ppg > q_f:
            return "D", "Trade Loss", "#b45309", f"Trade Deficit: {drop_str} ({ppg_out:.1f} PPG{partner_txt}) outscored {add_str} ({ppg_in:.1f} PPG) by {abs(net_ppg):.1f} PPG.{final_tag}"
        else:
            return "F", "Trade Disaster", "#b91c1c", f"Trade Disaster: {net_ppg:+.1f} Net PPG margin. {drop_str} traded away{partner_txt} heavily outperformed {add_str}.{final_tag}"

    # 4. ADD & DROP (SWAPS)
    else:
        if net_ppg >= q_a or (net_ppg >= q_b and net_tv >= 20.0):
            return "A+", "League Winner", "#15803d", f"League Winner: {net_ppg:+.1f} Net PPG (Top 25% of league moves)! {add_str} ({ppg_in:.1f} PPG) heavily outscored {drop_str} ({ppg_out:.1f} PPG).{final_tag}"
        elif net_ppg >= q_b:
            return "A", "Great Upgrade", "#15803d", f"Clear Upgrade: {net_ppg:+.1f} Net PPG advantage gained from roster swap.{final_tag}"
        elif net_ppg > 0.5:
            return "B", "Positive Value", "#2563eb", f"Positive Move: {net_ppg:+.1f} PPG edge ({add_str}: {ppg_in:.1f} vs {drop_str}: {ppg_out:.1f}).{final_tag}"
        elif -0.5 <= net_ppg <= 0.5:
            return "C", "Neutral Swap", "#64748b", f"Neutral Swap: Negligible differential ({net_ppg:+.1f} PPG) between {add_str} and {drop_str}.{final_tag}"
        elif net_ppg > q_f:
            return "D", "Drop Regret", "#b45309", f"Drop Regret: {drop_str} ({ppg_out:.1f} PPG) outperformed {add_str} ({ppg_in:.1f} PPG) by {abs(net_ppg):.1f} PPG.{final_tag}"
        else:
            return "F", "Major Blunder", "#b91c1c", f"Major Blunder: {net_ppg:+.1f} Net PPG deficit. Dropping {drop_str} ({ppg_out:.1f} PPG) proved costly.{final_tag}"


def _compute_move_kpis(
    current_moves: List[Dict[str, Any]],
    all_moves: List[Dict[str, Any]],
    team_filter: Optional[str] = None
) -> Dict[str, Any]:
    """Compute summary KPIs for top cards including Best Manager ranking based on PPG."""
    is_single_team = bool(team_filter and team_filter != "All Teams")

    if not current_moves:
        return {
            "total_moves": 0,
            "net_ppg_avg": 0.0,
            "net_fpts_total": 0.0,
            "best_move": None,
            "worst_move": None,
            "most_active_team": "None",
            "most_active_count": 0,
            "free_adds_count": 0,
            "is_single_team": is_single_team,
            "win_rate": 0,
            "pos_moves": 0,
            "comp_moves": 0,
            "net_tv_total": 0.0,
            "best_manager": None,
            "single_team_rank": None,
            "single_team_manager_stat": None,
            "total_teams_count": 0
        }

    total_moves = len(current_moves)
    completed_moves = [m for m in current_moves if not m.get('is_pending', False)]
    eval_pool = completed_moves if completed_moves else current_moves

    # Relative PPG average across moves
    net_ppg_sum = sum(m['net_ppg'] for m in eval_pool)
    net_ppg_avg = round(net_ppg_sum / len(eval_pool), 1) if eval_pool else 0.0
    net_fpts_total = round(sum(m['net_fpts'] for m in current_moves), 1)
    net_tv_total = round(sum(m['net_tv'] for m in current_moves), 1)

    # Best & Worst Moves based primarily on Net PPG
    sorted_by_ppg = sorted(eval_pool, key=lambda m: (m['net_ppg'], m['net_fpts']), reverse=True)
    best_move = sorted_by_ppg[0] if sorted_by_ppg else None
    worst_move = sorted_by_ppg[-1] if sorted_by_ppg else None

    # Free adds count
    free_adds = sum(1 for m in current_moves if m['category'] == "Free Add / IR Fill")

    # Team activity
    team_counts = {}
    for m in current_moves:
        team_counts[m['team_name']] = team_counts.get(m['team_name'], 0) + 1

    most_active_team = max(team_counts, key=team_counts.get) if team_counts else "None"
    most_active_count = team_counts.get(most_active_team, 0)

    # Win Rate based on Net PPG > 0.5
    pos_moves = sum(1 for m in completed_moves if m['net_ppg'] > 0.5)
    comp_moves = len(completed_moves)
    win_rate = round((pos_moves / comp_moves) * 100) if comp_moves > 0 else 0

    # Best Manager Evaluation across ALL moves
    team_manager_stats = {}
    for m in all_moves:
        tname = m['team_name']
        if tname not in team_manager_stats:
            team_manager_stats[tname] = {
                'team_name': tname,
                'owner_name': m.get('owner_name', tname),
                'total_moves': 0,
                'completed_moves': 0,
                'net_ppg_sum': 0.0,
                'net_fpts': 0.0,
                'net_tv': 0.0,
                'wins': 0,
                'losses': 0,
                'ties': 0
            }
        team_manager_stats[tname]['total_moves'] += 1
        team_manager_stats[tname]['net_fpts'] += m['net_fpts']
        team_manager_stats[tname]['net_tv'] += m['net_tv']
        if not m.get('is_pending', False):
            team_manager_stats[tname]['completed_moves'] += 1
            team_manager_stats[tname]['net_ppg_sum'] += m['net_ppg']
            if m['net_ppg'] > 0.5:
                team_manager_stats[tname]['wins'] += 1
            elif m['net_ppg'] < -0.5:
                team_manager_stats[tname]['losses'] += 1
            else:
                team_manager_stats[tname]['ties'] += 1

    for tname in team_manager_stats:
        c_cnt = team_manager_stats[tname]['completed_moves']
        team_manager_stats[tname]['avg_net_ppg'] = round(team_manager_stats[tname]['net_ppg_sum'] / max(1, c_cnt), 1)
        team_manager_stats[tname]['net_fpts'] = round(team_manager_stats[tname]['net_fpts'], 1)
        team_manager_stats[tname]['net_tv'] = round(team_manager_stats[tname]['net_tv'], 1)

    # Sort all teams primarily by cumulative profit and average Net PPG
    sorted_managers = sorted(
        team_manager_stats.values(),
        key=lambda x: (x['net_fpts'], x['avg_net_ppg']),
        reverse=True
    )

    best_manager = sorted_managers[0] if sorted_managers else None

    # Single team league rank
    single_team_rank = None
    single_team_manager_stat = None
    if is_single_team and team_filter in team_manager_stats:
        for idx, m_stat in enumerate(sorted_managers, 1):
            if m_stat['team_name'] == team_filter:
                single_team_rank = idx
                single_team_manager_stat = m_stat
                break

    return {
        "total_moves": total_moves,
        "net_ppg_avg": net_ppg_avg,
        "net_fpts_total": net_fpts_total,
        "net_tv_total": net_tv_total,
        "best_move": best_move,
        "worst_move": worst_move,
        "most_active_team": most_active_team,
        "most_active_count": most_active_count,
        "free_adds_count": free_adds,
        "is_single_team": is_single_team,
        "win_rate": win_rate,
        "pos_moves": pos_moves,
        "comp_moves": comp_moves,
        "best_manager": best_manager,
        "single_team_rank": single_team_rank,
        "single_team_manager_stat": single_team_manager_stat,
        "total_teams_count": len(sorted_managers)
    }


def render_roster_moves_html(analytics: Dict[str, Any], owner_colors: Optional[Dict[str, str]] = None) -> str:
    """
    Generate high-density, compact table view matching Team Analytics roster table.
    Shows Relative Measures (Net PPG / Avg FPTS) with dynamic quantile grading.
    Displays tenure indicators (Dropped Wk X vs Active) and move finalization status.
    """
    moves = analytics.get("moves", [])
    kpis = analytics.get("kpis", {})

    total_moves = kpis.get("total_moves", 0)
    net_ppg_avg = kpis.get("net_ppg_avg", 0.0)
    net_fpts_total = kpis.get("net_fpts_total", 0.0)
    net_tv_total = kpis.get("net_tv_total", 0.0)
    best = kpis.get("best_move")
    worst = kpis.get("worst_move")
    is_single_team = kpis.get("is_single_team", False)
    best_manager = kpis.get("best_manager")
    single_team_rank = kpis.get("single_team_rank")
    single_stat = kpis.get("single_team_manager_stat")
    total_teams_cnt = kpis.get("total_teams_count", 0)

    owner_col_map = owner_colors or {}

    net_avg_color = "#16a34a" if net_ppg_avg >= 0 else "#dc2626"
    net_avg_prefix = "+" if net_ppg_avg > 0 else ""

    # TOP KPI CARDS
    # 1. Best Move (Highest Net PPG)
    if best:
        add_n = _format_names([p['name'] for p in best['added_players']])
        drop_n = _format_names([p['name'] for p in best['dropped_players']])
        b_team = best['team_name']
        b_owner = best.get('owner_name', '')
        b_owner_txt = f" ({b_owner})" if b_owner and b_owner != b_team else ""
        b_team_dot = f"<span style='display:inline-block; width:9px; height:9px; border-radius:50%; background-color:{owner_col_map.get(b_team, '#16a34a')}; margin-right:5px;'></span>"
        
        detail_txt = f"{add_n} ({best['ppg_in_total']} PPG) vs {drop_n} ({best['ppg_out_total']} PPG)" if drop_n != "None" else f"{add_n} ({best['ppg_in_total']} PPG)"
        title_display = f"{b_team_dot}{b_team}<span style='font-size:0.78rem; font-weight:600; color:#64748b;'>{b_owner_txt}</span>" if not is_single_team else f"{add_n}"
        
        best_card_html = f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                <span style="font-size:0.75rem; font-weight:700; color:#15803d; text-transform:uppercase; letter-spacing:0.04em;">👑 Best Move</span>
                <span style="background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; font-weight:800; font-size:0.72rem; padding:2px 7px; border-radius:6px;">{best['grade']}</span>
            </div>
            <div>
                <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    {title_display}
                </div>
                <div style="font-size:0.88rem; font-weight:800; color:#16a34a; margin-bottom:2px;">
                    +{best['net_ppg']} <span style="font-size:0.74rem; font-weight:600; color:#64748b;">Net PPG ({best['timing_label']})</span>
                </div>
                <div style="font-size:0.74rem; color:#64748b; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{detail_txt}">
                    {detail_txt}
                </div>
            </div>
        </div>
        """
    else:
        best_card_html = """
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:700; color:#15803d; text-transform:uppercase;">👑 Best Move</div>
            <div style="font-size:0.9rem; color:#94a3b8; margin-top:8px;">No Move Evaluated</div>
        </div>
        """

    # 2. Worst Move (Lowest Net PPG)
    if worst:
        add_nw = _format_names([p['name'] for p in worst['added_players']])
        drop_nw = _format_names([p['name'] for p in worst['dropped_players']])
        w_team = worst['team_name']
        w_owner = worst.get('owner_name', '')
        w_owner_txt = f" ({w_owner})" if w_owner and w_owner != w_team else ""
        w_team_dot = f"<span style='display:inline-block; width:9px; height:9px; border-radius:50%; background-color:{owner_col_map.get(w_team, '#dc2626')}; margin-right:5px;'></span>"

        detail_txt_w = f"{add_nw} ({worst['ppg_in_total']} PPG) vs {drop_nw} ({worst['ppg_out_total']} PPG)" if add_nw != "None" else f"Drop: {drop_nw} ({worst['ppg_out_total']} PPG)"
        title_display_w = f"{w_team_dot}{w_team}<span style='font-size:0.78rem; font-weight:600; color:#64748b;'>{w_owner_txt}</span>" if not is_single_team else f"{drop_nw}"

        worst_card_html = f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                <span style="font-size:0.75rem; font-weight:700; color:#dc2626; text-transform:uppercase; letter-spacing:0.04em;">💔 Worst Move</span>
                <span style="background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; font-weight:800; font-size:0.72rem; padding:2px 7px; border-radius:6px;">{worst['grade']}</span>
            </div>
            <div>
                <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    {title_display_w}
                </div>
                <div style="font-size:0.88rem; font-weight:800; color:#dc2626; margin-bottom:2px;">
                    {worst['net_ppg']} <span style="font-size:0.74rem; font-weight:600; color:#64748b;">Net PPG ({worst['timing_label']})</span>
                </div>
                <div style="font-size:0.74rem; color:#64748b; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{detail_txt_w}">
                    {detail_txt_w}
                </div>
            </div>
        </div>
        """
    else:
        worst_card_html = """
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:700; color:#dc2626; text-transform:uppercase;">💔 Worst Move</div>
            <div style="font-size:0.9rem; color:#94a3b8; margin-top:8px;">No Move Evaluated</div>
        </div>
        """

    # 3. Transactions Total (Average Net PPG & Totals)
    total_card_html = f"""
    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
        <div style="font-size:0.75rem; font-weight:700; color:#475569; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;">📊 Transactions</div>
        <div>
            <div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{total_moves} <span style="font-size:0.8rem; font-weight:600; color:#64748b;">Moves</span></div>
            <div style="font-size:0.84rem; font-weight:700; color:{net_avg_color}; margin-bottom:2px;">{net_avg_prefix}{net_ppg_avg} Net PPG Avg</div>
            <div style="font-size:0.74rem; color:#64748b;">{net_fpts_total:+.1f} Net FPTS • {kpis.get('free_adds_count', 0)} Free Adds</div>
        </div>
    </div>
    """

    # 4. Activity / Success Rate Card
    if is_single_team:
        win_rate = kpis.get("win_rate", 0)
        pos_moves = kpis.get("pos_moves", 0)
        comp_moves = kpis.get("comp_moves", 0)
        tv_sign = "+" if net_tv_total > 0 else ""
        tv_col = "#7c3aed" if net_tv_total >= 0 else "#b45309"

        fourth_card_html = f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
            <div style="font-size:0.75rem; font-weight:700; color:#0284c7; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;">🎯 Move Success Rate</div>
            <div>
                <div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{win_rate}% <span style="font-size:0.8rem; font-weight:600; color:#64748b;">Win Rate</span></div>
                <div style="font-size:0.84rem; font-weight:700; color:#0284c7; margin-bottom:2px;">{pos_moves} of {comp_moves} Positive</div>
                <div style="font-size:0.74rem; color:{tv_col}; font-weight:600;">{tv_sign}{net_tv_total} Total TV Delta</div>
            </div>
        </div>
        """
    else:
        most_active = kpis.get("most_active_team", "None")
        most_active_cnt = kpis.get("most_active_count", 0)
        fourth_card_html = f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
            <div style="font-size:0.75rem; font-weight:700; color:#0284c7; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;">🔥 Most Active Team</div>
            <div>
                <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    <span style='display:inline-block; width:9px; height:9px; border-radius:50%; background-color:{owner_col_map.get(most_active, "#0284c7")}; margin-right:5px;'></span>{most_active}
                </div>
                <div style="font-size:0.84rem; font-weight:700; color:#0284c7; margin-bottom:2px;">{most_active_cnt} Transactions</div>
                <div style="font-size:0.74rem; color:#64748b;">Highest move volume in league</div>
            </div>
        </div>
        """

    # 5. Best Manager / League Standing Card
    if is_single_team and single_stat:
        rank_txt = f"#{single_team_rank}" if single_team_rank else "N/A"
        tm_avg_ppg = single_stat.get('avg_net_ppg', 0.0)
        tm_sign = "+" if tm_avg_ppg > 0 else ""
        tm_col = "#16a34a" if tm_avg_ppg >= 0 else "#dc2626"

        fifth_card_html = f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                <span style="font-size:0.75rem; font-weight:700; color:#ea580c; text-transform:uppercase; letter-spacing:0.04em;">🏆 GM Ranking</span>
                <span style="background:#fff7ed; border:1px solid #ffedd5; color:#ea580c; font-weight:800; font-size:0.72rem; padding:2px 7px; border-radius:6px;">{rank_txt} of {total_teams_cnt}</span>
            </div>
            <div>
                <div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{rank_txt} <span style="font-size:0.8rem; font-weight:600; color:#64748b;">in GM Efficiency</span></div>
                <div style="font-size:0.84rem; font-weight:700; color:{tm_col}; margin-bottom:2px;">{tm_sign}{tm_avg_ppg} Net PPG/Move</div>
                <div style="font-size:0.74rem; color:#64748b;">{single_stat['wins']}-{single_stat['losses']} Record ({single_stat['completed_moves']} graded)</div>
            </div>
        </div>
        """
    elif best_manager:
        bm_team = best_manager['team_name']
        bm_owner = best_manager.get('owner_name', '')
        bm_owner_txt = f" ({bm_owner})" if bm_owner and bm_owner != bm_team else ""
        bm_dot = f"<span style='display:inline-block; width:9px; height:9px; border-radius:50%; background-color:{owner_col_map.get(bm_team, '#ea580c')}; margin-right:5px;'></span>"
        bm_avg_ppg = best_manager['avg_net_ppg']
        bm_sign = "+" if bm_avg_ppg > 0 else ""
        bm_col = "#16a34a" if bm_avg_ppg >= 0 else "#dc2626"
        bm_pts = best_manager['net_fpts']
        bm_pts_sign = "+" if bm_pts > 0 else ""

        fifth_card_html = f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
            <div style="font-size:0.75rem; font-weight:700; color:#ea580c; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;">🏆 Best GM</div>
            <div>
                <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                    {bm_dot}{bm_team}<span style='font-size:0.78rem; font-weight:600; color:#64748b;'>{bm_owner_txt}</span>
                </div>
                <div style="font-size:0.84rem; font-weight:800; color:{bm_col}; margin-bottom:2px;">{bm_sign}{bm_avg_ppg} Net PPG/Move</div>
                <div style="font-size:0.74rem; color:#64748b;">{bm_pts_sign}{bm_pts} Net FPTS • {best_manager['wins']}-{best_manager['losses']} Record</div>
            </div>
        </div>
        """
    else:
        fifth_card_html = """
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
            <div style="font-size:0.75rem; font-weight:700; color:#ea580c; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:4px;">🏆 Best Manager</div>
            <div>
                <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">No Moves Yet</div>
                <div style="font-size:0.84rem; font-weight:600; color:#64748b; margin-bottom:2px;">No moves evaluated</div>
                <div style="font-size:0.74rem; color:#94a3b8;">Ranked by Net PPG & Net FPTS</div>
            </div>
        </div>
        """

    # COMPACT TABLE ROWS BUILDER
    table_rows = []
    for m in moves:
        is_pending = m.get('is_pending', False)
        is_finalized = m.get('is_finalized', False)

        # Grade pill styling
        g_badge = m['grade']
        if g_badge in ["A+", "A"]:
            g_bg, g_border, g_col = "#f0fdf4", "#bbf7d0", "#15803d"
        elif g_badge == "B":
            g_bg, g_border, g_col = "#eff6ff", "#bfdbfe", "#1d4ed8"
        elif g_badge == "C":
            g_bg, g_border, g_col = "#f8fafc", "#e2e8f0", "#475569"
        elif g_badge == "D":
            g_bg, g_border, g_col = "#fffbeb", "#fde68a", "#b45309"
        elif g_badge == "F":
            g_bg, g_border, g_col = "#fef2f2", "#fecaca", "#b91c1c"
        else:  # Pending
            g_bg, g_border, g_col = "#f1f5f9", "#e2e8f0", "#64748b"

        # Primary Relative Measure Pill (Net PPG) + Secondary Total Context
        if is_pending:
            score_pill_html = "<span style='background:#f1f5f9; border:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; font-weight:700; padding:2px 7px; border-radius:6px; display:inline-block; white-space:nowrap;'>⏳ Pending</span>"
            math_sub_html = f"<div style='font-size:0.68rem; color:#7c3aed; font-weight:600; margin-top:2px;'>TV {m['net_tv']:+.1f}</div>"
        else:
            if m['net_ppg'] > 0:
                score_pill_html = f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; font-size:0.8rem; font-weight:800; padding:2px 8px; border-radius:6px; display:inline-block; white-space:nowrap;'>+{m['net_ppg']} PPG</span>"
            elif m['net_ppg'] < 0:
                score_pill_html = f"<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; font-size:0.8rem; font-weight:800; padding:2px 8px; border-radius:6px; display:inline-block; white-space:nowrap;'>{m['net_ppg']} PPG</span>"
            else:
                score_pill_html = "<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#64748b; font-size:0.76rem; font-weight:700; padding:2px 7px; border-radius:6px; display:inline-block; white-space:nowrap;'>0.0 PPG</span>"
            
            fpts_prefix = "+" if m['net_fpts'] > 0 else ""
            math_sub_html = f"<div style='font-size:0.68rem; color:#64748b; margin-top:2px;' title='Cumulative Points'>{fpts_prefix}{m['net_fpts']} tot pts</div>"

        # Move lifecycle badge (Finalized Stint vs Active Roster vs Pending)
        if is_pending:
            lifecycle_sub = "<div style='font-size:0.63rem; color:#94a3b8; font-weight:700; text-transform:uppercase; margin-top:2px;'>Pending</div>"
        elif is_finalized:
            lifecycle_sub = f"<div style='font-size:0.63rem; color:#64748b; font-weight:700; text-transform:uppercase; margin-top:2px;' title='Acquired player was dropped. Grading finalized.'>Final (Wk {m['move_end_week']})</div>"
        else:
            lifecycle_sub = "<div style='font-size:0.63rem; color:#0284c7; font-weight:700; text-transform:uppercase; margin-top:2px;'>Active</div>"

        # Team Cell
        t_dot = f"<span style='display:inline-block; width:8px; height:8px; border-radius:50%; background-color:{owner_col_map.get(m['team_name'], '#3b82f6')}; margin-right:4px;'></span>"
        if m['category'] == 'Trade' and m.get('partner_name'):
            team_cell_html = f"""
            <div style="font-weight:700; color:#0f172a; font-size:0.82rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{m['team_name']}">
                {t_dot}{m['team_name']}
            </div>
            <div style="font-size:0.7rem; color:#64748b; margin-top:1px;">
                🤝 w/ <strong>{m['partner_name']}</strong>
            </div>
            """
        else:
            team_cell_html = f"""
            <div style="font-weight:700; color:#0f172a; font-size:0.82rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{m['team_name']}">
                {t_dot}{m['team_name']}
            </div>
            """

        # Type Pill
        if m['type'] == 'waiver':
            type_pill = f"<span style='background:#f5f3ff; border:1px solid #ddd6fe; color:#6d28d9; font-weight:700; font-size:0.7rem; padding:2px 6px; border-radius:6px; display:inline-block; white-space:nowrap;'>Waiver</span>"
            if m['waiver_bid'] > 0:
                type_pill += f"<div style='font-size:0.68rem; color:#6d28d9; font-weight:600; margin-top:1px;'>${m['waiver_bid']} FAAB</div>"
        elif m['type'] == 'free_agent':
            type_pill = f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; font-weight:700; font-size:0.7rem; padding:2px 6px; border-radius:6px; display:inline-block; white-space:nowrap;'>Free Agent</span>"
        else:
            type_pill = f"<span style='background:#eff6ff; border:1px solid #bfdbfe; color:#1d4ed8; font-weight:700; font-size:0.7rem; padding:2px 6px; border-radius:6px; display:inline-block; white-space:nowrap;'>{m['type_badge']}</span>"

        # 1. Added Players (IN) Cell with Tenure Indicators
        adds_cells = []
        for p in m['added_players']:
            if p.get('is_dropped'):
                tenure_badge = f"<span style='font-size:0.62rem; font-weight:700; background:#f1f5f9; color:#475569; border:1px solid #e2e8f0; padding:0 4px; border-radius:3px; margin-left:4px;' title='Player was subsequently dropped'>Dropped Wk {p.get('drop_eff_week')}</span>"
                stint_txt = f"({p['games_played']} GP in {p.get('stint_display', '')} • {p['total_fpts']} pts)"
            else:
                tenure_badge = "<span style='font-size:0.62rem; font-weight:700; background:#f0fdf4; color:#15803d; border:1px solid #bbf7d0; padding:0 4px; border-radius:3px; margin-left:4px;'>Active</span>"
                stint_txt = f"({p['games_played']} GP • {p['total_fpts']} pts)"

            adds_cells.append(f"""
            <div style="display:flex; align-items:center; gap:8px; margin:2px 0;">
                <img src="{p['headshot_url']}" style="width:28px; height:28px; border-radius:50%; object-fit:cover; background:#e2e8f0; border:1px solid #86efac; flex-shrink:0;" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp';"/>
                <div style="min-width:0;">
                    <div style="display:flex; align-items:center; gap:4px; flex-wrap:nowrap;">
                        <span style="font-weight:700; color:#0f172a; font-size:0.82rem; white-space:nowrap;">{p['name']}</span>
                        <span style="font-size:0.65rem; font-weight:700; background:#e0f2fe; color:#0369a1; padding:0 4px; border-radius:3px;">{p['position']}</span>
                        {tenure_badge}
                    </div>
                    <div style="font-size:0.7rem; color:#64748b;">
                        <strong style="color:#16a34a;">{p['ppg']} PPG</strong> <span style="color:#94a3b8;">{stint_txt}</span> • TV {p['trade_value']}
                    </div>
                </div>
            </div>
            """)
        if len(m['added_players']) > 1:
            adds_cells.append(f"<div style='font-size:0.68rem; font-weight:700; color:#16a34a; margin-top:2px;'>Pkg Total: {m['ppg_in_total']} PPG (+{m['pts_in_total']} pts) • TV {m['tv_in_total']}</div>")
        adds_html = "".join(adds_cells) if adds_cells else "<span style='color:#94a3b8; font-size:0.75rem; font-style:italic;'>None</span>"

        # 2. Dropped Players (OUT) Cell
        drops_cells = []
        for p in m['dropped_players']:
            drops_cells.append(f"""
            <div style="display:flex; align-items:center; gap:8px; margin:2px 0;">
                <img src="{p['headshot_url']}" style="width:28px; height:28px; border-radius:50%; object-fit:cover; background:#e2e8f0; border:1px solid #fca5a5; flex-shrink:0;" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp';"/>
                <div style="min-width:0;">
                    <div style="display:flex; align-items:center; gap:4px; flex-wrap:nowrap;">
                        <span style="font-weight:700; color:#0f172a; font-size:0.82rem; white-space:nowrap;">{p['name']}</span>
                        <span style="font-size:0.65rem; font-weight:700; background:#fee2e2; color:#b91c1c; padding:0 4px; border-radius:3px;">{p['position']}</span>
                    </div>
                    <div style="font-size:0.7rem; color:#64748b;">
                        <strong style="color:#dc2626;">{p['ppg']} PPG</strong> <span style="color:#94a3b8;">({p['games_played']} GP • {p['fpts_since_drop']} pts)</span> • TV {p['trade_value']}
                    </div>
                </div>
            </div>
            """)
        if len(m['dropped_players']) > 1:
            drops_cells.append(f"<div style='font-size:0.68rem; font-weight:700; color:#dc2626; margin-top:2px;'>Pkg Total: {m['ppg_out_total']} PPG (+{m['pts_out_total']} pts) • TV {m['tv_out_total']}</div>")
        drops_html = "".join(drops_cells) if drops_cells else "<span style='color:#94a3b8; font-size:0.75rem; font-style:italic;'>None (Free/IR)</span>"

        row_html = f"""
        <tr style="border-bottom: 1px solid #f1f5f9; transition: background-color 0.15s ease;" onmouseover="this.style.backgroundColor='#f8fafc'" onmouseout="this.style.backgroundColor='transparent'">
            <td style="padding: 10px 12px; white-space: nowrap;">
                <div style="font-weight: 700; color: #0f172a; font-size: 0.8rem;">{m['timing_label']}</div>
                <div style="font-size: 0.7rem; color: #94a3b8; margin-top: 1px;">{m['formatted_date']}</div>
            </td>
            <td style="padding: 10px 12px; max-width: 140px;">
                {team_cell_html}
            </td>
            <td style="padding: 10px 10px; text-align: center;">
                {type_pill}
            </td>
            <td style="padding: 10px 12px; min-width: 200px;">
                {adds_html}
            </td>
            <td style="padding: 10px 12px; min-width: 200px;">
                {drops_html}
            </td>
            <td style="padding: 10px 12px; text-align: right; white-space: nowrap;">
                {score_pill_html}
                {math_sub_html}
            </td>
            <td style="padding: 10px 10px; text-align: center;">
                <span style="background:{g_bg}; border:1px solid {g_border}; color:{g_col}; font-weight:800; font-size:0.78rem; padding:2px 7px; border-radius:6px; display:inline-block;">{g_badge}</span>
                {lifecycle_sub}
            </td>
            <td style="padding: 10px 14px; min-width: 240px; font-size: 0.76rem; color: #334155; line-height: 1.4;">
                {m['verdict']}
            </td>
        </tr>
        """
        table_rows.append(row_html)

    table_body = "".join(table_rows) if table_rows else """
    <tr>
        <td colspan="8" style="text-align:center; padding:36px; color:#64748b; font-size:0.9rem;">
            No moves found matching the selected filter criteria.
        </td>
    </tr>
    """

    full_table_html = f"""
    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-bottom:18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);">
        <div style="background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;">
            <span>📜 Roster Move Log</span>
            <span style="font-size:0.75rem; color:#64748b; font-weight:600;">{total_moves} Moves</span>
        </div>
        <div style="overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; font-size:0.82rem;">
                <thead>
                    <tr style="background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.5px;">
                        <th style="padding:10px 12px; text-align:left; width:100px;">When</th>
                        <th style="padding:10px 12px; text-align:left; width:140px;">Team</th>
                        <th style="padding:10px 10px; text-align:center; width:95px;">Type</th>
                        <th style="padding:10px 12px; text-align:left;">Players Added (IN)</th>
                        <th style="padding:10px 12px; text-align:left;">Players Dropped (OUT)</th>
                        <th style="padding:10px 12px; text-align:right; width:115px;">Net PPG</th>
                        <th style="padding:10px 10px; text-align:center; width:75px;">Grade</th>
                        <th style="padding:10px 14px; text-align:left; min-width:240px;">Analysis / Verdict</th>
                    </tr>
                </thead>
                <tbody>
                    {table_body}
                </tbody>
            </table>
        </div>
    </div>
    """

    full_view_html = f"""
    <div style="display:flex; flex-direction:column; gap:16px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; width:100%;">
        <!-- Top KPI Grid (5 Cards: Best Move, Worst Move, Transactions, Activity/Success, Best Manager) -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; width:100%;">
            {best_card_html}
            {worst_card_html}
            {total_card_html}
            {fourth_card_html}
            {fifth_card_html}
        </div>

        <!-- High-Density Compact Moves Table -->
        {full_table_html}
    </div>
    """
    return full_view_html
