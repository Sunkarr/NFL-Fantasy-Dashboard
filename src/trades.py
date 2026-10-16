import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
import numpy as np


def calculate_player_trade_values(
    df_rosters: pd.DataFrame,
    df_player_stats: pd.DataFrame,
    mode: str = "ppg",
    scoring_settings: Optional[Dict[str, float]] = None,
    projections: Optional[Dict[str, Any]] = None,
    include_free_agents: bool = True
) -> pd.DataFrame:
    """
    Calculate market trade values (0 - 100 scale) for all rostered and active free agent players.
    Incorporates:
    - Base production (PPG / Projections)
    - Positional Scarcity Weight (RB/WR/TE carry high trade premium vs QB/K/DEF)
    - Value Over Replacement Player (VORP) baseline
    - Elite Tier Multiplier (Top 5 assets have exponentially higher value)
    - Injury Status discount
    - Positional Percentiles (contextual rank within position)
    """
    df = df_rosters.copy() if df_rosters is not None and not df_rosters.empty else pd.DataFrame()
    if 'player_id' in df.columns:
        df['player_id'] = df['player_id'].astype(str)

    # Include active unowned / free agent players so their trade / market value is fully evaluated
    if include_free_agents and df_player_stats is not None and not df_player_stats.empty:
        rostered_pids = set(df['player_id'].astype(str)) if 'player_id' in df.columns else set()
        fa_players = df_player_stats[
            ~df_player_stats['player_id'].astype(str).isin(rostered_pids) &
            (df_player_stats['mean_points'] > 0)
        ].copy()
        if not fa_players.empty:
            fa_rows = []
            for _, r in fa_players.iterrows():
                fa_rows.append({
                    'player_id': str(r['player_id']),
                    'player_name': str(r.get('player_name', r['player_id'])),
                    'position': str(r.get('position', 'WR')),
                    'nfl_team': str(r.get('nfl_team', 'FA')),
                    'team_name': 'Free Agent',
                    'owner_name': 'Free Agent',
                    'roster_id': None,
                    'is_starter': 0,
                    'is_reserve': 0,
                    'injury_status': str(r.get('injury_status', 'Healthy'))
                })
            df = pd.concat([df, pd.DataFrame(fa_rows)], ignore_index=True)

    if df.empty:
        return pd.DataFrame()

    if df_player_stats is not None and not df_player_stats.empty:
        stats_cols = [
            "player_id", "mean_points", "std_points", "games_played",
            "pos_rank", "headshot_url"
        ]
        available_cols = [col for col in stats_cols if col in df_player_stats.columns]
        cols_to_drop = [c for c in available_cols if c != "player_id" and c in df.columns]
        if cols_to_drop:
            df = df.drop(columns=cols_to_drop)

        df['player_id'] = df['player_id'].astype(str)
        df_stats_copy = df_player_stats[available_cols].copy()
        df_stats_copy['player_id'] = df_stats_copy['player_id'].astype(str)
        df = df.merge(df_stats_copy, on="player_id", how="left")

    # Fill defaults
    if "position" not in df.columns:
        df["position"] = "WR"
    else:
        df["position"] = df["position"].fillna("WR")

    if "player_name" not in df.columns:
        df["player_name"] = df["player_id"].astype(str)
    else:
        df["player_name"] = df["player_name"].fillna(df["player_id"].astype(str))

    if "mean_points" not in df.columns:
        df["mean_points"] = 0.0
    else:
        df["mean_points"] = df["mean_points"].fillna(0.0)

    if "std_points" not in df.columns:
        df["std_points"] = 0.0
    else:
        df["std_points"] = df["std_points"].fillna(0.0)

    if "games_played" not in df.columns:
        df["games_played"] = 0
    else:
        df["games_played"] = df["games_played"].fillna(0).astype(int)

    if "pos_rank" not in df.columns:
        df["pos_rank"] = 99
    else:
        df["pos_rank"] = df["pos_rank"].fillna(99).astype(int)

    if "injury_status" not in df.columns:
        df["injury_status"] = "Healthy"
    else:
        df["injury_status"] = df["injury_status"].fillna("Healthy")

    # Determine baseline score for trade evaluation
    if mode == "projection" and isinstance(projections, dict) and bool(projections):
        proj_scores = []
        for pid in df["player_id"]:
            p_val = float(projections.get(str(pid), projections.get(int(pid) if str(pid).isdigit() else "", 0.0)))
            proj_scores.append(p_val)
        df["score"] = proj_scores
        # Fallback to mean_points if projection is missing/zero
        df["score"] = np.where(df["score"] > 0, df["score"], df["mean_points"])
    else:
        df["score"] = df["mean_points"]

    # Positional Replacement Baselines in a 6-team league (Waiver wire replacement level)
    # In a 6-team league, replacement levels are high, making elite studs even more valuable
    replacement_baselines = {
        "QB": 14.5,
        "RB": 7.5,
        "WR": 8.0,
        "TE": 5.5,
        "K": 6.5,
        "DEF": 5.5
    }

    # Positional Scarcity Multipliers:
    # RB: Hardest position to replace, high injury volatility, high demand
    # TE: Elite TEs provide massive positional advantage
    # WR: High depth, but top WRs are dependable anchors
    # QB: In 1-QB leagues, streamable depth is abundant
    scarcity_weights = {
        "RB": 1.45,
        "WR": 1.30,
        "TE": 1.35,
        "QB": 0.85,
        "K": 0.30,
        "DEF": 0.40
    }

    trade_values = []
    baselines = []
    weights = []
    vorps = []
    elite_mults = []
    inj_discounts = []

    for _, row in df.iterrows():
        pos = str(row.get("position", "WR")).upper()
        pts = float(row.get("score", 0.0)) if pd.notna(row.get("score")) else 0.0
        rk_val = row.get("pos_rank", 99)
        rk = int(rk_val) if pd.notna(rk_val) else 99
        inj = str(row.get("injury_status", "Healthy"))

        baseline = replacement_baselines.get(pos, 8.0)
        weight = scarcity_weights.get(pos, 1.0)

        # Value Over Replacement (VORP)
        vorp = max(0.0, pts - baseline)

        # Raw value calculation
        raw_val = (vorp * 3.5 * weight) + (pts * 1.1 * weight)

        # Elite rank bonuses (Top tier game-changers have exponential trade leverage)
        elite_mult = 1.00
        if pos in ["RB", "WR"]:
            if rk <= 3:
                elite_mult = 1.35
            elif rk <= 6:
                elite_mult = 1.22
            elif rk <= 12:
                elite_mult = 1.12
            elif rk <= 20:
                elite_mult = 1.05
        elif pos == "TE":
            if rk <= 2:
                elite_mult = 1.40
            elif rk <= 5:
                elite_mult = 1.20
        elif pos == "QB":
            if rk <= 2:
                elite_mult = 1.25
            elif rk <= 5:
                elite_mult = 1.10

        raw_val *= elite_mult

        # Injury discount
        inj_mult = 1.00
        if inj in ["Out", "IR", "PUP", "Doubtful", "NA", "Sus"]:
            inj_mult = 0.60
        elif inj == "Questionable":
            inj_mult = 0.90

        raw_val *= inj_mult

        trade_values.append(raw_val)
        baselines.append(round(baseline, 1))
        weights.append(round(weight, 2))
        vorps.append(round(vorp, 1))
        elite_mults.append(round(elite_mult, 2))
        inj_discounts.append(round(inj_mult, 2))

    df["raw_trade_value"] = trade_values
    df["baseline"] = baselines
    df["scarcity_weight"] = weights
    df["vorp"] = vorps
    df["elite_multiplier"] = elite_mults
    df["injury_discount"] = inj_discounts

    # Normalize to 0 - 100 scale
    max_raw = max(df["raw_trade_value"].max(), 1.0)
    df["trade_value"] = ((df["raw_trade_value"] / max_raw) * 98.0).round(1)
    df["trade_value"] = df["trade_value"].clip(lower=1.0)

    # Calculate positional percentile within all rostered players at that position
    if "score" in df.columns and "position" in df.columns:
        df["pos_percentile"] = (
            df.groupby("position")["score"].rank(pct=True, ascending=True) * 100.0
        ).round(0).fillna(50).astype(int)
    else:
        df["pos_percentile"] = 50

    # Ensure headshot_url exists
    if "headshot_url" not in df.columns or df["headshot_url"].isna().any():
        df["headshot_url"] = df.apply(
            lambda r: f"https://sleepercdn.com/images/team_logos/nfl/{str(r.get('nfl_team', '')).lower()}.png"
            if r.get("position") == "DEF" or str(r.get("player_id")) == str(r.get("nfl_team"))
            else f"https://sleepercdn.com/content/nfl/players/{r.get('player_id')}.jpg",
            axis=1
        )

    return df


