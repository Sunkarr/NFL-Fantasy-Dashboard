import json
import sqlite3
import datetime
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
import pandas as pd
import requests

from src.config import DB_PATH, DEFAULT_LEAGUE_ID

_current_week_cache: Tuple[Optional[int], float] = (None, 0.0)

ALL_NFL_TEAMS: Set[str] = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LV", "LAC", "LAR", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SF", "SEA", "TB", "TEN", "WAS"
}

TEAM_SYNONYMS: Dict[str, str] = {
    "JAC": "JAX",
    "WSH": "WAS",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
}

_bye_week_cache: Dict[Tuple[str, int], Set[str]] = {}


def get_current_nfl_week() -> int:
    """
    Fetch current active NFL week from Sleeper state API (cached for 5 minutes).
    Falls back to 3 if API request fails.
    """
    global _current_week_cache
    val, ts = _current_week_cache
    if val is not None and (time.time() - ts) < 300:
        return val

    try:
        res = requests.get("https://api.sleeper.app/v1/state/nfl", timeout=4).json()
        wk = int(res.get("week") or res.get("display_week") or 4)
        _current_week_cache = (wk, time.time())
        return wk
    except Exception:
        return val if val is not None else 3


def get_cached_or_live_projections(
    season: str = "2026",
    week: Optional[int] = None,
    force_refresh: bool = False,
    db_path: Path = DB_PATH
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch and locally cache Sleeper player projections for a given NFL season & week.
    Caches to data/projections_{season}_{week}.json for lightning-fast loads.
    Auto-refreshes if older than 30 minutes (1800s) or if force_refresh is True.
    """
    if week is None:
        week = get_current_nfl_week()

    cache_dir = Path(db_path).parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"projections_{season}_{week}.json"

    if not force_refresh and cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            # Auto-refresh if projections cache is older than 30 minutes (1800 seconds)
            if (time.time() - mtime) < 1800:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    # Fetch live from Sleeper
    url = f"https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}"
    try:
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, dict):
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                return data
    except Exception as e:
        print(f"[Optimizer] Failed to fetch Sleeper projections for {season} W{week}: {e}")

    return {}


def _save_bye_week_to_disk(season: str, week: int, byes: Set[str], cache_file: Path) -> None:
    """Helper to persist dynamically detected bye week teams to disk."""
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data[str(week)] = sorted(list(byes))
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_nfl_bye_teams(
    season: str = "2026",
    week: Optional[int] = None,
    projections: Optional[Dict[str, Any]] = None,
    db_path: Path = DB_PATH
) -> Set[str]:
    """
    Dynamically determine which NFL teams are on BYE for any given season and week.
    Fully automated and season-agnostic:
      1. Checks in-memory cache for speed.
      2. Checks persistent local file cache (data/bye_weeks_{season}.json).
      3. Discovers bye teams via Sleeper weekly projections (which include all active team defenses).
      4. Falls back to ESPN public NFL scoreboard API for scheduled games.
      5. Automatically caches results so future requests are instantaneous.
    This guarantees that future seasons (2027 and beyond) work automatically with 0 manual code changes.
    """
    if week is None:
        week = get_current_nfl_week()

    s_str = str(season)
    w_int = int(week)
    cache_key = (s_str, w_int)

    # 1. In-memory cache
    if cache_key in _bye_week_cache:
        return _bye_week_cache[cache_key]

    # 2. Persistent disk cache
    cache_file = Path(db_path).parent / f"bye_weeks_{s_str}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                saved_byes = json.load(f)
                if str(w_int) in saved_byes:
                    byes = set(saved_byes[str(w_int)])
                    _bye_week_cache[cache_key] = byes
                    return byes
        except Exception:
            pass

    # 3. Dynamic discovery from Sleeper weekly projections
    projs = projections
    if projs is None:
        projs = get_cached_or_live_projections(season=s_str, week=w_int, db_path=db_path)

    if projs and isinstance(projs, dict):
        present_defs = {
            TEAM_SYNONYMS.get(k, k)
            for k in projs.keys()
            if TEAM_SYNONYMS.get(k, k) in ALL_NFL_TEAMS
        }
        if 24 <= len(present_defs) <= 32:
            byes = ALL_NFL_TEAMS - present_defs
            _save_bye_week_to_disk(s_str, w_int, byes, cache_file)
            _bye_week_cache[cache_key] = byes
            return byes

    # 4. Fallback: Query ESPN public NFL scoreboard API for scheduled games
    try:
        espn_url = f"http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={s_str}&seasontype=2&week={w_int}"
        resp = requests.get(espn_url, timeout=4)
        if resp.status_code == 200:
            espn_data = resp.json()
            playing_teams = set()
            for ev in espn_data.get("events", []):
                for comp in ev.get("competitions", []):
                    for competitor in comp.get("competitors", []):
                        abbrev = str(competitor.get("team", {}).get("abbreviation", "")).upper()
                        norm = TEAM_SYNONYMS.get(abbrev, abbrev)
                        if norm in ALL_NFL_TEAMS:
                            playing_teams.add(norm)
            if 24 <= len(playing_teams) <= 32:
                byes = ALL_NFL_TEAMS - playing_teams
                _save_bye_week_to_disk(s_str, w_int, byes, cache_file)
                _bye_week_cache[cache_key] = byes
                return byes
    except Exception:
        pass

    return set()


def is_player_on_bye(
    team_val: Any,
    pos_val: Any = "",
    pid_val: Any = "",
    bye_teams: Optional[Set[str]] = None
) -> bool:
    """Check if a player or defense is on bye given the bye teams set."""
    if not bye_teams:
        return False
    team_str = str(team_val or "").upper().strip()
    pos_str = str(pos_val or "").upper().strip()
    pid_str = str(pid_val or "").upper().strip()

    target = pid_str if (pos_str == "DEF" and pid_str in ALL_NFL_TEAMS) else team_str
    if not target or target in ["FA", "FREE AGENT", "NONE", ""]:
        return False
    norm = TEAM_SYNONYMS.get(target, target)
    return norm in bye_teams


def get_bye_badge(is_bye: bool) -> str:
    """Return a styled BYE badge pill if player is on bye."""
    if not is_bye:
        return ""
    return (
        '<span style="display:inline-flex; align-items:center; '
        'background:#7c3aed; color:#ffffff; '
        'font-weight:800; font-size:0.68rem; padding:1px 6px; border-radius:4px; '
        'letter-spacing:0.5px; vertical-align:middle; box-shadow:0 1px 2px rgba(124,58,237,0.25);">BYE</span>'
    )


def get_league_scoring_settings(db_path: Path = DB_PATH, league_id: str = DEFAULT_LEAGUE_ID) -> Dict[str, float]:
    """Retrieve custom league scoring settings from sync_metadata or Sleeper API."""
    try:
        from src.db import get_sync_metadata
        val = get_sync_metadata("league_scoring_settings", db_path=db_path)
        if val:
            return json.loads(val)
    except Exception:
        pass

    if league_id:
        try:
            res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}", timeout=6)
            if res.status_code == 200:
                settings = res.json().get("scoring_settings", {})
                if settings:
                    from src.db import set_sync_metadata
                    set_sync_metadata("league_scoring_settings", json.dumps(settings), db_path=db_path)
                    return settings
        except Exception:
            pass

    return {}


def calculate_projected_points(player_stats: Dict[str, Any], scoring_settings: Dict[str, float]) -> float:
    """Calculate fantasy points for projected stat categories using custom league rules."""
    if not player_stats:
        return 0.0

    if not scoring_settings:
        return float(player_stats.get("pts_ppr", player_stats.get("pts_half_ppr", player_stats.get("pts_std", 0.0))))

    total = 0.0
    has_custom = False
    for stat, val in player_stats.items():
        if stat in scoring_settings and isinstance(val, (int, float)):
            total += val * scoring_settings[stat]
            has_custom = True

    if not has_custom:
        return float(player_stats.get("pts_ppr", player_stats.get("pts_half_ppr", player_stats.get("pts_std", 0.0))))

    return round(total, 2)


def get_week_matchup_starters(
    league_id: str = DEFAULT_LEAGUE_ID,
    week: int = 1,
    db_path: Path = DB_PATH
) -> Dict[int, List[str]]:
    """
    Retrieve week-specific starters for each roster from Sleeper matchups/{week}.
    Uses a 2-minute TTL for current/upcoming weeks to reflect real-time lineup changes
    made in Sleeper, and 1-hour TTL for past weeks.
    """
    cache_dir = Path(db_path).parent
    cache_file = cache_dir / f"matchups_week_{week}.json"

    data = None
    curr_wk = get_current_nfl_week()
    ttl = 120 if week >= curr_wk else 3600

    if cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            if (time.time() - mtime) < ttl:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:
            pass

    if (data is None or not isinstance(data, list)) and league_id:
        try:
            res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}", timeout=6)
            if res.status_code == 200:
                data = res.json()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f)
        except Exception as e:
            print(f"[Optimizer] Failed to fetch matchups week {week} starters: {e}")
            return {}

    if not data or not isinstance(data, list):
        return {}

    starters_map: Dict[int, List[str]] = {}
    for item in data:
        rid = item.get("roster_id")
        st = item.get("starters") or []
        if rid is not None:
            starters_map[int(rid)] = [str(p) for p in st if p]

    return starters_map


def get_matchup_pairings(
    league_id: str = DEFAULT_LEAGUE_ID,
    week: int = 1,
    db_path: Path = DB_PATH
) -> Dict[int, Dict[str, Any]]:
    """
    Retrieve matchup pairings (opponent roster_id, opponent score) for a past week.
    Caches results locally to avoid redundant API calls.
    """
    cache_dir = Path(db_path).parent
    cache_file = cache_dir / f"matchups_week_{week}.json"

    data = None
    if cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            if (time.time() - mtime) < 3600:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:
            pass

    if data is None and league_id:
        try:
            res = requests.get(f"https://api.sleeper.app/v1/league/{league_id}/matchups/{week}", timeout=6)
            if res.status_code == 200:
                data = res.json()
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f)
        except Exception as e:
            print(f"[Optimizer] Failed to fetch matchups for W{week}: {e}")
            return {}

    if not data or not isinstance(data, list):
        return {}

    by_matchup: Dict[int, List[Dict[str, Any]]] = {}
    for item in data:
        mid = item.get("matchup_id")
        if mid is not None:
            by_matchup.setdefault(mid, []).append(item)

    pairings: Dict[int, Dict[str, Any]] = {}
    for mid, teams in by_matchup.items():
        if len(teams) == 2:
            t1, t2 = teams[0], teams[1]
            pairings[t1["roster_id"]] = {
                "opponent_roster_id": t2["roster_id"],
                "opponent_points": float(t2.get("points") or 0.0),
                "my_points": float(t1.get("points") or 0.0)
            }
            pairings[t2["roster_id"]] = {
                "opponent_roster_id": t1["roster_id"],
                "opponent_points": float(t1.get("points") or 0.0),
                "my_points": float(t2.get("points") or 0.0)
            }
        elif len(teams) == 1:
            t1 = teams[0]
            pairings[t1["roster_id"]] = {
                "opponent_roster_id": None,
                "opponent_points": 0.0,
                "my_points": float(t1.get("points") or 0.0)
            }

    return pairings


def find_top_free_agents(
    shortage_pos: str,
    rostered_pids: set,
    mode: str = "projection",
    selected_week: Optional[int] = None,
    season: str = "2026",
    df_player_stats: Optional[pd.DataFrame] = None,
    db_path: Path = DB_PATH
) -> Optional[Dict[str, Any]]:
    """
    Find the best available free agent at a given position based on projection or PPG.
    Excludes injured players and players on a BYE week.
    """
    conn = sqlite3.connect(db_path)
    try:
        p_info = pd.read_sql_query(
            "SELECT player_id, full_name, position, nfl_team, injury_status FROM players WHERE position = ?",
            conn,
            params=(shortage_pos,)
        )
    finally:
        conn.close()

    if p_info.empty:
        return None

    p_info["player_id"] = p_info["player_id"].astype(str)
    
    # Exclude rostered players and severely injured players
    severe_injuries = ["Out", "IR", "PUP", "Doubtful", "NA", "Sus"]
    fa_candidates = p_info[
        (~p_info["player_id"].isin(rostered_pids)) &
        (~p_info["injury_status"].isin(severe_injuries))
    ].copy()

    if fa_candidates.empty:
        return None

    # Exclude players whose NFL team is on BYE in the selected week
    bye_teams = get_nfl_bye_teams(season=season, week=selected_week, db_path=db_path)
    if bye_teams:
        fa_candidates = fa_candidates[~fa_candidates["nfl_team"].apply(
            lambda t: TEAM_SYNONYMS.get(str(t).upper(), str(t).upper()) in bye_teams
        )].copy()

    if fa_candidates.empty:
        return None

    if mode == "projection":
        scoring_settings = get_league_scoring_settings(db_path=db_path)
        projections = get_cached_or_live_projections(season=season, week=selected_week, db_path=db_path)
        fa_candidates["score"] = fa_candidates["player_id"].apply(
            lambda pid: calculate_projected_points(projections.get(str(pid), {}), scoring_settings)
        )
    else:
        if df_player_stats is not None and not df_player_stats.empty:
            p_sub = df_player_stats[["player_id", "mean_points"]].drop_duplicates("player_id")
            p_sub["player_id"] = p_sub["player_id"].astype(str)
            fa_candidates = fa_candidates.merge(p_sub, on="player_id", how="left")
            fa_candidates["score"] = fa_candidates["mean_points"].fillna(0.0).astype(float)
        else:
            fa_candidates["score"] = 0.0

    fa_candidates = fa_candidates.sort_values(by="score", ascending=False)
    if fa_candidates.empty:
        return None

    best = fa_candidates.iloc[0]
    pid = str(best["player_id"])
    pos = str(best["position"])
    team = str(best.get("nfl_team", "FA"))

    headshot_url = (
        f"https://sleepercdn.com/images/team_logos/nfl/{team.lower()}.png"
        if pos == "DEF" or pid == team
        else f"https://sleepercdn.com/content/nfl/players/{pid}.jpg"
    )

    return {
        "player_id": pid,
        "player_name": best["full_name"],
        "position": pos,
        "nfl_team": team,
        "score": round(float(best["score"]), 2),
        "injury_status": best.get("injury_status", "Healthy") or "Healthy",
        "is_bye": False,
        "headshot_url": headshot_url
    }


def optimize_team_lineup(
    team_name: str,
    mode: str = "projection",
    selected_week: Optional[int] = None,
    ignore_injured: bool = True,
    df_teams: pd.DataFrame = None,
    df_rosters: pd.DataFrame = None,
    df_matchups: pd.DataFrame = None,
    df_player_stats: pd.DataFrame = None,
    season: str = "2026",
    league_id: str = DEFAULT_LEAGUE_ID,
    db_path: Path = DB_PATH
) -> Dict[str, Any]:
    """
    Run full lineup optimization and comparison for a selected fantasy team.
    Modes:
      - 'projection': Upcoming / target week projections from Sleeper
      - 'ppg': Season average fantasy points (PPG)
      - 'retro': Historical backward pass on actual points scored in selected_week
    """
    if selected_week is None:
        selected_week = get_current_nfl_week()

    if df_teams is None or df_teams.empty:
        return {}

    team_row = df_teams[df_teams["team_name"] == team_name]
    if team_row.empty:
        return {}
    team_info = team_row.iloc[0]
    roster_id = int(team_info["roster_id"])

    # 1. Build base player list for the team
    projections = None
    if mode == "retro":
        if df_matchups is None or df_matchups.empty:
            return {}
        roster_df = df_matchups[
            (df_matchups["team_name"] == team_name) &
            (df_matchups["week"] == selected_week)
        ].copy()

        if roster_df.empty:
            return {}

        roster_df["score"] = roster_df["points"].fillna(0.0).astype(float)
        roster_df["is_curr_starter"] = roster_df["started"].fillna(0).astype(int)

        if df_player_stats is not None and not df_player_stats.empty:
            p_sub = df_player_stats[["player_id", "injury_status", "headshot_url"]].drop_duplicates("player_id")
            roster_df = roster_df.merge(p_sub, on="player_id", how="left")
        
        if df_rosters is not None and not df_rosters.empty and "is_reserve" in df_rosters.columns:
            r_res = df_rosters[df_rosters["team_name"] == team_name][["player_id", "is_reserve"]].drop_duplicates("player_id")
            roster_df = roster_df.merge(r_res, on="player_id", how="left")
            roster_df["is_reserve"] = roster_df["is_reserve"].fillna(0).astype(int)
        elif "is_reserve" not in roster_df.columns:
            roster_df["is_reserve"] = 0

        if "injury_status" not in roster_df.columns:
            roster_df["injury_status"] = "Healthy"
        if "headshot_url" not in roster_df.columns:
            roster_df["headshot_url"] = ""

        score_label = f"Week {selected_week} Actual Points"
        mode_title = f"Team Optimizer — Retro Pass (Week {selected_week})"

    else:
        if df_rosters is None or df_rosters.empty:
            return {}
        roster_df = df_rosters[df_rosters["team_name"] == team_name].copy()
        if roster_df.empty:
            return {}

        # Retrieve live week-specific starters from matchups/{selected_week}
        week_starters_map = get_week_matchup_starters(league_id=league_id, week=selected_week, db_path=db_path)
        week_starters = set(week_starters_map.get(roster_id, []))

        if week_starters:
            roster_df["is_curr_starter"] = roster_df["player_id"].astype(str).apply(
                lambda pid: 1 if pid in week_starters else 0
            )
        else:
            roster_df["is_curr_starter"] = roster_df["is_starter"].fillna(0).astype(int)

        if mode == "projection":
            scoring_settings = get_league_scoring_settings(db_path=db_path, league_id=league_id)
            projections = get_cached_or_live_projections(season=season, week=selected_week, db_path=db_path)
            roster_df["score"] = roster_df["player_id"].apply(
                lambda pid: calculate_projected_points(projections.get(str(pid), {}), scoring_settings)
            )
            score_label = f"Matchup Projections (Week {selected_week})"
            mode_title = f"Team Optimizer — Matchup Projections (Week {selected_week})"
        else:
            # Season Average PPG
            if df_player_stats is not None and not df_player_stats.empty:
                p_sub = df_player_stats[["player_id", "mean_points"]].drop_duplicates("player_id")
                roster_df = roster_df.merge(p_sub, on="player_id", how="left")
                roster_df["score"] = roster_df["mean_points"].fillna(0.0).astype(float)
            else:
                roster_df["score"] = 0.0
            score_label = "Season Average (PPG)"
            mode_title = "Team Optimizer — Season Average (PPG)"

    # Fill default headshot if missing
    if "headshot_url" not in roster_df.columns or roster_df["headshot_url"].isna().any():
        roster_df["headshot_url"] = roster_df.apply(
            lambda r: f"https://sleepercdn.com/images/team_logos/nfl/{str(r.get('nfl_team', '')).lower()}.png"
            if r.get("position") == "DEF" or str(r.get("player_id")) == str(r.get("nfl_team"))
            else f"https://sleepercdn.com/content/nfl/players/{r.get('player_id')}.jpg",
            axis=1
        )

    if "injury_status" not in roster_df.columns:
        roster_df["injury_status"] = "Healthy"
    else:
        roster_df["injury_status"] = roster_df["injury_status"].fillna("Healthy")

    # Determine NFL bye teams for selected week
    bye_teams = get_nfl_bye_teams(
        season=season,
        week=selected_week,
        projections=projections if mode == "projection" else None,
        db_path=db_path
    )

    # Flag players on BYE week
    roster_df["is_bye"] = roster_df.apply(
        lambda r: is_player_on_bye(r.get("nfl_team"), r.get("position"), r.get("player_id"), bye_teams),
        axis=1
    )

    # In active/upcoming weeks, players on BYE have no game and score 0.0
    if mode != "retro":
        roster_df.loc[roster_df["is_bye"], "score"] = 0.0

    severe_injuries = ["Out", "IR", "PUP", "Doubtful", "NA", "Sus"]
    if ignore_injured and mode != "retro":
        roster_df.loc[roster_df["injury_status"].isin(severe_injuries), "score"] = 0.0
    roster_df["score"] = roster_df["score"].round(2)

    # 2. Extract Current Actual Lineup Slot-by-Slot
    curr_starters_raw = roster_df[roster_df["is_curr_starter"] == 1].copy()

    slot_keys = ["QB", "RB_1", "RB_2", "WR_1", "WR_2", "TE", "FLEX", "K", "DEF"]
    slot_display_names = {
        "QB": "QB",
        "RB_1": "RB",
        "RB_2": "RB",
        "WR_1": "WR",
        "WR_2": "WR",
        "TE": "TE",
        "FLEX": "FLEX",
        "K": "K",
        "DEF": "DEF"
    }

    curr_by_slot: Dict[str, Dict[str, Any]] = {}

    # Current QB
    qbs = curr_starters_raw[curr_starters_raw["position"] == "QB"].sort_values(by="score", ascending=False)
    if not qbs.empty:
        curr_by_slot["QB"] = qbs.iloc[0].to_dict()

    # Current RBs
    rbs = curr_starters_raw[curr_starters_raw["position"] == "RB"].sort_values(by="score", ascending=False)
    for i, (_, r) in enumerate(rbs.iterrows()):
        if i == 0:
            curr_by_slot["RB_1"] = r.to_dict()
        elif i == 1:
            curr_by_slot["RB_2"] = r.to_dict()
        elif "FLEX" not in curr_by_slot:
            curr_by_slot["FLEX"] = r.to_dict()

    # Current WRs
    wrs = curr_starters_raw[curr_starters_raw["position"] == "WR"].sort_values(by="score", ascending=False)
    for i, (_, r) in enumerate(wrs.iterrows()):
        if i == 0:
            curr_by_slot["WR_1"] = r.to_dict()
        elif i == 1:
            curr_by_slot["WR_2"] = r.to_dict()
        elif "FLEX" not in curr_by_slot:
            curr_by_slot["FLEX"] = r.to_dict()

    # Current TEs
    tes = curr_starters_raw[curr_starters_raw["position"] == "TE"].sort_values(by="score", ascending=False)
    for i, (_, r) in enumerate(tes.iterrows()):
        if i == 0:
            curr_by_slot["TE"] = r.to_dict()
        elif "FLEX" not in curr_by_slot:
            curr_by_slot["FLEX"] = r.to_dict()

    # Current K
    ks = curr_starters_raw[curr_starters_raw["position"] == "K"].sort_values(by="score", ascending=False)
    if not ks.empty:
        curr_by_slot["K"] = ks.iloc[0].to_dict()

    # Current DEF
    defs = curr_starters_raw[curr_starters_raw["position"] == "DEF"].sort_values(by="score", ascending=False)
    if not defs.empty:
        curr_by_slot["DEF"] = defs.iloc[0].to_dict()

    # Fallback to fill FLEX if open
    if "FLEX" not in curr_by_slot:
        assigned_pids = {v["player_id"] for v in curr_by_slot.values()}
        remaining = curr_starters_raw[~curr_starters_raw["player_id"].isin(assigned_pids)].sort_values(by="score", ascending=False)
        if not remaining.empty:
            curr_by_slot["FLEX"] = remaining.iloc[0].to_dict()

    for k, v in curr_by_slot.items():
        v["slot"] = slot_display_names.get(k, k)

    # 3. Calculate Mathematically Optimal Lineup Slot-by-Slot
    # Exclude severely injured players AND players on BYE week from eligible optimal starter pool
    if ignore_injured and mode != "retro":
        is_reserve_mask = (roster_df["is_reserve"] == 1) if "is_reserve" in roster_df.columns else False
        eligible_pool = roster_df[
            (~roster_df["injury_status"].isin(severe_injuries)) &
            (~is_reserve_mask) &
            (~roster_df["is_bye"])
        ].copy()
        if len(eligible_pool) < 9:
            eligible_pool = roster_df[~roster_df["is_bye"]].copy()
        if len(eligible_pool) < 9:
            eligible_pool = roster_df.copy()
    else:
        eligible_pool = roster_df[~roster_df["is_bye"]].copy()
        if len(eligible_pool) < 9:
            eligible_pool = roster_df.copy()

    # Check for position shortages (e.g. 0 healthy/active QBs available)
    starter_requirements = {
        "QB": 1,
        "RB": 2,
        "WR": 2,
        "TE": 1,
        "K": 1,
        "DEF": 1
    }
    shortages: List[Dict[str, Any]] = []
    trade_suggestions: List[Dict[str, Any]] = []

    if ignore_injured and mode != "retro":
        for pos, req_cnt in starter_requirements.items():
            healthy_at_pos = eligible_pool[eligible_pool["position"] == pos]
            if len(healthy_at_pos) < req_cnt:
                missing_cnt = req_cnt - len(healthy_at_pos)

                # Check cause of shortage at this position (BYE vs Injury vs Empty)
                pos_players = roster_df[roster_df["position"] == pos]
                has_bye = any(pos_players["is_bye"])
                has_injury = any(
                    pos_players["injury_status"].isin(severe_injuries) |
                    ((pos_players["is_reserve"] == 1) if "is_reserve" in pos_players.columns else False)
                )

                if len(pos_players) == 0:
                    reason = "missing"
                elif has_bye and not has_injury:
                    reason = "bye"
                elif has_injury and not has_bye:
                    reason = "injury"
                else:
                    reason = "mixed"

                shortages.append({
                    "position": pos,
                    "required": req_cnt,
                    "healthy_count": len(healthy_at_pos),
                    "missing": missing_cnt,
                    "reason": reason
                })

        # Generate intelligent trade / waiver suggestion if shortages detected
        if shortages and df_rosters is not None:
            all_rostered_pids = set(df_rosters["player_id"].astype(str).unique())
            
            # Identify surplus position on user's team (e.g. position with most bench players)
            bench_players = roster_df[roster_df["is_curr_starter"] == 0].copy()
            if bench_players.empty:
                bench_players = roster_df.copy()

            # Group bench depth by position
            pos_bench_counts = bench_players["position"].value_counts().to_dict()
            # Prioritize skill positions (WR, RB, TE) as trade assets
            sorted_surplus_pos = sorted(
                ["WR", "RB", "TE", "QB"],
                key=lambda p: (pos_bench_counts.get(p, 0), p != shortages[0]["position"]),
                reverse=True
            )
            surplus_pos = sorted_surplus_pos[0] if sorted_surplus_pos else "WR"

            # Filter healthy candidates first to avoid suggesting trading an injured superstar
            healthy_cands = bench_players[
                (bench_players["position"] == surplus_pos) &
                (~bench_players["injury_status"].isin(severe_injuries)) &
                (~bench_players["is_bye"])
            ].sort_values(by="score", ascending=True)

            if not healthy_cands.empty:
                cands_trade = healthy_cands
            else:
                cands_trade = bench_players[
                    (bench_players["position"] == surplus_pos) &
                    (~bench_players["is_bye"])
                ].sort_values(by="score", ascending=True)
                if cands_trade.empty:
                    cands_trade = bench_players[~bench_players["is_bye"]].sort_values(by="score", ascending=True)
                if cands_trade.empty:
                    cands_trade = bench_players.sort_values(by="score", ascending=True)

            giveaway_player = cands_trade.iloc[0].to_dict() if not cands_trade.empty else None

            # Find best free agent for the first shortage position
            target_shortage_pos = shortages[0]["position"]
            target_fa = find_top_free_agents(
                shortage_pos=target_shortage_pos,
                rostered_pids=all_rostered_pids,
                mode=mode,
                selected_week=selected_week,
                season=season,
                df_player_stats=df_player_stats,
                db_path=db_path
            )

            if giveaway_player and target_fa:
                giveaway_score = float(giveaway_player.get("score") or 0.0)
                target_score = float(target_fa.get("score") or 0.0)
                gain = round(target_score - giveaway_score, 2)
                trade_suggestions.append({
                    "shortage_pos": target_shortage_pos,
                    "giveaway": giveaway_player,
                    "target": target_fa,
                    "net_impact": gain
                })

    picked_pids = set()
    opt_by_slot: Dict[str, Dict[str, Any]] = {}

    def pick_slot_players(pos_list: List[str], count: int) -> List[Dict[str, Any]]:
        cands = eligible_pool[
            eligible_pool["position"].isin(pos_list) &
            ~eligible_pool["player_id"].isin(picked_pids)
        ].sort_values(by="score", ascending=False)

        picked = []
        for _, row in cands.head(count).iterrows():
            picked_pids.add(row["player_id"])
            picked.append(row.to_dict())

        # Fallback to non-bye players on roster if position pool exhausted
        if len(picked) < count:
            fallback = roster_df[
                roster_df["position"].isin(pos_list) &
                ~roster_df["player_id"].isin(picked_pids) &
                ~roster_df["is_bye"]
            ].sort_values(by="score", ascending=False)
            for _, row in fallback.head(count - len(picked)).iterrows():
                picked_pids.add(row["player_id"])
                picked.append(row.to_dict())

        # Final absolute fallback if entire roster at position is on bye
        if len(picked) < count:
            fallback_all = roster_df[
                roster_df["position"].isin(pos_list) &
                ~roster_df["player_id"].isin(picked_pids)
            ].sort_values(by="score", ascending=False)
            for _, row in fallback_all.head(count - len(picked)).iterrows():
                picked_pids.add(row["player_id"])
                picked.append(row.to_dict())

        return picked

    opt_pool_picks = []
    opt_pool_picks.extend(pick_slot_players(["QB"], 1))
    opt_pool_picks.extend(pick_slot_players(["RB"], 2))
    opt_pool_picks.extend(pick_slot_players(["WR"], 2))
    opt_pool_picks.extend(pick_slot_players(["TE"], 1))
    opt_pool_picks.extend(pick_slot_players(["RB", "WR", "TE"], 1))
    opt_pool_picks.extend(pick_slot_players(["K"], 1))
    opt_pool_picks.extend(pick_slot_players(["DEF"], 1))

    opt_pids = {p["player_id"] for p in opt_pool_picks}
    opt_players_by_pid = {p["player_id"]: p for p in opt_pool_picks}

    # Positional eligibility map for each slot
    slot_pos_eligibility = {
        "QB": ["QB"],
        "RB_1": ["RB"],
        "RB_2": ["RB"],
        "WR_1": ["WR"],
        "WR_2": ["WR"],
        "TE": ["TE"],
        "FLEX": ["RB", "WR", "TE"],
        "K": ["K"],
        "DEF": ["DEF"]
    }

    # Stable Slot Assignment:
    # 1. If an existing starter in slot K is also selected in the optimal 9 and eligible for slot K, KEEP them in slot K!
    for k in slot_keys:
        curr_p = curr_by_slot.get(k)
        if curr_p and curr_p["player_id"] in opt_pids and curr_p["position"] in slot_pos_eligibility.get(k, []):
            opt_by_slot[k] = opt_players_by_pid[curr_p["player_id"]]

    # 2. Fill the remaining empty slots with the unassigned optimal players
    assigned_opt_pids = {p["player_id"] for p in opt_by_slot.values()}
    unassigned_opt_players = [p for p in opt_pool_picks if p["player_id"] not in assigned_opt_pids]
    empty_slots = [k for k in slot_keys if k not in opt_by_slot]

    # Fill specific slots first (QB, RB, WR, TE, K, DEF), and FLEX last
    empty_slots_sorted = sorted(empty_slots, key=lambda s: 1 if s == "FLEX" else 0)

    for s in empty_slots_sorted:
        valid_cands = [p for p in unassigned_opt_players if p["position"] in slot_pos_eligibility.get(s, [])]
        valid_cands.sort(key=lambda x: -float(x.get("score") or 0))
        if valid_cands:
            chosen = valid_cands[0]
            opt_by_slot[s] = chosen
            unassigned_opt_players.remove(chosen)

    for k, v in opt_by_slot.items():
        v["slot"] = slot_display_names.get(k, k)

    ordered_curr_starters = [curr_by_slot[k] for k in slot_keys if k in curr_by_slot]
    optimal_starters = [opt_by_slot[k] for k in slot_keys if k in opt_by_slot]

    # Remaining players form optimal bench (categorized by BN and IR)
    optimal_bench = []
    pos_order = {"QB": 1, "RB": 2, "WR": 3, "TE": 4, "K": 5, "DEF": 6}
    for _, row in roster_df[~roster_df["player_id"].isin(picked_pids)].iterrows():
        d = row.to_dict()
        inj_st = str(d.get("injury_status", "")).strip().upper()
        p_st = str(d.get("status", "")).strip()
        is_res = int(d.get("is_reserve", 0) or 0)
        
        is_ir = (
            is_res == 1 or
            inj_st in ["IR", "PUP"] or
            p_st in ["Injured Reserve", "Physically Unable to Perform"]
        )
        d["slot"] = "IR" if is_ir else ("BYE" if d.get("is_bye", False) else "BN")
        optimal_bench.append(d)

    # Sort bench identically to Team Analytics:
    # All active bench players (BN) first, IR players grouped at the bottom
    optimal_bench.sort(
        key=lambda x: (
            1 if x.get("slot") == "IR" else 0,
            pos_order.get(x.get("position"), 99),
            -float(x.get("score") or 0)
        )
    )

    # 4. Total points and Deltas
    curr_score = round(sum(float(curr_by_slot[k].get("score") or 0.0) for k in slot_keys if k in curr_by_slot), 2)
    opt_score = round(sum(float(opt_by_slot[k].get("score") or 0.0) for k in slot_keys if k in opt_by_slot), 2)
    net_gain = round(opt_score - curr_score, 2)
    eff_pct = round((curr_score / opt_score * 100.0) if opt_score > 0 else 100.0, 1)

    # 5. Build Slot-by-Slot Comparison Table: Strictly paired by identical position slots!
    comparison_rows = []
    for k in slot_keys:
        c = curr_by_slot.get(k, {})
        o = opt_by_slot.get(k, {})
        slot_label = slot_display_names.get(k, k)
        c_score = float(c.get("score") or 0.0)
        o_score = float(o.get("score") or 0.0)
        gain = round(o_score - c_score, 2)
        is_swap = (c.get("player_id") != o.get("player_id")) if (c and o) else False

        comparison_rows.append({
            "slot": slot_label,
            "curr_player": c,
            "opt_player": o,
            "curr_score": c_score,
            "opt_score": o_score,
            "gain": gain if is_swap else 0.0,
            "is_swap": is_swap
        })

    # 6. Derive Swaps (cards) directly from table swaps
    # NEVER propose a player who is on BYE to be swapped into starting lineup!
    swaps = []
    for r in comparison_rows:
        if r["is_swap"] and r["gain"] > 0:
            opt_p = r["opt_player"]
            if opt_p and not opt_p.get("is_bye", False):
                swaps.append({
                    "slot": r["slot"],
                    "player_in": opt_p,
                    "player_out": r["curr_player"],
                    "gain": r["gain"]
                })
    swaps.sort(key=lambda s: -s["gain"])

    # 7. Matchup Impact for Retro Backward Pass
    matchup_impact = None
    if mode == "retro":
        pairings = get_matchup_pairings(league_id=league_id, week=selected_week, db_path=db_path)
        my_matchup = pairings.get(roster_id)
        if my_matchup and my_matchup.get("opponent_roster_id"):
            opp_rid = my_matchup["opponent_roster_id"]
            opp_team = df_teams[df_teams["roster_id"] == opp_rid]
            opp_name = opp_team.iloc[0]["team_name"] if not opp_team.empty else f"Team {opp_rid}"
            opp_score = float(my_matchup["opponent_points"])

            actual_won = curr_score > opp_score
            optimal_won = opt_score > opp_score

            matchup_impact = {
                "opponent_name": opp_name,
                "opponent_score": opp_score,
                "actual_won": actual_won,
                "optimal_won": optimal_won,
                "would_flip_result": (not actual_won) and optimal_won
            }

    return {
        "team_name": team_name,
        "owner_name": team_info.get("owner_name", team_name),
        "mode": mode,
        "mode_title": mode_title,
        "score_label": score_label,
        "selected_week": selected_week,
        "actual_score": curr_score,
        "optimal_score": opt_score,
        "net_gain": net_gain,
        "efficiency_pct": eff_pct,
        "swaps": swaps,
        "comparison_rows": comparison_rows,
        "optimal_bench": optimal_bench,
        "matchup_impact": matchup_impact,
        "shortages": shortages,
        "trade_suggestions": trade_suggestions,
        "ignore_injured": ignore_injured
    }


def render_optimizer_view(res: Dict[str, Any], mo) -> Any:
    """
    Render sleek, unified UI in English for the Team Optimizer tab in Marimo.
    Displays clear BYE badges on players whose teams have a bye week.
    """
    if not res:
        return mo.md("> ⚠️ **No data available.** Please select a valid team.")

    team_name = res["team_name"]
    score_label = res["score_label"]
    actual_score = res["actual_score"]
    optimal_score = res["optimal_score"]
    net_gain = res["net_gain"]
    eff_pct = res["efficiency_pct"]
    swaps = res.get("swaps", [])
    comparison_rows = res.get("comparison_rows", [])
    optimal_bench = res.get("optimal_bench", [])
    matchup_impact = res.get("matchup_impact")
    shortages = res.get("shortages", [])
    trade_suggestions = res.get("trade_suggestions", [])
    mode = res.get("mode", "projection")

    score_unit = "FPTS" if mode != "ppg" else "PPG"
    score_col_name = "Proj" if mode == "projection" else ("Pts" if mode == "retro" else "PPG")
    max_label = "Max Achievable Projections" if mode == "projection" else "Max Achievable Average"

    # Slot badge styling helper
    def get_slot_badge(slot_name: str) -> str:
        badges = {
            "QB": '<span style="display:inline-block; width:44px; text-align:center; background:#f43f5e; color:#ffffff; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">QB</span>',
            "RB": '<span style="display:inline-block; width:44px; text-align:center; background:#06b6d4; color:#ffffff; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">RB</span>',
            "WR": '<span style="display:inline-block; width:44px; text-align:center; background:#3b82f6; color:#ffffff; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">WR</span>',
            "TE": '<span style="display:inline-block; width:44px; text-align:center; background:#f59e0b; color:#ffffff; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">TE</span>',
            "FLEX": '<span style="display:inline-block; width:44px; text-align:center; background:linear-gradient(135deg, #06b6d4 0%, #3b82f6 50%, #f59e0b 100%); color:#ffffff; font-weight:800; font-size:0.68rem; padding:3px 0; border-radius:6px; letter-spacing:0.5px;">FLEX</span>',
            "K": '<span style="display:inline-block; width:44px; text-align:center; background:#a855f7; color:#ffffff; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">K</span>',
            "DEF": '<span style="display:inline-block; width:44px; text-align:center; background:#64748b; color:#ffffff; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">DEF</span>',
            "BN": '<span style="display:inline-block; width:44px; text-align:center; background:#64748b; color:#ffffff; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">BN</span>',
            "BYE": '<span style="display:inline-block; width:44px; text-align:center; background:#7c3aed; color:#ffffff; font-weight:800; font-size:0.72rem; padding:3px 0; border-radius:6px; letter-spacing:0.5px; box-shadow:0 1px 2px rgba(124,58,237,0.25);">BYE</span>',
            "IR": '<span style="display:inline-block; width:44px; text-align:center; background:#ef4444; color:#ffffff; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">IR</span>'
        }
        return badges.get(slot_name, f'<span style="display:inline-block; width:44px; text-align:center; background:#cbd5e1; color:#334155; font-weight:700; font-size:0.72rem; padding:3px 0; border-radius:6px;">{slot_name}</span>')

    # Status Dot Badge helper
    def get_status_dot(st: str) -> str:
        st = str(st).strip()
        if st in ["Healthy", "None", ""]:
            return "<span style='display:inline-flex; align-items:center; gap:5px; color:#16a34a; font-size:0.74rem; font-weight:600;'><span style='width:6px; height:6px; border-radius:50%; background:#22c55e;'></span>Healthy</span>"
        elif st in ["Questionable", "Doubtful"]:
            return f"<span style='display:inline-flex; align-items:center; gap:5px; color:#b45309; font-size:0.74rem; font-weight:600;'><span style='width:6px; height:6px; border-radius:50%; background:#f59e0b;'></span>{st}</span>"
        elif st in ["Out", "IR", "PUP", "NA"]:
            return f"<span style='display:inline-flex; align-items:center; gap:5px; color:#dc2626; font-size:0.74rem; font-weight:600;'><span style='width:6px; height:6px; border-radius:50%; background:#ef4444;'></span>{st}</span>"
        return f"<span style='color:#64748b; font-size:0.74rem;'>{st}</span>"

    # Efficiency badge styling
    if eff_pct >= 95.0:
        eff_color = "#16a34a"
        eff_bg = "#f0fdf4"
        eff_border = "#bbf7d0"
    elif eff_pct >= 85.0:
        eff_color = "#b45309"
        eff_bg = "#fefce8"
        eff_border = "#fef08a"
    else:
        eff_color = "#dc2626"
        eff_bg = "#fef2f2"
        eff_border = "#fecaca"

    # Roster Shortage Alert & Trade Recommendation Card
    shortage_alert_html = ""
    if shortages and trade_suggestions:
        cards = []
        for ts in trade_suggestions:
            sh_pos = ts["shortage_pos"]
            giveaway = ts["giveaway"]
            target = ts["target"]
            gain_val = ts["net_impact"]
            g_bye = get_bye_badge(giveaway.get("is_bye", False))
            t_bye = get_bye_badge(target.get("is_bye", False))

            card = f"""
            <div style="background:#ffffff; border:1px solid #fed7aa; border-radius:10px; padding:12px 16px; margin-top:10px; box-shadow:0 1px 3px rgba(0,0,0,0.02); display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px;">
                <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-weight:800; font-size:0.74rem; color:#b91c1c; background:#fee2e2; padding:3px 8px; border-radius:5px;">TRADE / DROP ⬇️</span>
                    <img src="{giveaway.get('headshot_url', '')}" style="width:34px; height:34px; border-radius:50%; object-fit:cover; border:1px solid #e2e8f0;" />
                    <div>
                        <div style="font-weight:700; font-size:0.88rem; color:#0f172a;">{giveaway.get('player_name')}</div>
                        <div style="font-size:0.72rem; color:#64748b; display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-top:2px;">
                            <span>{giveaway.get('nfl_team')} • {giveaway.get('position')} (Surplus)</span>
                            {f'{g_bye}' if g_bye else ''}
                            <span>•</span>
                            <strong style="color:#0f172a;">{float(giveaway.get('score') or 0):.2f} {score_unit}</strong>
                        </div>
                    </div>
                </div>

                <div style="color:#94a3b8; font-weight:800; font-size:1.1rem;">➔</div>

                <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-weight:800; font-size:0.74rem; color:#15803d; background:#dcfce7; padding:3px 8px; border-radius:5px;">ADD / TARGET ⬆️</span>
                    <img src="{target.get('headshot_url', '')}" style="width:34px; height:34px; border-radius:50%; object-fit:cover; border:1px solid #e2e8f0;" />
                    <div>
                        <div style="font-weight:700; font-size:0.88rem; color:#0f172a;">{target.get('player_name')}</div>
                        <div style="font-size:0.72rem; color:#64748b; display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-top:2px;">
                            <span>{target.get('nfl_team')} • {target.get('position')} (Free Agent)</span>
                            {f'{t_bye}' if t_bye else ''}
                            <span>•</span>
                            <strong style="color:#15803d;">{float(target.get('score') or 0):.2f} {score_unit}</strong>
                        </div>
                    </div>
                </div>

                <div style="background:#f0fdf4; border:1px solid #bbf7d0; color:#16a34a; font-weight:800; font-size:0.84rem; padding:5px 12px; border-radius:8px; margin-left:auto;">
                    Impact: {f'+{gain_val:.2f}' if gain_val > 0 else f'{gain_val:.2f}'} {score_unit}
                </div>
            </div>
            """
            cards.append(card)

        shortage_pos_names = ", ".join([s["position"] for s in shortages])
        reasons = {s.get("reason", "injury") for s in shortages}

        if reasons == {"bye"}:
            alert_title = f"Roster Shortage Alert: {shortage_pos_names} on BYE Week!"
            alert_desc = f"Your roster has no active starters at <strong>{shortage_pos_names}</strong> due to BYE weeks. To field a valid starting lineup, trade or pick up an available player from waivers:"
        elif reasons == {"injury"}:
            alert_title = f"Roster Shortage Alert: No Healthy {shortage_pos_names} Available!"
            alert_desc = f"Your roster lacks healthy starters at <strong>{shortage_pos_names}</strong> due to injuries. To field a valid starting lineup, trade or pick up an available player from waivers:"
        elif reasons == {"missing"}:
            alert_title = f"Roster Shortage Alert: No {shortage_pos_names} on Roster!"
            alert_desc = f"Your roster has no players at <strong>{shortage_pos_names}</strong>. To field a valid starting lineup, trade or pick up an available player from waivers:"
        else:
            alert_title = f"Roster Shortage Alert: No Active {shortage_pos_names} Available (BYE / Injured)!"
            alert_desc = f"Your roster lacks active starters at <strong>{shortage_pos_names}</strong> this week due to injuries and BYE weeks. To field a valid starting lineup, trade or pick up an available player from waivers:"

        shortage_alert_html = f"""
        <div style="background:#fff7ed; border:1px solid #fdba74; border-radius:12px; padding:16px 18px; margin-bottom:18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <div style="display:flex; align-items:flex-start; gap:12px;">
                <span style="font-size:1.6rem; line-height:1;">🚨</span>
                <div style="flex:1;">
                    <div style="font-weight:800; font-size:0.96rem; color:#9a3412;">{alert_title}</div>
                    <div style="font-size:0.82rem; color:#c2410c; margin-top:3px;">
                        {alert_desc}
                    </div>
                    {''.join(cards)}
                </div>
            </div>
        </div>
        """

    # Matchup What-If Card (if Backward Pass)
    matchup_card_html = ""
    if matchup_impact:
        opp_name = matchup_impact["opponent_name"]
        opp_score = matchup_impact["opponent_score"]
        if matchup_impact["would_flip_result"]:
            matchup_card_html = f"""
            <div style="background:#fef2f2; border:1px solid #f87171; border-radius:10px; padding:12px 18px; margin-top:14px; display:flex; align-items:center; gap:12px;">
                <span style="font-size:1.6rem;">🚨</span>
                <div>
                    <div style="font-weight:800; font-size:0.92rem; color:#991b1b;">WHAT-IF GAME CHANGER: You would have won this matchup!</div>
                    <div style="font-size:0.8rem; color:#b91c1c; margin-top:2px;">
                        Actual result: <strong>{actual_score:.1f}</strong> vs <strong>{opp_score:.1f}</strong> ({opp_name}) ➔ <em>Loss</em>.<br/>
                        With optimal starting lineup: <strong>{optimal_score:.1f}</strong> vs <strong>{opp_score:.1f}</strong> ➔ <strong style="color:#15803d;">VICTORY (+{optimal_score - opp_score:.1f} FPTS)!</strong>
                    </div>
                </div>
            </div>
            """
        elif matchup_impact["actual_won"]:
            matchup_card_html = f"""
            <div style="background:#f0fdf4; border:1px solid #86efac; border-radius:10px; padding:12px 18px; margin-top:14px; display:flex; align-items:center; gap:12px;">
                <span style="font-size:1.6rem;">🎉</span>
                <div>
                    <div style="font-weight:800; font-size:0.92rem; color:#166534;">Victory Secured!</div>
                    <div style="font-size:0.8rem; color:#15803d; margin-top:2px;">
                        Actual win: <strong>{actual_score:.1f}</strong> vs <strong>{opp_score:.1f}</strong> ({opp_name}). With your optimal lineup you would have reached <strong>{optimal_score:.1f} FPTS</strong>.
                    </div>
                </div>
            </div>
            """
        else:
            matchup_card_html = f"""
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:12px 18px; margin-top:14px; display:flex; align-items:center; gap:12px;">
                <span style="font-size:1.5rem;">ℹ️</span>
                <div>
                    <div style="font-weight:700; font-size:0.88rem; color:#334155;">Matchup Outcome: Defeat against {opp_name}</div>
                    <div style="font-size:0.8rem; color:#64748b; margin-top:2px;">
                        Result: <strong>{actual_score:.1f}</strong> vs <strong>{opp_score:.1f}</strong>. Even with your optimal lineup ({optimal_score:.1f} FPTS), the opponent put up too many points.
                    </div>
                </div>
            </div>
            """

    # Top KPI Box
    kpi_box_html = f"""
    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:18px 22px; margin-bottom:18px; box-shadow:0 1px 4px rgba(0,0,0,0.03); font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <!-- Top Title & Badge -->
        <div style="display:flex; justify-content:space-between; align-items:center; padding-bottom:14px; border-bottom:1px solid #f1f5f9; margin-bottom:16px;">
            <div>
                <span style="font-weight:800; font-size:1.1rem; color:#0f172a;">⚡ {res['mode_title']}</span>
                <span style="font-size:0.8rem; color:#64748b; margin-left:8px;">• {team_name}</span>
            </div>
            <div style="background:{eff_bg}; border:1px solid {eff_border}; color:{eff_color}; border-radius:12px; padding:4px 12px; font-weight:700; font-size:0.82rem;">
                🎯 Lineup Efficiency: {eff_pct:.1f}%
            </div>
        </div>

        <!-- 4 Key Figures -->
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:16px;">
            <div>
                <div style="font-size:0.74rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Current Starters</div>
                <div style="font-size:1.55rem; font-weight:800; color:#0f172a; margin:3px 0;">{actual_score:.2f} <span style="font-size:0.8rem; font-weight:600; color:#64748b;">{score_unit}</span></div>
                <div style="font-size:0.74rem; color:#94a3b8;">Basis: {score_label}</div>
            </div>
            <div>
                <div style="font-size:0.74rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Optimal Starters</div>
                <div style="font-size:1.55rem; font-weight:800; color:#0f172a; margin:3px 0;">{optimal_score:.2f} <span style="font-size:0.8rem; font-weight:600; color:#64748b;">{score_unit}</span></div>
                <div style="font-size:0.74rem; color:#94a3b8;">{max_label}</div>
            </div>
            <div>
                <div style="font-size:0.74rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Potential / Net Gain</div>
                <div style="font-size:1.55rem; font-weight:800; color:{'#16a34a' if net_gain > 0 else ('#dc2626' if net_gain < 0 else '#64748b')}; margin:3px 0;">
                    {f"+{net_gain:.2f}" if net_gain > 0 else (f"{net_gain:.2f}" if net_gain < 0 else "0.00")} <span style="font-size:0.8rem; font-weight:600;">{score_unit}</span>
                </div>
                <div style="font-size:0.74rem; color:#94a3b8;">{f'{len(swaps)} swap(s) recommended' if len(swaps) > 0 else 'No swaps needed'}</div>
            </div>
            <div>
                <div style="font-size:0.74rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Lineup Status</div>
                <div style="font-size:1.15rem; font-weight:700; color:{'#15803d' if len(swaps) == 0 else '#b45309'}; margin:5px 0;">
                    {'✅ 100% Optimal' if len(swaps) == 0 else f'🔄 {len(swaps)} Swap(s) Needed'}
                </div>
                <div style="font-size:0.74rem; color:#94a3b8;">{'Max potential unlocked' if len(swaps) == 0 else f'+{net_gain:.2f} {score_unit} left on bench'}</div>
            </div>
        </div>

        {matchup_card_html}
    </div>
    """

    # Swap Recommendations Feed
    if swaps:
        swap_cards = []
        for s in swaps:
            p_in = s["player_in"]
            p_out = s["player_out"]
            gain_val = s["gain"]
            slot_badge_html = get_slot_badge(s["slot"])
            p_in_bye = get_bye_badge(p_in.get("is_bye", False))
            p_out_bye = get_bye_badge(p_out.get("is_bye", False))

            card = f"""
            <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; background:#ffffff; border:1px solid #fed7aa; border-radius:10px; padding:10px 16px; margin-bottom:8px; box-shadow:0 1px 2px rgba(0,0,0,0.02);">
                <div style="display:flex; align-items:center; gap:10px; min-width:200px;">
                    {slot_badge_html}
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="font-weight:700; font-size:0.75rem; color:#15803d; background:#dcfce7; padding:2px 6px; border-radius:4px;">START ⬆️</span>
                        <img src="{p_in.get('headshot_url', '')}" style="width:30px; height:30px; border-radius:50%; object-fit:cover; border:1px solid #e2e8f0;" />
                        <div>
                            <div style="font-weight:700; font-size:0.86rem; color:#0f172a;">{p_in.get('player_name')}</div>
                            <div style="font-size:0.72rem; color:#64748b; display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-top:2px;">
                                <span>{p_in.get('nfl_team')} • {p_in.get('position')}</span>
                                {f'{p_in_bye}' if p_in_bye else ''}
                                <span>•</span>
                                <strong style="color:#0f172a;">{float(p_in.get('score') or 0):.2f} {score_unit}</strong>
                            </div>
                        </div>
                    </div>
                </div>

                <div style="color:#94a3b8; font-weight:700; font-size:1rem;">⟵</div>

                <div style="display:flex; align-items:center; gap:8px; min-width:200px;">
                    <span style="font-weight:700; font-size:0.75rem; color:#b91c1c; background:#fee2e2; padding:2px 6px; border-radius:4px;">BENCH ⬇️</span>
                    <img src="{p_out.get('headshot_url', '')}" style="width:30px; height:30px; border-radius:50%; object-fit:cover; border:1px solid #e2e8f0;" />
                    <div>
                        <div style="font-weight:700; font-size:0.86rem; color:#0f172a;">{p_out.get('player_name')}</div>
                        <div style="font-size:0.72rem; color:#64748b; display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-top:2px;">
                            <span>{p_out.get('nfl_team')} • {p_out.get('position')}</span>
                            {f'{p_out_bye}' if p_out_bye else ''}
                            <span>•</span>
                            <span style="color:#64748b;">{float(p_out.get('score') or 0):.2f} {score_unit}</span>
                        </div>
                    </div>
                </div>
                <div style="{'background:#f0fdf4; border:1px solid #bbf7d0; color:#16a34a;' if gain_val > 0 else ('background:#fef2f2; border:1px solid #fecaca; color:#dc2626;' if gain_val < 0 else 'background:#f8fafc; border:1px solid #e2e8f0; color:#64748b;')} font-weight:800; font-size:0.82rem; padding:4px 10px; border-radius:8px; margin-left:auto; white-space:nowrap;">
                    {f'+{gain_val:.2f}' if gain_val > 0 else (f'🛡️ Safety ({gain_val:.2f})' if gain_val < 0 else '0.00')} {score_unit}
                </div>
            </div>
            """
            swap_cards.append(card)

        swap_feed_html = f"""
        <div style="background:#fff7ed; border:1px solid #ffedd5; border-radius:12px; padding:14px 16px; margin-bottom:18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <div style="font-weight:800; font-size:0.88rem; color:#9a3412; margin-bottom:10px; display:flex; align-items:center; gap:6px;">
                <span>🔄 Recommended Lineup Swaps ({len(swaps)})</span>
                <span style="font-size:0.76rem; font-weight:normal; color:#ea580c;">— Swap these bench assets into your starting lineup for maximum output:</span>
            </div>
            {''.join(swap_cards)}
        </div>
        """
    else:
        swap_feed_html = """
        <div style="background:#f0fdf4; border:1px solid #bbf7d0; border-radius:12px; padding:14px 18px; margin-bottom:18px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display:flex; align-items:center; gap:12px;">
            <span style="font-size:1.4rem;">🎉</span>
            <div>
                <div style="font-weight:800; font-size:0.9rem; color:#166534;">Perfect Lineup! No Swaps Needed.</div>
                <div style="font-size:0.78rem; color:#15803d; margin-top:2px;">Your roster is 100% optimized. The best available options are already in your starting lineup.</div>
            </div>
        </div>
        """

    # Slot-by-Slot Comparison Table with PIXEL-PERFECT matching headers
    table_rows = []
    for r in comparison_rows:
        slot = r["slot"]
        c_p = r["curr_player"]
        o_p = r["opt_player"]
        c_score = r["curr_score"]
        o_score = r["opt_score"]
        gain = r["gain"]
        is_swap = r["is_swap"]

        slot_badge = get_slot_badge(slot)

        # Current player cell
        if c_p:
            c_name = c_p.get("player_name", "Empty")
            c_team_pos = f"{c_p.get('nfl_team', '')} • {c_p.get('position', '')}"
            c_img = c_p.get("headshot_url", "")
            c_status = get_status_dot(c_p.get("injury_status", "Healthy"))
            c_bye = get_bye_badge(c_p.get("is_bye", False))
        else:
            c_name = "<em>Empty</em>"
            c_team_pos = "—"
            c_img = ""
            c_status = ""
            c_bye = ""

        # Optimal player cell
        if o_p:
            o_name = o_p.get("player_name", "Empty")
            o_team_pos = f"{o_p.get('nfl_team', '')} • {o_p.get('position', '')}"
            o_img = o_p.get("headshot_url", "")
            o_status = get_status_dot(o_p.get("injury_status", "Healthy"))
            o_bye = get_bye_badge(o_p.get("is_bye", False))
        else:
            o_name = "<em>No Option</em>"
            o_team_pos = "—"
            o_img = ""
            o_status = ""
            o_bye = ""

        if is_swap:
            if gain > 0:
                action_badge = "<span style='background:#fef3c7; border:1px solid #fde68a; color:#b45309; font-weight:700; font-size:0.75rem; padding:3px 8px; border-radius:6px; white-space:nowrap;'>🔄 Swap</span>"
                gain_badge = f"<span style='color:#16a34a; font-weight:700;'>+{gain:.2f}</span>"
            elif gain < 0:
                action_badge = "<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; font-weight:700; font-size:0.75rem; padding:3px 8px; border-radius:6px; white-space:nowrap;'>🛡️ Safety</span>"
                gain_badge = f"<span style='color:#dc2626; font-weight:700;'>{gain:.2f}</span>"
            else:
                action_badge = "<span style='background:#fef3c7; border:1px solid #fde68a; color:#b45309; font-weight:700; font-size:0.75rem; padding:3px 8px; border-radius:6px; white-space:nowrap;'>🔄 Swap</span>"
                gain_badge = "<span style='color:#64748b; font-weight:700;'>0.00</span>"
            row_bg = "background:#fffdfa;"
        else:
            action_badge = "<span style='background:#f1f5f9; border:1px solid #e2e8f0; color:#475569; font-weight:600; font-size:0.75rem; padding:3px 8px; border-radius:6px; white-space:nowrap;'>✅ Keep</span>"
            gain_badge = "<span style='color:#94a3b8;'>0.00</span>"
            row_bg = ""

        row = f"""
        <tr style="border-bottom: 1px solid #f1f5f9; {row_bg}">
            <td style="padding:10px 8px; text-align:center; width:52px;">{slot_badge}</td>
            <td style="padding:10px 4px 10px 8px; width:44px; text-align:center;">
                <img src="{c_img}" style="width:34px; height:34px; border-radius:50%; object-fit:cover; border:1px solid #e2e8f0; display:block; margin:0 auto;" />
            </td>
            <td style="padding:10px 8px; text-align:left;">
                <div style="font-weight:700; font-size:0.86rem; color:#0f172a;">{c_name}</div>
                <div style="font-size:0.72rem; color:#64748b; display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-top:2px;">
                    <span>{c_team_pos}</span>
                    {f'{c_bye}' if c_bye else ''}
                    {c_status}
                </div>
            </td>
            <td style="padding:10px 10px; text-align:right; font-weight:600; font-size:0.88rem; color:#475569; width:80px;">
                {c_score:.2f}
            </td>
            <td style="padding:10px 4px; text-align:center; width:28px; color:#cbd5e1; font-weight:700;">➔</td>
            <td style="padding:10px 4px 10px 8px; width:44px; text-align:center;">
                <img src="{o_img}" style="width:34px; height:34px; border-radius:50%; object-fit:cover; border:1px solid #e2e8f0; display:block; margin:0 auto;" />
            </td>
            <td style="padding:10px 8px; text-align:left;">
                <div style="font-weight:700; font-size:0.86rem; color:{'#15803d' if is_swap else '#0f172a'};">{o_name}</div>
                <div style="font-size:0.72rem; color:#64748b; display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-top:2px;">
                    <span>{o_team_pos}</span>
                    {f'{o_bye}' if o_bye else ''}
                    {o_status}
                </div>
            </td>
            <td style="padding:10px 10px; text-align:right; font-weight:700; font-size:0.9rem; color:#0f172a; width:80px;">
                {o_score:.2f}
            </td>
            <td style="padding:10px 10px; text-align:right; font-size:0.84rem; width:70px;">
                {gain_badge}
            </td>
            <td style="padding:10px 10px; text-align:center; width:110px;">
                {action_badge}
            </td>
        </tr>
        """
        table_rows.append(row)

    table_html = f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-bottom:18px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'>
        <div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.9rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'>
            <span>⚡ Starting Lineup: Current vs. Optimal</span>
            <span style='font-size:0.74rem; font-weight:600; color:#64748b; background:#ffffff; border:1px solid #e2e8f0; padding:2px 8px; border-radius:12px;'>9 Starting Slots</span>
        </div>
        <div style='overflow-x:auto;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.82rem;'>
                <thead>
                    <tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.4px;'>
                        <th style='padding:9px 8px; text-align:center; width:52px;'>SLOT</th>
                        <th style='padding:9px 0; width:44px;'></th>
                        <th style='padding:9px 8px; text-align:left;'>CURRENT STARTER</th>
                        <th style='padding:9px 10px; text-align:right; width:80px;'>{score_col_name}</th>
                        <th style='padding:9px 0; text-align:center; width:28px;'></th>
                        <th style='padding:9px 0; width:44px;'></th>
                        <th style='padding:9px 8px; text-align:left;'>OPTIMAL STARTER</th>
                        <th style='padding:9px 10px; text-align:right; width:80px;'>OPT. {score_col_name}</th>
                        <th style='padding:9px 10px; text-align:right; width:70px;'>DELTA</th>
                        <th style='padding:9px 10px; text-align:center; width:110px;'>ACTION</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(table_rows)}
                </tbody>
            </table>
        </div>
    </div>
    """

    # Bench Table (remaining optimal bench players)
    bench_rows = []
    for b in optimal_bench:
        b_name = b.get("player_name", "Unknown")
        b_team = b.get("nfl_team", "")
        b_pos = b.get("position", "")
        b_score = float(b.get("score") or 0.0)
        b_img = b.get("headshot_url", "")
        b_status = get_status_dot(b.get("injury_status", "Healthy"))
        b_bye = get_bye_badge(b.get("is_bye", False))
        b_slot = get_slot_badge(b.get("slot", "BN"))

        brow = f"""
        <tr style="border-bottom: 1px solid #f1f5f9;">
            <td style="padding:8px 8px; text-align:center; width:52px;">{b_slot}</td>
            <td style="padding:8px 4px 8px 8px; width:44px; text-align:center;">
                <img src="{b_img}" style="width:32px; height:32px; border-radius:50%; object-fit:cover; border:1px solid #e2e8f0; display:block; margin:0 auto;" />
            </td>
            <td style="padding:8px 8px; text-align:left;">
                <div style="font-weight:700; font-size:0.85rem; color:#0f172a;">{b_name}</div>
                <div style="font-size:0.72rem; color:#64748b; margin-top:2px;">
                    {b_team} • {b_pos}
                </div>
            </td>
            <td style="padding:8px 10px; text-align:center; width:120px;">
                <div style="display:inline-flex; align-items:center; justify-content:center; gap:5px;">
                    {b_status}
                </div>
            </td>
            <td style="padding:8px 16px; text-align:right; font-weight:700; font-size:0.88rem; color:#334155; width:140px;">
                {b_score:.2f}
            </td>
        </tr>
        """
        bench_rows.append(brow)

    # Calculate Bench vs IR vs BYE count badge identical to Team Analytics
    ir_cnt = sum(1 for b in optimal_bench if b.get("slot") == "IR")
    bye_cnt = sum(1 for b in optimal_bench if b.get("slot") == "BYE")
    bn_cnt = len(optimal_bench) - ir_cnt - bye_cnt
    parts = []
    if bn_cnt > 0:
        parts.append(f"{bn_cnt} BN")
    if bye_cnt > 0:
        parts.append(f"{bye_cnt} BYE")
    if ir_cnt > 0:
        parts.append(f"{ir_cnt} IR")
    if parts:
        joined_parts = " + ".join(parts)
        bench_count_badge = f"{len(optimal_bench)} Players ({joined_parts})"
    else:
        bench_count_badge = f"{len(optimal_bench)} Players"

    bench_html = f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-bottom:18px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'>
        <div style='background:#f8fafc; padding:10px 18px; font-weight:700; font-size:0.86rem; color:#1e293b; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'>
            <span>🪑 Optimal Bench</span>
            <span style='font-size:0.74rem; font-weight:600; color:#64748b; background:#ffffff; border:1px solid #e2e8f0; padding:2px 8px; border-radius:12px;'>{bench_count_badge}</span>
        </div>
        <div style='overflow-x:auto;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.82rem;'>
                <thead>
                    <tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.4px;'>
                        <th style='padding:8px 8px; text-align:center; width:52px;'>SLOT</th>
                        <th style='padding:8px 0; width:44px;'></th>
                        <th style='padding:8px 8px; text-align:left;'>PLAYER</th>
                        <th style='padding:8px 10px; text-align:center; width:120px;'>STATUS</th>
                        <th style='padding:8px 16px; text-align:right; width:140px;'>{score_label.upper()}</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(bench_rows)}
                </tbody>
            </table>
        </div>
    </div>
    """

    return mo.vstack([
        mo.Html(shortage_alert_html) if shortage_alert_html else mo.md(""),
        mo.Html(kpi_box_html),
        mo.Html(swap_feed_html),
        mo.Html(table_html),
        mo.Html(bench_html)
    ], gap=0)