def solve_optimal_lineup(
    players_df: pd.DataFrame,
    score_col: str = "score"
) -> Dict[str, Any]:
    """
    Solve for the optimal starting lineup for a roster:
    1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 K, 1 DEF.
    Remaining players are placed on the bench.
    """
    if players_df is None or players_df.empty:
        return {
            "starters": [],
            "bench": [],
            "starter_score": 0.0,
            "bench_score": 0.0,
            "starter_trade_value": 0.0,
            "total_trade_value": 0.0,
            "by_slot": {}
        }

    df = players_df.copy()
    if score_col not in df.columns:
        df[score_col] = 0.0
    if "trade_value" not in df.columns:
        df["trade_value"] = 1.0

    df = df.sort_values(by=score_col, ascending=False).reset_index(drop=True)

    assigned_ids: Set[str] = set()
    starters: List[Dict[str, Any]] = []
    by_slot: Dict[str, Dict[str, Any]] = {}

    def pick_best(pos: str, slot_name: str) -> Optional[Dict[str, Any]]:
        cands = df[(df["position"] == pos) & (~df["player_id"].astype(str).isin(assigned_ids))]
        if not cands.empty:
            p = cands.iloc[0].to_dict()
            p["slot"] = slot_name
            assigned_ids.add(str(p["player_id"]))
            starters.append(p)
            by_slot[slot_name] = p
            return p
        return None

    # Core starting positions
    pick_best("QB", "QB")
    pick_best("RB", "RB_1")
    pick_best("RB", "RB_2")
    pick_best("WR", "WR_1")
    pick_best("WR", "WR_2")
    pick_best("TE", "TE")

    # FLEX (RB, WR, TE)
    flex_cands = df[
        (df["position"].isin(["RB", "WR", "TE"])) &
        (~df["player_id"].astype(str).isin(assigned_ids))
    ]
    if not flex_cands.empty:
        p = flex_cands.iloc[0].to_dict()
        p["slot"] = "FLEX"
        assigned_ids.add(str(p["player_id"]))
        starters.append(p)
        by_slot["FLEX"] = p

    # K & DEF
    pick_best("K", "K")
    pick_best("DEF", "DEF")

    # Bench
    bench: List[Dict[str, Any]] = []
    bench_cands = df[~df["player_id"].astype(str).isin(assigned_ids)]
    for _, r in bench_cands.iterrows():
        b = r.to_dict()
        b["slot"] = "BN"
        bench.append(b)

    starter_score = round(sum(float(p.get(score_col, 0.0)) for p in starters), 1)
    bench_score = round(sum(float(p.get(score_col, 0.0)) for p in bench), 1)
    starter_tv = round(sum(float(p.get("trade_value", 0.0)) for p in starters), 1)
    total_tv = round(sum(float(p.get("trade_value", 0.0)) for p in starters + bench), 1)

    return {
        "starters": starters,
        "bench": bench,
        "starter_score": starter_score,
        "bench_score": bench_score,
        "starter_trade_value": starter_tv,
        "total_trade_value": total_tv,
        "by_slot": by_slot
    }


def analyze_team_needs_and_surplus(
    df_teams: pd.DataFrame,
    df_rosters: pd.DataFrame,
    df_player_stats: pd.DataFrame,
    mode: str = "ppg",
    scoring_settings: Optional[Dict[str, float]] = None,
    projections: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Perform deep positional surplus & deficit analysis for all teams in the league.
    Identifies:
    - High-surplus positions (excess depth, trade bait)
    - Deficit / need positions (lineup holes, low starter output)
    - Bench trade chips
    """
    if df_teams is None or df_teams.empty or df_rosters is None or df_rosters.empty:
        return {}

    val_df = calculate_player_trade_values(
        df_rosters, df_player_stats, mode=mode,
        scoring_settings=scoring_settings, projections=projections
    )

    team_lineups: Dict[str, Dict[str, Any]] = {}
    team_pos_starter_scores: Dict[str, Dict[str, float]] = {}
    team_pos_bench_scores: Dict[str, Dict[str, List[float]]] = {}
    team_pos_players: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    positions = ["QB", "RB", "WR", "TE"]

    for t_name in df_teams["team_name"].unique():
        t_players = val_df[val_df["team_name"] == t_name].copy()
        lineup = solve_optimal_lineup(t_players, score_col="score")
        team_lineups[t_name] = lineup

        starter_pos_map: Dict[str, List[float]] = {p: [] for p in positions}
        for st in lineup["starters"]:
            pos = st.get("position")
            if pos in positions:
                starter_pos_map[pos].append(float(st.get("score", 0.0)))

        bench_pos_map: Dict[str, List[float]] = {p: [] for p in positions}
        pos_players_map: Dict[str, List[Dict[str, Any]]] = {p: [] for p in positions}

        for bn in lineup["bench"]:
            pos = bn.get("position")
            if pos in positions:
                bench_pos_map[pos].append(float(bn.get("score", 0.0)))
                pos_players_map[pos].append(bn)

        for st in lineup["starters"]:
            pos = st.get("position")
            if pos in positions:
                pos_players_map[pos].append(st)

        team_pos_starter_scores[t_name] = {p: (np.mean(scs) if scs else 0.0) for p, scs in starter_pos_map.items()}
        team_pos_bench_scores[t_name] = bench_pos_map
        team_pos_players[t_name] = pos_players_map

    # Calculate league averages for each position's starters
    league_pos_avg_starters: Dict[str, float] = {}
    for pos in positions:
        all_st_scores = [team_pos_starter_scores[t][pos] for t in team_pos_starter_scores if team_pos_starter_scores[t][pos] > 0]
        league_pos_avg_starters[pos] = float(np.mean(all_st_scores)) if all_st_scores else 0.0

    # Classify each team's position as Surplus, Deficit/Need, or Balanced
    team_profiles: Dict[str, Dict[str, Any]] = {}
    for t_name in df_teams["team_name"].unique():
        t_row = df_teams[df_teams["team_name"] == t_name].iloc[0]
        owner = str(t_row.get("owner_name", t_name))
        lineup = team_lineups[t_name]

        pos_analysis: Dict[str, Dict[str, Any]] = {}
        surplus_positions: List[str] = []
        need_positions: List[str] = []
        trade_bait: List[Dict[str, Any]] = []

        for pos in positions:
            st_avg = team_pos_starter_scores[t_name].get(pos, 0.0)
            lg_avg = league_pos_avg_starters.get(pos, 0.0)
            diff = round(st_avg - lg_avg, 1)

            b_scores = sorted(team_pos_bench_scores[t_name].get(pos, []), reverse=True)
            bench_count = len(b_scores)
            bench_max = b_scores[0] if b_scores else 0.0

            # Start-worthy bench benchmark
            sw_threshold = lg_avg * 0.85
            start_worthy_bench = [
                p for p in team_pos_players[t_name].get(pos, [])
                if p.get("slot") == "BN" and float(p.get("score", 0.0)) >= sw_threshold
            ]

            status = "Balanced"
            status_code = "neutral"
            badge_color = "#475569"

            total_players = team_pos_players[t_name].get(pos, [])

            if pos in ["QB", "TE"]:
                # Single starter positions
                if len(start_worthy_bench) >= 1 or (diff >= 3.0 and bench_count >= 1):
                    status = "Major Surplus"
                    status_code = "major_surplus"
                    badge_color = "#15803d"
                    surplus_positions.append(pos)
                    for sw in start_worthy_bench:
                        trade_bait.append(sw)
                elif diff >= 2.0:
                    status = "Surplus"
                    status_code = "surplus"
                    badge_color = "#16a34a"
                    surplus_positions.append(pos)
                elif diff <= -3.0:
                    status = "Major Need"
                    status_code = "major_need"
                    badge_color = "#dc2626"
                    need_positions.append(pos)
                elif diff <= -1.2:
                    status = "Need Upgrade"
                    status_code = "need"
                    badge_color = "#ea580c"
                    need_positions.append(pos)
            else:
                # RB and WR
                if len(start_worthy_bench) >= 2 or (diff >= 2.0 and len(start_worthy_bench) >= 1):
                    status = "Major Surplus"
                    status_code = "major_surplus"
                    badge_color = "#15803d"
                    surplus_positions.append(pos)
                    for sw in start_worthy_bench:
                        trade_bait.append(sw)
                elif len(start_worthy_bench) >= 1 or diff >= 2.5:
                    status = "Surplus"
                    status_code = "surplus"
                    badge_color = "#16a34a"
                    surplus_positions.append(pos)
                    for sw in start_worthy_bench:
                        trade_bait.append(sw)
                elif diff <= -3.0 or (diff <= -1.5 and bench_count == 0):
                    status = "Major Need"
                    status_code = "major_need"
                    badge_color = "#dc2626"
                    need_positions.append(pos)
                elif diff <= -1.2:
                    status = "Need Upgrade"
                    status_code = "need"
                    badge_color = "#ea580c"
                    need_positions.append(pos)

            pos_analysis[pos] = {
                "position": pos,
                "starter_avg_ppg": round(st_avg, 1),
                "league_avg_ppg": round(lg_avg, 1),
                "diff_vs_league": diff,
                "bench_count": bench_count,
                "bench_max_ppg": round(bench_max, 1),
                "start_worthy_bench_count": len(start_worthy_bench),
                "status": status,
                "status_code": status_code,
                "badge_color": badge_color,
                "players": total_players
            }

        # Deduplicate trade bait
        unique_bait = []
        seen_pids = set()
        for b in sorted(trade_bait, key=lambda x: float(x.get("trade_value", 0.0)), reverse=True):
            if b["player_id"] not in seen_pids:
                seen_pids.add(b["player_id"])
                unique_bait.append(b)

        # Use official roster bench PPG from get_team_roster_analytics to ensure 100% consistency across League Overview & Trade Finder
        try:
            from src.stats import get_team_roster_analytics
            an = get_team_roster_analytics(t_name, df_rosters, df_player_stats, df_teams)
            bench_pts = round(float(an["bench_ppg"]), 1) if an else lineup["bench_score"]
        except Exception:
            bench_pts = lineup["bench_score"]

        team_profiles[t_name] = {
            "team_name": t_name,
            "owner_name": owner,
            "lineup": lineup,
            "starter_score": lineup["starter_score"],
            "bench_score": bench_pts,
            "total_trade_value": lineup["total_trade_value"],
            "pos_analysis": pos_analysis,
            "surplus_positions": surplus_positions,
            "need_positions": need_positions,
            "trade_bait": unique_bait
        }

    return {
        "league_benchmarks": league_pos_avg_starters,
        "team_profiles": team_profiles,
        "val_df": val_df
    }


def simulate_custom_trade(
    team_a_name: str,
    team_b_name: str,
    team_a_pids: List[str],
    team_b_pids: List[str],
    df_teams: pd.DataFrame,
    df_rosters: pd.DataFrame,
    df_player_stats: pd.DataFrame,
    mode: str = "ppg",
    scoring_settings: Optional[Dict[str, float]] = None,
    projections: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Simulate a custom fantasy trade between Team A and Team B.
    Calculates direct net player production (PPG delta), starting lineup impact,
    trade value equity, and tactical recommendation.
    """
    if not team_a_name or not team_b_name or team_a_name == team_b_name:
        return {}

    val_df = calculate_player_trade_values(
        df_rosters, df_player_stats, mode=mode,
        scoring_settings=scoring_settings, projections=projections
    )

    t_a_orig = val_df[val_df["team_name"] == team_a_name].copy()
    t_b_orig = val_df[val_df["team_name"] == team_b_name].copy()

    if t_a_orig.empty or t_b_orig.empty:
        return {}

    # Initial lineups
    lineup_a_before = solve_optimal_lineup(t_a_orig, score_col="score")
    lineup_b_before = solve_optimal_lineup(t_b_orig, score_col="score")

    # Selected players
    pids_a_set = set(str(pid) for pid in team_a_pids)
    pids_b_set = set(str(pid) for pid in team_b_pids)

    players_a_sends = t_a_orig[t_a_orig["player_id"].astype(str).isin(pids_a_set)].to_dict("records")
    players_b_sends = t_b_orig[t_b_orig["player_id"].astype(str).isin(pids_b_set)].to_dict("records")

    if not players_a_sends and not players_b_sends:
        return {
            "valid": False,
            "reason": "Please select at least one player to trade from either team."
        }

    # Simulate rosters after trade
    t_a_kept = t_a_orig[~t_a_orig["player_id"].astype(str).isin(pids_a_set)].copy()
    t_b_received = t_b_orig[t_b_orig["player_id"].astype(str).isin(pids_b_set)].copy()
    t_a_after = pd.concat([t_a_kept, t_b_received], ignore_index=True)

    t_b_kept = t_b_orig[~t_b_orig["player_id"].astype(str).isin(pids_b_set)].copy()
    t_a_received = t_a_orig[t_a_orig["player_id"].astype(str).isin(pids_a_set)].copy()
    t_b_after = pd.concat([t_b_kept, t_a_received], ignore_index=True)

    # Solve lineups after trade
    lineup_a_after = solve_optimal_lineup(t_a_after, score_col="score")
    lineup_b_after = solve_optimal_lineup(t_b_after, score_col="score")

    # Starting Lineup Metrics
    starter_diff_a = round(lineup_a_after["starter_score"] - lineup_a_before["starter_score"], 2)
    starter_diff_b = round(lineup_b_after["starter_score"] - lineup_b_before["starter_score"], 2)

    # Trade Value Metrics
    val_a_sends = round(sum(float(p.get("trade_value", 0.0)) for p in players_a_sends), 1)
    val_b_sends = round(sum(float(p.get("trade_value", 0.0)) for p in players_b_sends), 1)

    # Direct Net Player PPG Production (without starter/bench distinction)
    ppg_a_sends = round(sum(float(p.get("score", 0.0)) for p in players_a_sends), 1)
    ppg_b_sends = round(sum(float(p.get("score", 0.0)) for p in players_b_sends), 1)
    ppg_net_a = round(ppg_b_sends - ppg_a_sends, 1)
    ppg_net_b = round(ppg_a_sends - ppg_b_sends, 1)

    # Average Positional Percentiles of packages
    pct_a_sends = int(round(sum(float(p.get("pos_percentile", 50)) for p in players_a_sends) / max(len(players_a_sends), 1)))
    pct_b_sends = int(round(sum(float(p.get("pos_percentile", 50)) for p in players_b_sends) / max(len(players_b_sends), 1)))

    max_tv = max(val_a_sends, val_b_sends, 1.0)
    min_tv = min(val_a_sends, val_b_sends)
    fairness_pct = int(round((min_tv / max_tv) * 100))

    # Lineup changes breakdown
    def extract_lineup_moves(b_slot, a_slot):
        moves = []
        for s, p_new in a_slot.items():
            p_old = b_slot.get(s)
            if not p_old or str(p_old.get("player_id")) != str(p_new.get("player_id")):
                old_name = p_old.get("player_name", "Empty") if p_old else "Empty"
                diff_pts = round(float(p_new.get("score", 0.0)) - float(p_old.get("score", 0.0) if p_old else 0.0), 1)
                moves.append({
                    "slot": s,
                    "new_player": p_new.get("player_name"),
                    "old_player": old_name,
                    "diff": diff_pts
                })
        return moves

    moves_a = extract_lineup_moves(lineup_a_before["by_slot"], lineup_a_after["by_slot"])
    moves_b = extract_lineup_moves(lineup_b_before["by_slot"], lineup_b_after["by_slot"])

    # Determine Verdict
    if starter_diff_a > 0 and starter_diff_b > 0:
        verdict = "🌟 Mutual Win-Win: Both teams upgrade their starting lineup!"
        verdict_color = "#15803d"
    elif starter_diff_a > 0 and starter_diff_b >= -0.5:
        verdict = f"🟢 Favorable for {team_a_name}: Lineup boosted with acceptable loss for {team_b_name}."
        verdict_color = "#16a34a"
    elif starter_diff_b > 0 and starter_diff_a >= -0.5:
        verdict = f"🟢 Favorable for {team_b_name}: Lineup boosted with acceptable loss for {team_a_name}."
        verdict_color = "#16a34a"
    elif starter_diff_a < -1.0 and starter_diff_b < -1.0:
        verdict = "⚠️ Inefficient Trade: Both teams lose starting output (bench depth trap)."
        verdict_color = "#b91c1c"
    elif fairness_pct < 65:
        favored = team_a_name if val_b_sends > val_a_sends else team_b_name
        verdict = f"⚖️ Unbalanced Trade Value: Favors {favored} in raw asset equity ({fairness_pct}% match)."
        verdict_color = "#b45309"
    else:
        verdict = f"⚖️ Fair Asset Exchange ({fairness_pct}% Trade Value Match)."
        verdict_color = "#2563eb"

    return {
        "valid": True,
        "team_a": team_a_name,
        "team_b": team_b_name,
        "players_a_sends": players_a_sends,
        "players_b_sends": players_b_sends,
        "ppg_a_sends": ppg_a_sends,
        "ppg_b_sends": ppg_b_sends,
        "ppg_net_a": ppg_net_a,
        "ppg_net_b": ppg_net_b,
        "pct_a_sends": pct_a_sends,
        "pct_b_sends": pct_b_sends,
        "val_a_sends": val_a_sends,
        "val_b_sends": val_b_sends,
        "fairness_pct": fairness_pct,
        "lineup_a_before": lineup_a_before,
        "lineup_a_after": lineup_a_after,
        "lineup_b_before": lineup_b_before,
        "lineup_b_after": lineup_b_after,
        "starter_diff_a": starter_diff_a,
        "starter_diff_b": starter_diff_b,
        "moves_a": moves_a,
        "moves_b": moves_b,
        "verdict": verdict,
        "verdict_color": verdict_color
    }


def generate_trade_recommendations(
    df_teams: pd.DataFrame,
    df_rosters: pd.DataFrame,
    df_player_stats: pd.DataFrame,
    focus_team: Optional[str] = None,
    mode: str = "ppg",
    scoring_settings: Optional[Dict[str, float]] = None,
    projections: Optional[Dict[str, Any]] = None,
    max_recs: int = 15
) -> List[Dict[str, Any]]:
    """
    Algorithmic Trade Matchmaker:
    Proposes win-win deals matching complementary surplus & deficit positions.
    Evaluates:
    - Balanced 1-for-1 swaps
    - 2-for-1 star consolidation packages
    """
    analysis = analyze_team_needs_and_surplus(
        df_teams, df_rosters, df_player_stats, mode=mode,
        scoring_settings=scoring_settings, projections=projections
    )
    if not analysis:
        return []

    team_profiles = analysis["team_profiles"]
    val_df = analysis["val_df"]
    recommendations: List[Dict[str, Any]] = []
    seen_trade_signatures: Set[str] = set()

    all_teams = list(team_profiles.keys())

    for i in range(len(all_teams)):
        t_a = all_teams[i]
        if focus_team and focus_team != "All Teams" and focus_team != t_a:
            continue

        for j in range(len(all_teams)):
            if i == j:
                continue
            t_b = all_teams[j]
            if focus_team and focus_team != "All Teams" and focus_team not in (t_a, t_b):
                continue

            prof_a = team_profiles[t_a]
            prof_b = team_profiles[t_b]

            # Check for mutual complement
            a_gives_pos = [p for p in prof_a["surplus_positions"] if p in prof_b["need_positions"]]
            b_gives_pos = [p for p in prof_b["surplus_positions"] if p in prof_a["need_positions"]]

            if not a_gives_pos and not b_gives_pos:
                continue

            # Candidate players
            cands_a = val_df[(val_df["team_name"] == t_a) & (val_df["position"].isin(a_gives_pos or prof_a["surplus_positions"]))].to_dict("records")
            cands_b = val_df[(val_df["team_name"] == t_b) & (val_df["position"].isin(b_gives_pos or prof_b["surplus_positions"]))].to_dict("records")

            if not cands_a or not cands_b:
                continue

            # Explore 1-for-1 swaps
            for p_a in cands_a:
                for p_b in cands_b:
                    # Guard 1: Never trade a position to a team that already has a surplus in it
                    if p_a["position"] in prof_b["surplus_positions"]:
                        continue
                    if p_b["position"] in prof_a["surplus_positions"]:
                        continue

                    # Guard 2: If a team has designated needs, incoming player must address one of those needs
                    if prof_a["need_positions"] and p_b["position"] not in prof_a["need_positions"]:
                        continue
                    if prof_b["need_positions"] and p_a["position"] not in prof_b["need_positions"]:
                        continue

                    pid_a = str(p_a["player_id"])
                    pid_b = str(p_b["player_id"])

                    sig = tuple(sorted([f"{t_a}:{pid_a}", f"{t_b}:{pid_b}"]))
                    if sig in seen_trade_signatures:
                        continue

                    # Simulate trade
                    res = simulate_custom_trade(
                        team_a_name=t_a,
                        team_b_name=t_b,
                        team_a_pids=[pid_a],
                        team_b_pids=[pid_b],
                        df_teams=df_teams,
                        df_rosters=df_rosters,
                        df_player_stats=df_player_stats,
                        mode=mode
                    )

                    if not res.get("valid"):
                        continue

                    diff_a = res["starter_diff_a"]
                    diff_b = res["starter_diff_b"]
                    fair_pct = res["fairness_pct"]

                    # Filter: Strictly mutual win-win (both starting lineups improve) and fair trade equity
                    if fair_pct >= 65 and diff_a > 0 and diff_b > 0:
                        seen_trade_signatures.add(sig)

                        # Tagging
                        tags = []
                        tags.append("🌟 Mutual Win-Win")
                        if p_a["position"] in prof_b["need_positions"] and p_b["position"] in prof_a["need_positions"]:
                            tags.append("🎯 Perfect Positional Fit")
                        if fair_pct >= 88:
                            tags.append("⚖️ High Equity")
                        if max(p_a["trade_value"], p_b["trade_value"]) >= 40:
                            tags.append("💎 Blockbuster")

                        def _fmt_side(team, p_sent, p_rec, diff, prof):
                            if p_rec["position"] in prof["need_positions"]:
                                return f"{team} addresses need at {p_rec['position']} ({diff:+.1f} pts)"
                            return f"{team} upgrades {p_rec['position']} ({diff:+.1f} pts)"

                        reason = f"{_fmt_side(t_a, p_a, p_b, diff_a, prof_a)}, while {_fmt_side(t_b, p_b, p_a, diff_b, prof_b)}." 

                        recommendations.append({
                            "type": "1_for_1",
                            "team_a": t_a,
                            "team_b": t_b,
                            "player_a": p_a,
                            "player_b": p_b,
                            "starter_diff_a": diff_a,
                            "starter_diff_b": diff_b,
                            "fairness_pct": fair_pct,
                            "tags": tags,
                            "reason": reason,
                            "score": (diff_a + diff_b) * 10 + (fair_pct / 5)
                        })

    # Sort recommendations by highest mutual net gain and trade fairness
    recommendations = sorted(recommendations, key=lambda x: x["score"], reverse=True)
    return recommendations[:max_recs]


def render_trade_finder_view(
    analysis: Dict[str, Any],
    recommendations: List[Dict[str, Any]],
    calc_result: Optional[Dict[str, Any]],
    calc_team_a_control: Any,
    calc_team_b_control: Any,
    calc_pids_a_control: Any,
    calc_pids_b_control: Any,
    owner_colors: Dict[str, str],
    mo: Any
) -> Any:
    """
    Renders the complete 🤝 Trade Finder & Team Needs Analyzer dashboard view.
    Sections:
    1. Top KPI Summary Grid
    2. Positional Surplus vs. Deficit Matrix Table
    3. AI Trade Target Matchmaker (Top Win-Win Recommendations)
    4. Interactive Trade Value Calculator & Lineup Simulator
    """
    if not analysis or "team_profiles" not in analysis:
        return mo.Html("<div style='padding:24px; text-align:center; color:#64748b;'>No team analysis available.</div>")

    team_profiles = analysis["team_profiles"]
    val_df = analysis.get("val_df", pd.DataFrame())
    benchmarks = analysis.get("league_benchmarks", {})

    # Top KPI Metrics
    win_win_count = sum(1 for r in recommendations if r.get("starter_diff_a", 0) > 0 and r.get("starter_diff_b", 0) > 0)
    
    top_asset = None
    if not val_df.empty:
        top_asset_row = val_df.sort_values(by="trade_value", ascending=False).iloc[0]
        top_asset = f"{top_asset_row['player_name']} ({top_asset_row['trade_value']:.1f} TV)"

    deepest_team = None
    max_bench = -1
    for t_n, prof in team_profiles.items():
        if prof["bench_score"] > max_bench:
            max_bench = prof["bench_score"]
            deepest_team = t_n

    top_buyer = None
    max_needs = -1
    for t_n, prof in team_profiles.items():
        if len(prof["need_positions"]) > max_needs:
            max_needs = len(prof["need_positions"])
            top_buyer = t_n

    kpi_html = f"""
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:12px; width:100%; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:600; color:#15803d; text-transform:uppercase;">🌟 Win-Win Matches</div>
            <div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{win_win_count} Trades Found</div>
            <div style="font-size:0.75rem; color:#16a34a; font-weight:600;">Both rosters upgrade starters</div>
        </div>
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:600; color:#7c3aed; text-transform:uppercase;">👑 #1 Trade Asset</div>
            <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{top_asset or 'N/A'}</div>
            <div style="font-size:0.75rem; color:#64748b;">Highest league trade value</div>
        </div>
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:600; color:#2563eb; text-transform:uppercase;">🪵 Deepest Bench Depth</div>
            <div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{deepest_team or 'N/A'}</div>
            <div style="font-size:0.75rem; color:#64748b;">{max_bench:.1f} Bench PPG • Prime Seller</div>
        </div>
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:600; color:#ea580c; text-transform:uppercase;">🎯 High Need Partner</div>
            <div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{top_buyer or 'N/A'}</div>
            <div style="font-size:0.75rem; color:#64748b;">{max_needs} Deficit Areas • Eager Buyer</div>
        </div>
    </div>
    """

    # SECTION 1: Positional Needs & Surplus Matrix (Decluttered modern build matching Weekly Matrix)
    matrix_rows = []
    positions = ["QB", "RB", "WR", "TE"]

    # Find position leaders (#1 starter PPG) for crown highlights
    pos_max: Dict[str, float] = {}
    for pos in positions:
        pos_scores = [prof["pos_analysis"].get(pos, {}).get("starter_avg_ppg", 0.0) for prof in team_profiles.values()]
        pos_max[pos] = max(pos_scores) if pos_scores else 0.0

    for t_name, prof in team_profiles.items():
        t_dot = f"<span style='display:inline-block; width:10px; height:10px; border-radius:50%; background-color:{owner_colors.get(t_name, '#3b82f6')};'></span>"
        
        pos_cells = []
        for pos in positions:
            p_data = prof["pos_analysis"].get(pos, {})
            code = p_data.get("status_code", "neutral")
            status = p_data.get("status", "Balanced")
            diff = p_data.get("diff_vs_league", 0.0)
            st_avg = p_data.get("starter_avg_ppg", 0.0)
            bench_cnt = p_data.get("bench_count", 0)

            if code in ["major_surplus", "surplus"]:
                _status_text = "Surplus"
                _status_color = "#16a34a"
                _cell_bg = "rgba(22, 163, 74, 0.12)" if code == "major_surplus" else "rgba(22, 163, 74, 0.09)"
            elif code in ["major_need", "need"]:
                _status_text = "Deficit"
                _status_color = "#dc2626"
                _cell_bg = "rgba(220, 38, 38, 0.11)" if code == "major_need" else "rgba(220, 38, 38, 0.08)"
            else:
                _status_text = "Even"
                _status_color = "#64748b"
                _cell_bg = "transparent"

            is_top = (st_avg == pos_max.get(pos, -999) and st_avg > 0)
            crown_html = (
                f"<span style='font-size:0.8rem; margin-left:3px;' title='Position Starter Leader (#1 {pos})'>👑</span>"
                if is_top else ""
            )

            diff_str = f"+{diff:.1f}" if diff > 0 else f"{diff:.1f}"
            tooltip = f"{pos}: {st_avg:.1f} PPG ({diff_str} vs league starter avg {benchmarks.get(pos, 0.0):.1f}) • {status} • {bench_cnt} on bench"

            cell_html = f"""<td style="padding:8px 8px; text-align:center; vertical-align:middle; background:{_cell_bg}; border-left:1px solid #f8fafc; border-right:1px solid #f8fafc;"><div style="display:flex; flex-direction:column; align-items:center; gap:2px;" title="{tooltip}"><div style="display:flex; align-items:center;"><span style="font-weight:750; color:#0f172a; font-size:0.92rem; letter-spacing:-0.2px;">{st_avg:.1f}</span>{crown_html}</div><div style="display:flex; align-items:center; gap:4px; font-size:0.73rem;"><span style="font-weight:800; color:{_status_color};">{_status_text}</span><span style="color:#94a3b8; font-size:0.7rem;">({diff_str})</span></div></div></td>"""
            pos_cells.append(cell_html)

        # Surplus / Trade bait chips
        surplus_badges = []
        for pos in prof["surplus_positions"]:
            surplus_badges.append(f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:6px; padding:2px 8px; font-weight:700; font-size:0.74rem; white-space:nowrap;'>+{pos}</span>")
        if not surplus_badges:
            surplus_html = "<span style='color:#94a3b8; font-size:0.75rem;'>None</span>"
        else:
            bait_names = [b["player_name"] for b in prof["trade_bait"][:2]]
            bait_str = f"<div style='font-size:0.70rem; color:#64748b; margin-top:3px; white-space:nowrap;'>Bait: <span style='color:#334155; font-weight:600;'>{', '.join(bait_names)}</span></div>" if bait_names else ""
            surplus_html = f"<div style='display:flex; flex-direction:column; justify-content:center;'><div style='display:flex; gap:5px; flex-wrap:wrap; align-items:center;'>{''.join(surplus_badges)}</div>{bait_str}</div>"

        # Needs chips
        need_badges = []
        for pos in prof["need_positions"]:
            need_badges.append(f"<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; border-radius:6px; padding:2px 8px; font-weight:700; font-size:0.74rem; white-space:nowrap;'>Need {pos}</span>")
        if not need_badges:
            need_html = "<span style='display:inline-flex; align-items:center; gap:5px; color:#15803d; font-size:0.75rem; font-weight:600;'><span style='width:6px; height:6px; border-radius:50%; background:#22c55e;'></span>Solid Depth</span>"
        else:
            need_html = f"<div style='display:flex; gap:5px; flex-wrap:wrap; align-items:center;'>{''.join(need_badges)}</div>"

        row = f"""
        <tr style="border-bottom:1px solid #f1f5f9; height:52px;">
            <td style="padding:8px 4px 8px 14px; width:20px; text-align:center;">{t_dot}</td>
            <td style="padding:8px 10px 8px 4px; text-align:left; min-width:130px;">
                <div style="font-weight:700; font-size:0.86rem; color:#0f172a; white-space:nowrap;">{t_name}</div>
                <div style="font-size:0.72rem; color:#64748b; white-space:nowrap;">{prof['owner_name']}</div>
            </td>
            {''.join(pos_cells)}
            <td style="padding:8px 12px; vertical-align:middle; min-width:140px;">{surplus_html}</td>
            <td style="padding:8px 12px; vertical-align:middle; min-width:150px;">{need_html}</td>
            <td style="padding:8px 12px; text-align:right; font-weight:800; color:#0f172a; font-size:0.88rem; white-space:nowrap;">
                {prof['starter_score']:.1f}
            </td>
            <td style="padding:8px 14px 8px 8px; text-align:right; font-weight:700; color:#64748b; font-size:0.84rem; white-space:nowrap;">
                {prof['bench_score']:.1f}
            </td>
        </tr>
        """
        matrix_rows.append(row)

    # Benchmark Row
    bm_cells = "".join([f"<td style='padding:9px 8px; text-align:center; font-weight:750; color:#2563eb; font-size:0.86rem; white-space:nowrap;'>{benchmarks.get(p, 0.0):.1f}</td>" for p in positions])
    avg_starter_total = float(np.mean([prof['starter_score'] for prof in team_profiles.values()])) if team_profiles else 0.0
    avg_bench_total = float(np.mean([prof['bench_score'] for prof in team_profiles.values()])) if team_profiles else 0.0
    benchmark_row = f"""
    <tr style="background:#f8fafc; font-weight:700; border-top:2px solid #e2e8f0; height:44px;">
        <td colspan="2" style="padding:9px 14px; text-align:left; color:#475569; font-size:0.76rem; text-transform:uppercase; letter-spacing:0.5px; white-space:nowrap;">
            🎯 League Starter Avg
        </td>
        {bm_cells}
        <td style="padding:9px 12px; text-align:left; color:#94a3b8; font-size:0.75rem;">Benchmark</td>
        <td style="padding:9px 12px; text-align:left; color:#94a3b8; font-size:0.75rem;">—</td>
        <td style="padding:9px 12px; text-align:right; color:#2563eb; font-weight:800; font-size:0.86rem; white-space:nowrap;">
            {avg_starter_total:.1f}
        </td>
        <td style="padding:9px 14px 9px 8px; text-align:right; color:#64748b; font-weight:700; font-size:0.84rem; white-space:nowrap;">
            {avg_bench_total:.1f}
        </td>
    </tr>
    """

    matrix_table = f"""
    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:14px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);">
        <div style="background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;">
            <span>📊 Positional Surplus vs. Deficit Matrix</span>
            <span style="font-size:0.75rem; color:#64748b; font-weight:500;">Evaluates roster strength against 6-team league starter averages</span>
        </div>
        <div style="overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; font-size:0.84rem;">
                <thead>
                    <tr style="background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.5px;">
                        <th style="padding:10px 4px 10px 14px; width:20px;"></th>
                        <th style="padding:10px 10px 10px 4px; text-align:left; min-width:130px;">Team / Manager</th>
                        <th style="padding:10px 8px; text-align:center; min-width:95px;">QB</th>
                        <th style="padding:10px 8px; text-align:center; min-width:95px;">RB</th>
                        <th style="padding:10px 8px; text-align:center; min-width:95px;">WR</th>
                        <th style="padding:10px 8px; text-align:center; min-width:95px;">TE</th>
                        <th style="padding:10px 12px; text-align:left; min-width:140px;">Surplus / Trade Bait</th>
                        <th style="padding:10px 12px; text-align:left; min-width:150px;">Target Area (Need)</th>
                        <th style="padding:10px 12px; text-align:right; width:88px;">Starter PPG</th>
                        <th style="padding:10px 14px 10px 8px; text-align:right; width:82px;">Bench PPG</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(matrix_rows)}
                    {benchmark_row}
                </tbody>
            </table>
        </div>
    </div>
    """

    # SECTION 2: AI Trade Target Matchmaker (Cards)
    rec_cards = []
    if not recommendations:
        rec_cards.append("""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:20px; text-align:center; color:#64748b; font-size:0.85rem;">
            No high-equity win-win trades found for the selected filter. Try selecting 'All Teams' or adjusting roster requirements.
        </div>
        """)
    else:
        for rec in recommendations[:6]:
            t_a = rec["team_a"]
            t_b = rec["team_b"]
            p_a = rec["player_a"]
            p_b = rec["player_b"]
            diff_a = rec["starter_diff_a"]
            diff_b = rec["starter_diff_b"]
            fair = rec["fairness_pct"]

            tags_html = " ".join([f"<span style='background:#eff6ff; border:1px solid #bfdbfe; color:#1d4ed8; border-radius:6px; padding:2px 7px; font-size:0.7rem; font-weight:700;'>{t}</span>" for t in rec.get("tags", [])])

            t_a_dot = f"<span style='display:inline-block; width:8px; height:8px; border-radius:50%; background-color:{owner_colors.get(t_a, '#3b82f6')};'></span>"
            t_b_dot = f"<span style='display:inline-block; width:8px; height:8px; border-radius:50%; background-color:{owner_colors.get(t_b, '#8b5cf6')};'></span>"

            pill_a = f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:6px; padding:2px 7px; font-weight:700; font-size:0.75rem;'>{diff_a:+.1f} Starter PPG</span>" if diff_a >= 0 else f"<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; border-radius:6px; padding:2px 7px; font-weight:700; font-size:0.75rem;'>{diff_a:+.1f} Starter PPG</span>"
            pill_b = f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:6px; padding:2px 7px; font-weight:700; font-size:0.75rem;'>{diff_b:+.1f} Starter PPG</span>" if diff_b >= 0 else f"<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; border-radius:6px; padding:2px 7px; font-weight:700; font-size:0.75rem;'>{diff_b:+.1f} Starter PPG</span>"

            card = f"""
            <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; flex-direction:column; justify-content:space-between;">
                <div>
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                        <div style="display:flex; gap:6px; flex-wrap:wrap;">{tags_html}</div>
                        <div style="font-size:0.72rem; font-weight:700; color:#2563eb; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; padding:2px 6px;">
                            ⚖️ {fair}% Value Match
                        </div>
                    </div>

                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-top:8px;">
                        <!-- Team A -->
                        <div style="background:#f8fafc; border:1px solid #f1f5f9; border-radius:10px; padding:10px;">
                            <div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
                                {t_a_dot}
                                <span style="font-weight:700; font-size:0.82rem; color:#0f172a;">{t_a}</span>
                            </div>
                            <div style="font-size:0.7rem; color:#64748b; margin-bottom:4px; font-weight:600; text-transform:uppercase;">Gives Up:</div>
                            <div style="display:flex; align-items:center; gap:8px;">
                                <img src="{p_a.get('headshot_url', '')}" style="width:36px; height:36px; border-radius:50%; object-fit:cover; background:#e2e8f0; border:1px solid #cbd5e1;" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'"/>
                                <div>
                                    <div style="font-weight:700; font-size:0.84rem; color:#0f172a;">{p_a['player_name']}</div>
                                    <div style="font-size:0.72rem; color:#64748b;"><span style="font-weight:700; color:#3b82f6;">{p_a['position']}</span> • {p_a.get('pos_percentile', 50)}th %ile • <strong style="color:#0f172a;">{p_a.get('score', 0):.1f}</strong> PPG</div>
                                    <div style="font-size:0.68rem; color:#7c3aed; font-weight:700;">TV: {p_a.get('trade_value', 0):.1f}</div>
                                </div>
                            </div>
                            <div style="margin-top:8px;">{pill_a}</div>
                        </div>

                        <!-- Team B -->
                        <div style="background:#f8fafc; border:1px solid #f1f5f9; border-radius:10px; padding:10px;">
                            <div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
                                {t_b_dot}
                                <span style="font-weight:700; font-size:0.82rem; color:#0f172a;">{t_b}</span>
                            </div>
                            <div style="font-size:0.7rem; color:#64748b; margin-bottom:4px; font-weight:600; text-transform:uppercase;">Gives Up:</div>
                            <div style="display:flex; align-items:center; gap:8px;">
                                <img src="{p_b.get('headshot_url', '')}" style="width:36px; height:36px; border-radius:50%; object-fit:cover; background:#e2e8f0; border:1px solid #cbd5e1;" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'"/>
                                <div>
                                    <div style="font-weight:700; font-size:0.84rem; color:#0f172a;">{p_b['player_name']}</div>
                                    <div style="font-size:0.72rem; color:#64748b;"><span style="font-weight:700; color:#3b82f6;">{p_b['position']}</span> • {p_b.get('pos_percentile', 50)}th %ile • <strong style="color:#0f172a;">{p_b.get('score', 0):.1f}</strong> PPG</div>
                                    <div style="font-size:0.68rem; color:#7c3aed; font-weight:700;">TV: {p_b.get('trade_value', 0):.1f}</div>
                                </div>
                            </div>
                            <div style="margin-top:8px;">{pill_b}</div>
                        </div>
                    </div>

                    <div style="background:#f1f5f9; border-radius:8px; padding:8px 10px; margin-top:12px; font-size:0.74rem; color:#475569; line-height:1.4;">
                        <strong style="color:#0f172a;">Trade Logic:</strong> {rec['reason']}
                    </div>
                </div>
            </div>
            """
            rec_cards.append(card)

    recs_section = f"""
    <div style="margin-top:18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
            <div>
                <div style="font-weight:800; font-size:1.05rem; color:#0f172a;">🎯 AI Trade Target Matchmaker (Top Win-Win Swaps)</div>
                <div style="font-size:0.78rem; color:#64748b;">Algorithmic proposals matching complementary roster surplus and deficit positions to upgrade starting lineups.</div>
            </div>
        </div>
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap:12px;">
            {''.join(rec_cards)}
        </div>
    </div>
    """

    # SECTION 3: Interactive Trade Value Calculator
    # Header & simulation display
    if calc_result and calc_result.get("valid"):
        t_a = calc_result["team_a"]
        t_b = calc_result["team_b"]
        diff_a = calc_result["starter_diff_a"]
        diff_b = calc_result["starter_diff_b"]
        net_ppg_a = calc_result.get("ppg_net_a", 0.0)
        net_ppg_b = calc_result.get("ppg_net_b", 0.0)
        pct_a = calc_result.get("pct_a_sends", 50)
        pct_b = calc_result.get("pct_b_sends", 50)
        val_a = calc_result["val_a_sends"]
        val_b = calc_result["val_b_sends"]
        fair_pct = calc_result["fairness_pct"]
        verdict = calc_result["verdict"]
        verdict_color = calc_result["verdict_color"]

        # Production Net Delta Pills
        if net_ppg_a > 0:
            diff_a_pill = f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:8px; padding:4px 10px; font-weight:800; font-size:0.95rem;'>+{net_ppg_a:.1f} PPG</span>"
        elif net_ppg_a < 0:
            diff_a_pill = f"<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; border-radius:8px; padding:4px 10px; font-weight:800; font-size:0.95rem;'>{net_ppg_a:.1f} PPG</span>"
        else:
            diff_a_pill = f"<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#475569; border-radius:8px; padding:4px 10px; font-weight:800; font-size:0.95rem;'>0.0 PPG</span>"

        if net_ppg_b > 0:
            diff_b_pill = f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:8px; padding:4px 10px; font-weight:800; font-size:0.95rem;'>+{net_ppg_b:.1f} PPG</span>"
        elif net_ppg_b < 0:
            diff_b_pill = f"<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; border-radius:8px; padding:4px 10px; font-weight:800; font-size:0.95rem;'>{net_ppg_b:.1f} PPG</span>"
        else:
            diff_b_pill = f"<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#475569; border-radius:8px; padding:4px 10px; font-weight:800; font-size:0.95rem;'>0.0 PPG</span>"

        # Trade balance bar
        total_val_pool = max(val_a + val_b, 1.0)
        bar_pct_a = (val_a / total_val_pool) * 100
        bar_pct_b = (val_b / total_val_pool) * 100


        def _render_package_breakdown(players_list):
            if not players_list:
                return "<div style='font-size:0.75rem; color:#94a3b8; padding:4px 0;'>None selected</div>"
            cards = []
            for p in players_list:
                img = p.get("headshot_url", "")
                p_name = p.get("player_name", "Unknown")
                pos = p.get("position", "")
                tv_val = p.get("trade_value", 0.0)
                tv = float(tv_val) if pd.notna(tv_val) else 0.0
                score_val = p.get("score", 0.0)
                score = float(score_val) if pd.notna(score_val) else 0.0
                gp_val = p.get("games_played", 0)
                gp = int(gp_val) if pd.notna(gp_val) else 0
                pos_rank_val = p.get("pos_rank", 99)
                pos_rank = int(pos_rank_val) if pd.notna(pos_rank_val) else 99
                pct_val = p.get("pos_percentile", 50)
                pct = int(round(float(pct_val))) if pd.notna(pct_val) else 50
                inj = str(p.get("injury_status", "Healthy")).strip()

                if inj == "Healthy":
                    inj_badge = "<span style='color:#16a34a; font-weight:600; font-size:0.70rem;'>Healthy</span>"
                elif inj in ["Questionable", "Q"]:
                    inj_badge = "<span style='background:#fef3c7; color:#b45309; border:1px solid #fde68a; border-radius:4px; padding:1px 5px; font-weight:700; font-size:0.68rem;'>Questionable (-10% risk)</span>"
                else:
                    inj_badge = f"<span style='background:#fee2e2; color:#dc2626; border:1px solid #fca5a5; border-radius:4px; padding:1px 5px; font-weight:700; font-size:0.68rem;'>{inj} (-40% risk)</span>"

                if gp <= 1:
                    sample_tag = " <span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; border-radius:4px; padding:1px 5px; font-weight:700; font-size:0.68rem;'>⚠️ 1 GP (Small sample)</span>"
                else:
                    sample_tag = f" <span style='color:#64748b;'>({gp} GP)</span>"

                rank_str = f"#{pos_rank} {pos}" if pos_rank < 99 else pos

                card_html = f"""
                <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:8px 10px; margin-top:6px; display:flex; align-items:center; justify-content:space-between; gap:10px;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <img src="{img}" style="width:34px; height:34px; border-radius:50%; object-fit:cover; background:#f1f5f9; border:1px solid #e2e8f0;" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'"/>
                        <div>
                            <div style="font-weight:700; font-size:0.86rem; color:#0f172a; display:flex; align-items:center; gap:6px;">
                                <span>{p_name}</span>
                                <span style="background:#f1f5f9; color:#475569; border-radius:4px; padding:1px 5px; font-size:0.70rem; font-weight:700;">{pos}</span>
                            </div>
                            <div style="font-size:0.72rem; color:#64748b; margin-top:2px; display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                <span><b>{score:.1f} PPG</b>{sample_tag}</span>
                                <span>•</span>
                                <span>{rank_str} ({pct}th %ile)</span>
                                <span>•</span>
                                {inj_badge}
                            </div>
                        </div>
                    </div>
                    <div style="text-align:right; min-width:70px; flex-shrink:0;">
                        <div style="font-weight:800; font-size:1.0rem; color:#7c3aed;">{tv:.1f} <span style="font-size:0.72rem; font-weight:600; color:#64748b;">TV</span></div>
                        <div style="font-size:0.68rem; color:#94a3b8;">Asset Value</div>
                    </div>
                </div>
                """
                cards.append(card_html)
            return "".join(cards)

        # Lineup changes rows
        st_a_before = calc_result.get("lineup_a_before", {}).get("starter_score", 0.0)
        st_b_before = calc_result.get("lineup_b_before", {}).get("starter_score", 0.0)

        moves_a_html = "".join([f"<li style='margin-bottom:3px;'><b>{m['slot']}:</b> {m['new_player']} enters ({m['diff']:+.1f} pts vs {m['old_player']})</li>" for m in calc_result.get("moves_a", [])])
        if not moves_a_html:
            moves_a_html = f"<li>Roster Depth: Bench upgraded (Starters hold at {st_a_before:.1f} PPG)</li>"

        moves_b_html = "".join([f"<li style='margin-bottom:3px;'><b>{m['slot']}:</b> {m['new_player']} enters ({m['diff']:+.1f} pts vs {m['old_player']})</li>" for m in calc_result.get("moves_b", [])])
        if not moves_b_html:
            moves_b_html = f"<li>Roster Depth: Bench upgraded (Starters hold at {st_b_before:.1f} PPG)</li>"

        calc_sim_display = f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:16px; margin-top:14px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-left:4px solid {verdict_color}; border-radius:8px; padding:10px 14px; font-weight:700; font-size:0.92rem; color:{verdict_color}; margin-bottom:14px;">
                {verdict}
            </div>

            <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px;">
                <!-- Team A Impact -->
                <div style="background:#f8fafc; border:1px solid #f1f5f9; border-radius:10px; padding:14px; display:flex; flex-direction:column; justify-content:space-between;">
                    <div>
                        <div style="font-weight:800; font-size:0.95rem; color:#0f172a; margin-bottom:8px;">{t_a} Trade Impact</div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <span style="font-size:0.78rem; color:#64748b; font-weight:600;">Net Production Delta:</span>
                            {diff_a_pill}
                        </div>
                        <div style="font-size:0.75rem; color:#64748b; margin-bottom:10px;">
                            <span>Trade Value: Sent <strong style="color:#7c3aed;">{val_a:.1f} TV</strong> ({pct_a}th %ile)</span> • 
                            <span>Received <strong style="color:#2563eb;">{val_b:.1f} TV</strong> ({pct_b}th %ile)</span>
                        </div>
                        
                        <!-- Individual Asset Valuation Breakdown -->
                        <div style="font-size:0.75rem; color:#475569; margin-top:8px; border-top:1px solid #e2e8f0; padding-top:8px;">
                            <div style="font-weight:700; color:#0f172a; margin-bottom:4px;">📦 Players Sent by {t_a} ({len(calc_result.get('players_a_sends', []))}):</div>
                            {_render_package_breakdown(calc_result.get('players_a_sends', []))}
                        </div>
                    </div>

                    <div style="font-size:0.74rem; color:#475569; margin-top:12px; border-top:1px solid #e2e8f0; padding-top:8px;">
                        <strong>⚡ Starting Lineup Adjustments:</strong>
                        <ul style="padding-left:16px; margin:4px 0 0 0; color:#334155;">{moves_a_html}</ul>
                    </div>
                </div>

                <!-- Team B Impact -->
                <div style="background:#f8fafc; border:1px solid #f1f5f9; border-radius:10px; padding:14px; display:flex; flex-direction:column; justify-content:space-between;">
                    <div>
                        <div style="font-weight:800; font-size:0.95rem; color:#0f172a; margin-bottom:8px;">{t_b} Trade Impact</div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <span style="font-size:0.78rem; color:#64748b; font-weight:600;">Net Production Delta:</span>
                            {diff_b_pill}
                        </div>
                        <div style="font-size:0.75rem; color:#64748b; margin-bottom:10px;">
                            <span>Trade Value: Sent <strong style="color:#7c3aed;">{val_b:.1f} TV</strong> ({pct_b}th %ile)</span> • 
                            <span>Received <strong style="color:#2563eb;">{val_a:.1f} TV</strong> ({pct_a}th %ile)</span>
                        </div>
                        
                        <!-- Individual Asset Valuation Breakdown -->
                        <div style="font-size:0.75rem; color:#475569; margin-top:8px; border-top:1px solid #e2e8f0; padding-top:8px;">
                            <div style="font-weight:700; color:#0f172a; margin-bottom:4px;">📦 Players Sent by {t_b} ({len(calc_result.get('players_b_sends', []))}):</div>
                            {_render_package_breakdown(calc_result.get('players_b_sends', []))}
                        </div>
                    </div>

                    <div style="font-size:0.74rem; color:#475569; margin-top:12px; border-top:1px solid #e2e8f0; padding-top:8px;">
                        <strong>⚡ Starting Lineup Adjustments:</strong>
                        <ul style="padding-left:16px; margin:4px 0 0 0; color:#334155;">{moves_b_html}</ul>
                    </div>
                </div>
            </div>

            <!-- Value Balance Bar -->
            <div style="margin-top:14px; background:#f8fafc; border:1px solid #f1f5f9; border-radius:8px; padding:10px 14px;">
                <div style="display:flex; justify-content:space-between; font-size:0.75rem; font-weight:600; color:#64748b; margin-bottom:6px;">
                    <span>{t_a} ({val_a:.1f} TV)</span>
                    <span style="color:#0f172a; font-weight:700;">⚖️ {fair_pct}% Trade Equity Match</span>
                    <span>{t_b} ({val_b:.1f} TV)</span>
                </div>
                <div style="height:8px; border-radius:4px; background:#e2e8f0; overflow:hidden; display:flex;">
                    <div style="width:{bar_pct_a}%; background:#3b82f6;"></div>
                    <div style="width:{bar_pct_b}%; background:#8b5cf6;"></div>
                </div>
            </div>

            <!-- Positional Scarcity & Percentile Context Note -->
            <div style="margin-top:12px; background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; padding:10px 14px; font-size:0.74rem; color:#475569; line-height:1.45;">
                💡 <strong>Positional Value & Scarcity Context:</strong> Trade Value (TV) normalizes <em>positional scarcity</em> and <em>Value Over Replacement (VORP)</em> rather than raw fantasy points. 
                Because top-tier Running Backs and Tight Ends are drastically scarcer than Quarterbacks, an elite 13–15 PPG TE or RB holds significantly higher trade equity and market value than an 18–20 PPG QB.
            </div>
        </div>
        """
    else:
        calc_sim_display = """
        <div style="background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px; padding:20px; text-align:center; color:#64748b; font-size:0.84rem; margin-top:14px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            👉 <strong>Select one or more players from Team A and Team B above</strong> to instantly simulate the net production impact and trade equity balance.
        </div>
        """

    # Interactive Calculator Card Wrap
    calc_box = mo.vstack([
        mo.Html(f"""
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:16px; margin-top:18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);">
            <div style="margin-bottom:12px;">
                <div style="font-weight:800; font-size:1.05rem; color:#0f172a;">⚡ Interactive Trade Value Calculator & Lineup Simulator</div>
                <div style="font-size:0.78rem; color:#64748b;">Select any two teams and pick players to simulate net production impact (PPG delta) and asset value exchange.</div>
            </div>
        """),
        mo.hstack([
            mo.vstack([
                calc_team_a_control,
                calc_pids_a_control
            ], gap=0.5),
            mo.vstack([
                calc_team_b_control,
                calc_pids_b_control
            ], gap=0.5)
        ], justify="space-between", gap=2),
        mo.Html(calc_sim_display),
        mo.Html("</div>")
    ], gap=0.5)

    return mo.vstack([
        mo.Html(kpi_html),
        mo.Html(matrix_table),
        mo.Html(recs_section),
        calc_box
    ], gap=1)


def render_player_market_view(
    val_df: pd.DataFrame,
    unique_teams: List[str],
    owner_colors: Dict[str, str],
    pos_filter: str,
    team_filter: str,
    search_query: str,
    mo: Any,
    chart_width: int = 860
) -> Any:
    """
    Render the dedicated Player Market & Value Analysis page.
    Includes:
    - Top Market Asset KPIs
    - Buy-Low & Sell-High Trade Radar
    - Interactive Altair Value Scatter Plot (TV vs PPG)
    - Full Searchable & Filterable League-Wide Market Value Table
    """
    if val_df is None or val_df.empty:
        return mo.md("No player market data available.")

    from src.visual import build_market_value_scatter_chart

    # Filter strictly to rostered (owned) fantasy players on the Player Market page
    rostered_mask = (
        (val_df["team_name"].notna()) &
        (val_df["team_name"] != "Free Agent") &
        (val_df["team_name"] != "")
    )
    val_df = val_df[rostered_mask].copy()

    if val_df.empty:
        return mo.md("No rostered player market data available.")

    # Apply filters
    filtered = val_df.copy()
    if pos_filter and pos_filter != "ALL":
        filtered = filtered[filtered["position"] == pos_filter]
    if team_filter and team_filter != "ALL":
        filtered = filtered[filtered["team_name"] == team_filter]
    if search_query and search_query.strip():
        q = search_query.strip().lower()
        filtered = filtered[filtered["player_name"].str.lower().str.contains(q, na=False)]

    # 1. KPI Cards
    sorted_all = val_df.sort_values(by="trade_value", ascending=False)
    top_asset = sorted_all.iloc[0] if not sorted_all.empty else None

    # Buy-Low Candidates:
    # High-ceiling players (score >= 12.0) whose trade value is temporarily DEPRESSED (TV <= 50.0)
    # due to injury or limited sample size (<= 2 GP). Elite, fully-priced assets (e.g. Bowers at 81.9 TV) are NOT buy-lows.
    buy_low_mask = (
        (val_df["score"] >= 12.0) &
        (val_df["trade_value"] <= 50.0) &
        ((val_df["injury_status"].isin(["Questionable", "Out", "IR", "Doubtful"])) | (val_df["games_played"] <= 2))
    )
    buy_low_cands = val_df[buy_low_mask].sort_values(by="score", ascending=False)
    buy_low_ids = set(buy_low_cands["player_id"].astype(str).tolist())

    # Prioritize skill positions (WR, RB, TE) for top buy-low card
    skill_buy_low = buy_low_cands[buy_low_cands["position"].isin(["RB", "WR", "TE"])]
    top_buy_low = skill_buy_low.iloc[0] if not skill_buy_low.empty else (buy_low_cands.iloc[0] if not buy_low_cands.empty else None)

    # Sell-High Candidates:
    # Must be currently HEALTHY, with substantial trade equity (TV >= 25.0) and high scoring (score >= 15.0),
    # but accompanied by high volatility / boom-bust risk (std_points >= 8.0).
    # STRICT DISJOINT GUARANTEE: Never include any player flagged in the Buy-Low list!
    sell_high_mask = (
        (~val_df["player_id"].astype(str).isin(buy_low_ids)) &
        (val_df["injury_status"] == "Healthy") &
        (val_df["trade_value"] >= 25.0) &
        (val_df["score"] >= 15.0) &
        (val_df["std_points"] >= 8.0)
    )
    sell_high_cands = val_df[sell_high_mask].sort_values(by="std_points", ascending=False)
    top_sell_high = sell_high_cands.iloc[0] if not sell_high_cands.empty else None

    # Capital leader team
    team_cap = val_df.groupby("team_name")["trade_value"].sum().sort_values(ascending=False)
    top_cap_team = team_cap.index[0] if not team_cap.empty else "N/A"
    top_cap_val = team_cap.iloc[0] if not team_cap.empty else 0.0

    kpi_boxes = f"""
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:12px; margin-bottom:16px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <!-- Top Asset -->
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">👑 #1 Overall Asset</div>
            <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0;">{top_asset['player_name'] if top_asset is not None else 'N/A'}</div>
            <div style="font-size:0.75rem; color:#7c3aed; font-weight:700;">{top_asset['trade_value']:.1f} TV <span style="color:#64748b; font-weight:normal;">({top_asset['position']} • {top_asset['team_name']})</span></div>
        </div>

        <!-- Top Buy-Low -->
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:700; color:#16a34a; text-transform:uppercase; letter-spacing:0.5px;">📈 Top Buy-Low Target</div>
            <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0;">{top_buy_low['player_name'] if top_buy_low is not None else 'N/A'}</div>
            <div style="font-size:0.75rem; color:#15803d; font-weight:700;">{top_buy_low['score']:.1f} PPG <span style="color:#64748b; font-weight:normal;">({top_buy_low['trade_value']:.1f} TV • {top_buy_low['injury_status']})</span></div>
        </div>

        <!-- Top Sell-High -->
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:700; color:#b45309; text-transform:uppercase; letter-spacing:0.5px;">⚡ Peak Volatility (Sell-High)</div>
            <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0;">{top_sell_high['player_name'] if top_sell_high is not None else 'N/A'}</div>
            <div style="font-size:0.75rem; color:#b45309; font-weight:700;">±{top_sell_high['std_points']:.1f} SD <span style="color:#64748b; font-weight:normal;">({top_sell_high['score']:.1f} PPG • {top_sell_high['team_name']})</span></div>
        </div>

        <!-- Asset Capital Leader -->
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="font-size:0.75rem; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">💼 Asset Capital Leader</div>
            <div style="font-size:1.25rem; font-weight:800; color:#0f172a; margin:4px 0;">{top_cap_team}</div>
            <div style="font-size:0.75rem; color:#2563eb; font-weight:700;">{top_cap_val:.1f} Total TV <span style="color:#64748b; font-weight:normal;">(Deepest trade equity)</span></div>
        </div>
    </div>
    """

    # 2. Buy-Low & Sell-High Radar Cards
    def _render_radar_items(cands, is_buy=True):
        items = []
        for _, r in cands.head(3).iterrows():
            pos = r.get("position", "WR")
            score_val = r.get("score", 0.0)
            score = float(score_val) if pd.notna(score_val) else 0.0
            tv_val = r.get("trade_value", 0.0)
            tv = float(tv_val) if pd.notna(tv_val) else 0.0
            sd_val = r.get("std_points", 0.0)
            sd = float(sd_val) if pd.notna(sd_val) else 0.0
            gp_val = r.get("games_played", 0)
            gp = int(gp_val) if pd.notna(gp_val) else 0
            inj = str(r.get("injury_status", "Healthy"))

            if is_buy:
                note = f"{score:.1f} PPG ({gp} GP)" if gp <= 1 else f"{inj} discount ({score:.1f} PPG)"
                color = "#15803d"
                bg = "#f0fdf4"
                border = "#bbf7d0"
            else:
                note = f"High Boom/Bust: ±{sd:.1f} SD ({score:.1f} PPG)"
                color = "#b45309"
                bg = "#fffbeb"
                border = "#fde68a"

            item_html = f"""
            <div style="background:{bg}; border:1px solid {border}; border-radius:8px; padding:8px 12px; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <img src="{r.get('headshot_url', '')}" style="width:32px; height:32px; border-radius:50%; object-fit:cover; background:#ffffff; border:1px solid #e2e8f0;" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'"/>
                    <div>
                        <div style="font-weight:700; font-size:0.86rem; color:#0f172a;">{r['player_name']} <span style="font-size:0.74rem; color:#64748b;">({pos} • {r['team_name']})</span></div>
                        <div style="font-size:0.72rem; color:{color}; font-weight:600;">{note}</div>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-weight:800; font-size:0.95rem; color:#7c3aed;">{tv:.1f} TV</div>
                    <div style="font-size:0.68rem; color:#94a3b8;">#{r.get('pos_rank', 99)} {pos}</div>
                </div>
            </div>
            """
            items.append(item_html)
        return "".join(items)

    radar_box = f"""
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:16px; margin-bottom:18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <!-- Buy-Low Radar -->
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:10px;">
                <span style="font-size:1.1rem;">🎯</span>
                <div>
                    <div style="font-weight:800; font-size:0.92rem; color:#0f172a;">Target Buy-Low Candidates</div>
                    <div style="font-size:0.72rem; color:#64748b;">Studs with depressed market values due to small sample sizes or minor injuries.</div>
                </div>
            </div>
            {_render_radar_items(buy_low_cands, is_buy=True)}
        </div>

        <!-- Sell-High Radar -->
        <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px; box-shadow:0 1px 3px rgba(0,0,0,0.02);">
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:10px;">
                <span style="font-size:1.1rem;">⚡</span>
                <div>
                    <div style="font-weight:800; font-size:0.92rem; color:#0f172a;">Target Sell-High Candidates</div>
                    <div style="font-size:0.72rem; color:#64748b;">Players carrying volatile boom-bust profiles currently valued at peak market output.</div>
                </div>
            </div>
            {_render_radar_items(sell_high_cands, is_buy=False)}
        </div>
    </div>
    """

    # 3. Scatter Chart
    scatter_chart = build_market_value_scatter_chart(
        val_data=filtered,
        unique_teams=unique_teams,
        owner_colors=owner_colors,
        chart_width=chart_width,
        chart_height=480
    )

    chart_header = """
    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:14px 14px 0 0; padding:14px 18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; border-bottom:1px solid #e2e8f0; margin-top:6px;">
        <div style="font-weight:800; font-size:0.96rem; color:#0f172a;">📈 Player Market Trade Value vs. Mean Fantasy Production</div>
        <div style="font-size:0.75rem; color:#64748b; margin-top:2px;">Comparing raw weekly scoring (PPG) against scarcity-adjusted trade equity (TV). Upper-right quadrant represents league-winning anchors.</div>
    </div>
    """

    # 4. League-Wide Market Value Table
    pos_colors = {
        'QB': '#f43f5e',
        'RB': '#06b6d4',
        'WR': '#3b82f6',
        'TE': '#f59e0b',
        'K': '#a855f7',
        'DEF': '#64748b'
    }

    table_rows = []
    for rank_idx, (_, r) in enumerate(filtered.sort_values(by="trade_value", ascending=False).iterrows(), 1):
        pos = r.get("position", "WR")
        pos_badge = f"<span style='background:{pos_colors.get(pos, '#2563eb')}; color:#ffffff; font-weight:700; font-size:0.72rem; border-radius:4px; padding:2px 6px;'>{pos}</span>"
        t_name = r.get("team_name", "Free Agent")
        o_color = owner_colors.get(t_name, "#94a3b8")
        owner_badge = f"<span style='display:inline-flex; align-items:center; gap:4px; font-weight:600; font-size:0.78rem; color:#0f172a;'><span style='width:8px; height:8px; border-radius:50%; background:{o_color};'></span>{t_name}</span>"
        
        score_val = r.get("score", 0.0)
        score = float(score_val) if pd.notna(score_val) else 0.0
        gp_val = r.get("games_played", 0)
        gp = int(gp_val) if pd.notna(gp_val) else 0
        gp_badge = f"<span style='background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; border-radius:4px; padding:1px 5px; font-size:0.68rem; font-weight:700;'>⚠️ {gp} GP</span>" if gp <= 1 else f"<span style='color:#64748b; font-size:0.78rem;'>{gp} GP</span>"
        
        tv_val = r.get("trade_value", 0.0)
        tv = float(tv_val) if pd.notna(tv_val) else 0.0
        pct_val = r.get("pos_percentile", 50)
        pct = int(round(float(pct_val))) if pd.notna(pct_val) else 50
        sd_val = r.get("std_points", 0.0)
        sd = float(sd_val) if pd.notna(sd_val) else 0.0
        inj = str(r.get("injury_status", "Healthy")).strip()
        if inj == "Healthy":
            inj_html = "<span style='color:#16a34a; font-weight:600; font-size:0.76rem;'>Active</span>"
        elif inj in ["Questionable", "Q"]:
            inj_html = "<span style='background:#fef3c7; color:#b45309; border:1px solid #fde68a; border-radius:4px; padding:1px 5px; font-weight:700; font-size:0.70rem;'>Questionable</span>"
        else:
            inj_html = f"<span style='background:#fee2e2; color:#dc2626; border:1px solid #fca5a5; border-radius:4px; padding:1px 5px; font-weight:700; font-size:0.70rem;'>{inj}</span>"

        row_html = f"""
        <tr style="border-bottom:1px solid #f1f5f9; height:48px;">
            <td style="padding:8px 10px; font-weight:700; color:#64748b; font-size:0.80rem; width:40px;">#{rank_idx}</td>
            <td style="padding:8px 6px; width:38px;">
                <img src="{r.get('headshot_url', '')}" style="width:32px; height:32px; border-radius:50%; object-fit:cover; background:#f1f5f9; border:1px solid #e2e8f0;" onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'"/>
            </td>
            <td style="padding:8px 12px; text-align:left;">
                <div style="font-weight:700; font-size:0.86rem; color:#0f172a;">{r.get('player_name', '')}</div>
                <div style="font-size:0.72rem; color:#64748b;">{r.get('nfl_team', '')}</div>
            </td>
            <td style="padding:8px 10px; text-align:center; width:55px;">{pos_badge}</td>
            <td style="padding:8px 12px; text-align:left;">{owner_badge}</td>
            <td style="padding:8px 12px; text-align:right; width:120px;">
                <div style="font-weight:800; font-size:0.92rem; color:#7c3aed;">{tv:.1f}</div>
                <div style="font-size:0.68rem; color:#94a3b8;">{pct}th %ile</div>
            </td>
            <td style="padding:8px 12px; text-align:right; font-weight:700; color:#0f172a; width:90px;">{score:.2f}</td>
            <td style="padding:8px 10px; text-align:center; width:75px;">{gp_badge}</td>
            <td style="padding:8px 10px; text-align:center; width:80px; font-size:0.80rem; color:#64748b;">±{sd:.1f}</td>
            <td style="padding:8px 12px; text-align:center; width:100px;">{inj_html}</td>
        </tr>
        """
        table_rows.append(row_html)

    table_box = f"""
    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);">
        <div style="background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;">
            <span>📋 League Market Value & Trade Asset Registry</span>
            <span style="font-size:0.75rem; color:#64748b; font-weight:500;">{len(filtered)} Players Matching Filters</span>
        </div>
        <div style="overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; font-size:0.84rem;">
                <thead>
                    <tr style="background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.5px;">
                        <th style="padding:10px; width:40px;">#</th>
                        <th style="padding:10px 6px; width:38px;"></th>
                        <th style="padding:10px 12px; text-align:left;">Player</th>
                        <th style="padding:10px; text-align:center; width:55px;">Pos</th>
                        <th style="padding:10px 12px; text-align:left;">Fantasy Team</th>
                        <th style="padding:10px 12px; text-align:right; width:120px;">Trade Value (TV)</th>
                        <th style="padding:10px 12px; text-align:right; width:90px;">PPG</th>
                        <th style="padding:10px; text-align:center; width:75px;">GP</th>
                        <th style="padding:10px; text-align:center; width:80px;">Std Dev</th>
                        <th style="padding:10px 12px; text-align:center; width:100px;">Status</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                </tbody>
            </table>
        </div>
    </div>
    """

    return mo.vstack([
        mo.Html(kpi_boxes),
        mo.Html(radar_box),
        mo.Html(chart_header),
        mo.ui.altair_chart(scatter_chart),
        mo.Html(table_box)
    ], gap=1)
