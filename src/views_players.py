import pandas as pd
from typing import Dict, Any, Optional, List, Union
from src.config import NFL_TEAM_COLORS, NFL_TEAM_NAMES
from src.visual import build_player_weekly_bar_chart, build_player_comparison_chart


def _build_profile_header_html(data: Any, owner_colors: Optional[Dict[str, str]] = None) -> str:
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
                <div style='font-size:0.75rem; color:#cbd5e1; font-weight:700;'>-</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#64748b; text-transform:uppercase;'>Baseline</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#64748b;'>{data.get('baseline', 8.0):.1f}</div>
                </div>
                <div style='font-size:0.75rem; color:#cbd5e1; font-weight:700;'>=</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#2563eb; text-transform:uppercase;'>Raw VORP</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#2563eb;'>{data.get('vorp', 0.0):+.1f}</div>
                </div>
                <div style='font-size:0.75rem; color:#cbd5e1; font-weight:700;'>×</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#64748b; text-transform:uppercase;'>Scarcity</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#64748b;'>{data.get('scarcity_weight', 1.0):.1f}x</div>
                </div>
                {f'''<div style='font-size:0.75rem; color:#cbd5e1; font-weight:700;'>×</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#16a34a; text-transform:uppercase;'>Elite Prem.</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#16a34a;'>{data.get('elite_multiplier', 1.0):.2f}x</div>
                </div>''' if data.get('elite_multiplier', 1.0) > 1.0 else ''}
                {f'''<div style='font-size:0.75rem; color:#cbd5e1; font-weight:700;'>×</div>
                <div style='text-align:center;'>
                    <div style='font-size:0.62rem; font-weight:700; color:#dc2626; text-transform:uppercase;'>Inj. Disc.</div>
                    <div style='font-size:0.95rem; font-weight:800; color:#dc2626;'>{data.get('injury_discount'):.2f}x</div>
                </div>''' if data.get('injury_discount') and data.get('injury_discount') < 1.0 else ''}
            </div>
            <!-- Final Scaled Market Score -->
            <div style='text-align:right; background:#f0fdf4; border:1.5px solid #bbf7d0; border-radius:12px; padding:10px 18px;'>
                <div style='font-size:0.68rem; font-weight:800; color:#15803d; text-transform:uppercase; letter-spacing:0.5px;'>Market Trade Value</div>
                <div style='font-size:1.65rem; font-weight:900; color:#15803d; line-height:1.1;'>{data['trade_value']:.1f} <span style='font-size:0.85rem; font-weight:700; color:#16a34a;'>TV</span></div>
                <div style='font-size:0.65rem; color:#16a34a; font-weight:600;'>0-100 Scaled VORP</div>
            </div>
        </div>
    </div>
    """


def _build_profile_kpi_html(data: Any) -> str:
    proj_kpi = ""
    if data.get('proj_total_games', 0) > 0:
        beat_pct = data['proj_beat_pct']
        beat_count = data['proj_beat_count']
        tot_proj_g = data['proj_total_games']
        net_diff = data['proj_net_diff']
        avg_diff = data['proj_avg_diff']
        diff_col = "#16a34a" if net_diff >= 0 else "#dc2626"
        diff_sign = "+" if net_diff >= 0 else ""

        proj_kpi = f"""
        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>🎯 Beat Projections</div>
            <div style='font-size:1.45rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'>{beat_pct:.0f}% <span style='font-size:0.8rem; font-weight:600; color:#64748b;'>({beat_count}/{tot_proj_g} G)</span></div>
            <div style='font-size:0.74rem; color:{diff_col}; font-weight:700;'>{diff_sign}{avg_diff:.1f} avg vs exp ({diff_sign}{net_diff:.1f} net)</div>
        </div>
        """

    return f"""
    <div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:16px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'>
        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>📈 Season PPG</div>
            <div style='font-size:1.45rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'>{data['mean_points']:.2f} <span style='font-size:0.8rem; font-weight:600; color:#64748b;'>FPTS</span></div>
            <div style='font-size:0.74rem; color:#1d4ed8; font-weight:700;'>#{data['pos_rank']} at {data['position']}</div>
        </div>

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>📊 Variance Profile</div>
            <div style='font-size:1.25rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'>{data['consistency_tier']}</div>
            <div style='font-size:0.74rem; color:#64748b;'>Std Dev: <strong>±{data['std_points']:.1f} FPTS</strong></div>
        </div>

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>🏥 Availability</div>
            <div style='font-size:1.45rem; font-weight:800; color:{data['health_color']}; margin:3px 0 1px 0;'>{data['availability_pct']:.0f}% <span style='font-size:0.8rem; font-weight:600; color:#64748b;'>({data['games_played']}/{data['total_active_weeks']} Wks)</span></div>
            <div style='font-size:0.74rem; color:#64748b; font-weight:600;'>{data['health_assessment']}</div>
        </div>

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>↕️ Floor / Ceiling</div>
            <div style='font-size:1.2rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'>{data['floor_points']:.1f} <span style='font-size:0.8rem; font-weight:400; color:#94a3b8;'>to</span> {data['ceiling_points']:.1f}</div>
            <div style='font-size:0.74rem; color:#64748b;'>Median: <strong>{data['median_points']:.1f} FPTS</strong></div>
        </div>

        {proj_kpi}

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>🏆 Best Week</div>
            <div style='font-size:1.45rem; font-weight:800; color:#15803d; margin:3px 0 1px 0;'>{data['ceiling_points']:.1f} <span style='font-size:0.8rem; font-weight:600; color:#64748b;'>FPTS</span></div>
            <div style='font-size:0.74rem; color:#64748b;'>Week {int(data['best_week']) if pd.notna(data['best_week']) and data['best_week'] else '—'}</div>
        </div>

        <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);'>
            <div style='font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;'>📊 Total Output</div>
            <div style='font-size:1.45rem; font-weight:800; color:#0f172a; margin:3px 0 1px 0;'>{data['total_points']:.1f} <span style='font-size:0.8rem; font-weight:600; color:#64748b;'>FPTS</span></div>
            <div style='font-size:0.74rem; color:#64748b;'>{data.get('history_summary_str', f"{data['games_played']} games in 2026")}</div>
        </div>
    </div>
    """


def _build_chart_header_html(data: Any) -> str:
    from src.players import resolve_nfl_team
    w_df = data.get('weekly_df', pd.DataFrame())

    unique_teams = []
    if not w_df.empty and 'nfl_team' in w_df.columns:
        for t in w_df.sort_values(by=['season', 'week'], ascending=[False, False])['nfl_team'].dropna().unique():
            t_clean = resolve_nfl_team(t, fallback="")
            if t_clean and t_clean not in ('FA', '') and t_clean not in unique_teams:
                unique_teams.append(t_clean)

    curr_team = resolve_nfl_team(data.get('nfl_team'), fallback="")
    if curr_team and curr_team not in ('FA', '') and curr_team not in unique_teams:
        unique_teams.insert(0, curr_team)

    if not unique_teams and curr_team:
        unique_teams = [curr_team]

    # Full team names with individual franchise color boxes
    team_items = []
    for t_code in unique_teams:
        t_col = NFL_TEAM_COLORS.get(t_code, '#00338D')
        t_full = NFL_TEAM_NAMES.get(t_code, f"{t_code} Franchise")
        team_items.append(
            f"<div style='display:flex; align-items:center; gap:6px;'>"
            f"<span style='width:12px; height:12px; background:{t_col}; border-radius:3px; display:inline-block;'></span>"
            f"<span style='font-weight:600; color:#334155;'>{t_full}</span>"
            f"</div>"
        )
    team_items_html = "".join(team_items)

    # Adaptive needle color (silver-grey #94a3b8 on dark teams like LV, SEA, CHI; black #000000 on light/colorful teams)
    curr_t_col = NFL_TEAM_COLORS.get(curr_team.upper(), '#00338D')
    is_dark_team = False
    try:
        if curr_t_col and curr_t_col.startswith('#') and len(curr_t_col) >= 7:
            r = int(curr_t_col[1:3], 16)
            g = int(curr_t_col[3:5], 16)
            b = int(curr_t_col[5:7], 16)
            is_dark_team = (0.299 * r + 0.587 * g + 0.114 * b) < 50.0
    except Exception:
        pass
    needle_col = '#94a3b8' if is_dark_team else '#000000'

    has_proj = 'projected_points' in w_df.columns and (w_df['projected_points'] > 0).any() if not w_df.empty else False
    proj_html = f"""
    <div style='display:flex; align-items:center; gap:6px;'>
        <span style='width:3.5px; height:12px; background:{needle_col}; border-radius:1px; display:inline-block;'></span>
        <span style='font-weight:600; color:#334155;'>🎯 Proj Target</span>
    </div>
    """ if has_proj else ""

    mean_pts = data.get('mean_points', 0.0)

    return f"""
    <div style='display:flex; justify-content:space-between; align-items:center; margin:16px 0 8px 0; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; flex-wrap:wrap; gap:10px;'>
        <div style='font-size:0.95rem; font-weight:800; color:#0f172a;'>
            📅 Weekly Scoring Progression & Multi-Season History
        </div>
        <div style='display:flex; align-items:center; gap:16px; font-size:0.75rem; color:#64748b; flex-wrap:wrap;'>
            {team_items_html}
            {proj_html}
            <div style='display:flex; align-items:center; gap:6px;'>
                <span style='width:16px; height:2px; background:#ef4444; border-top:2px dashed #ef4444; display:inline-block;'></span>
                <span style='color:#dc2626; font-weight:700;'>Season Avg: {mean_pts:.1f} FPTS</span>
            </div>
        </div>
    </div>
    """


def _build_profile_log_table_html(data: Any) -> str:
    from src.players import resolve_nfl_team
    w_df = data['weekly_df']
    player_nfl = resolve_nfl_team(data.get('nfl_team', 'FA'), fallback="FA")

    game_rows = []
    if w_df is not None and not w_df.empty:
        for _, r in w_df.sort_values(by='week', ascending=False).iterrows():
            wk = int(r['week'])
            pts = float(r['points']) if pd.notna(r['points']) else 0.0

            # Projections
            proj = float(r['projected_points']) if 'projected_points' in r and pd.notna(r['projected_points']) else None
            if proj is not None:
                p_diff = pts - proj
                p_diff_color = "#16a34a" if p_diff >= 0 else "#dc2626"
                p_diff_str = f"+{p_diff:.1f}" if p_diff >= 0 else f"{p_diff:.1f}"
                proj_cell = f"<td style='padding:8px 12px; text-align:right;'><span style='color:#64748b; font-weight:600;'>{proj:.1f}</span> <span style='font-size:0.7rem; color:{p_diff_color}; font-weight:700;'>({p_diff_str})</span></td>"
            else:
                proj_cell = "<td style='padding:8px 12px; text-align:right; color:#94a3b8;'>—</td>"

            opp = r.get('opponent')
            opp_code = resolve_nfl_team(opp, fallback="")
            if not opp_code or opp_code == "FA" or opp_code == player_nfl:
                opp_code = "BYE / Off"
            opp_str = f"vs {opp_code}" if opp_code != "BYE / Off" else "<span style='color:#94a3b8;'>BYE</span>"

            status = r.get('fantasy_status', 'FA')
            if status == 'Starter':
                status_badge = "<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:6px; padding:2px 8px; font-weight:700; font-size:0.72rem;'>Starter</span>"
            elif status == 'Bench':
                status_badge = "<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#64748b; border-radius:6px; padding:2px 8px; font-weight:600; font-size:0.72rem;'>Bench</span>"
            else:
                status_badge = "<span style='color:#94a3b8; font-size:0.72rem;'>FA</span>"

            stat_line_parts = []
            if 'pass_yd' in r and float(r.get('pass_yd', 0)) > 0:
                stat_line_parts.append(f"{int(r['pass_yd'])} Pass Yds, {int(r.get('pass_td', 0))} TD")
            if 'rush_yd' in r and float(r.get('rush_yd', 0)) > 0:
                stat_line_parts.append(f"{int(r['rush_yd'])} Rush Yds, {int(r.get('rush_td', 0))} TD")
            if 'rec' in r and float(r.get('rec', 0)) > 0:
                stat_line_parts.append(f"{int(r['rec'])} Rec, {int(r.get('rec_yd', 0))} Yds, {int(r.get('rec_td', 0))} TD")
            stat_line = " • ".join(stat_line_parts) if stat_line_parts else "—"

            game_rows.append(f"""
            <tr style='border-bottom:1px solid #f1f5f9; height:40px;'>
                <td style='padding:8px 12px; font-weight:700; color:#0f172a;'>Week {wk}</td>
                <td style='padding:8px 12px; color:#475569;'>{opp_str}</td>
                <td style='padding:8px 12px; text-align:center;'>{status_badge}</td>
                {proj_cell}
                <td style='padding:8px 12px; text-align:right; font-weight:800; color:{'#15803d' if pts >= 18 else ('#2563eb' if pts >= 10 else '#64748b')};'>{pts:.2f}</td>
                <td style='padding:8px 12px; color:#64748b; font-size:0.78rem;'>{stat_line}</td>
            </tr>
            """)

    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:16px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'>
        <div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'>
            <span>📜 Game Log</span>
            <span style='font-size:0.75rem; color:#64748b;'>{len(game_rows)} Recorded Weeks</span>
        </div>
        <div style='overflow-x:auto;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.84rem;'>
                <thead>
                    <tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px;'>
                        <th style='padding:10px 12px; text-align:left;'>Week</th>
                        <th style='padding:10px 12px; text-align:left;'>Opponent</th>
                        <th style='padding:10px 12px; text-align:center;'>Matchup Role</th>
                        <th style='padding:10px 12px; text-align:right;'>Projected</th>
                        <th style='padding:10px 12px; text-align:right;'>Fantasy Pts</th>
                        <th style='padding:10px 12px; text-align:left;'>Key Statistics</th>
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
    data: Any,
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


def _build_comp_headers_html(comp_data: Any, owner_colors: Optional[Dict[str, str]] = None) -> str:
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

    def render_card(p, is_left: bool) -> str:
        border_col = "#2563eb" if is_left else "#059669"
        bg_pill = "#eff6ff" if is_left else "#ecfdf5"
        text_pill = "#1d4ed8" if is_left else "#047857"
        owner_c = (owner_colors or {}).get(p['owner_name'], '#64748b')

        inj = p['injury_status']
        inj_html = f"<span style='background:#fef3c7; color:#b45309; border:1px solid #fde68a; font-size:0.7rem; font-weight:700; border-radius:4px; padding:1px 6px;'>{inj}</span>" if inj != 'Healthy' else ""

        return f"""
        <div style='background:#ffffff; border:1.5px solid {border_col}; border-radius:14px; padding:16px 20px; box-shadow:0 2px 6px rgba(0,0,0,0.03); flex:1; min-width:280px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'>
            <div style='display:flex; align-items:center; gap:16px;'>
                <img src='{p['headshot_url']}' style='width:64px; height:64px; border-radius:50%; object-fit:cover; background:#f1f5f9; border:2.5px solid {border_col};' onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'" />
                <div style='flex:1;'>
                    <div style='display:flex; align-items:center; gap:8px;'>
                        <span style='font-size:1.3rem; font-weight:800; color:#0f172a;'>{p['player_name']}</span>
                        <span style='background:{pos_colors.get(p['position'], '#2563eb')}; color:#ffffff; font-weight:800; font-size:0.72rem; border-radius:4px; padding:2px 7px;'>{p['position']}</span>
                        <span style='background:#f1f5f9; color:#475569; font-weight:700; font-size:0.72rem; border-radius:4px; padding:2px 7px; border:1px solid #e2e8f0;'>{p['nfl_team']}</span>
                        {inj_html}
                    </div>
                    <div style='display:flex; align-items:center; gap:8px; margin-top:4px; font-size:0.78rem; color:#64748b;'>
                        <span style='display:inline-flex; align-items:center; gap:4px;'>
                            <span style='width:7px; height:7px; border-radius:50%; background:{owner_c};'></span>
                            <strong style='color:#334155;'>Owner:</strong> {p['owner_name']}
                        </span>
                        <span>•</span>
                        <span>Rank: <strong style='color:{text_pill};'>#{p['pos_rank']} {p['position']}</strong></span>
                    </div>
                </div>
                <div style='text-align:right;'>
                    <div style='background:{bg_pill}; border:1px solid {border_col}; border-radius:8px; padding:6px 12px;'>
                        <div style='font-size:0.65rem; font-weight:800; color:{text_pill}; text-transform:uppercase;'>Season PPG</div>
                        <div style='font-size:1.35rem; font-weight:900; color:{text_pill};'>{p['mean_points']:.2f}</div>
                    </div>
                </div>
            </div>
        </div>
        """

    card_a = render_card(p_a, is_left=True)
    card_b = render_card(p_b, is_left=False)

    return f"""
    <div style='display:flex; gap:14px; flex-wrap:wrap; margin-bottom:14px;'>
        {card_a}
        {card_b}
    </div>
    """


def _build_comp_banner_html(comp_data: Any) -> str:
    p_a = comp_data['player_a']
    p_b = comp_data['player_b']
    score_a = comp_data['wins_a']
    score_b = comp_data['wins_b']
    ties = comp_data['ties']

    if score_a > score_b:
        sub = f"<strong>{p_a['player_name']}</strong> outscored <strong>{p_b['player_name']}</strong> in {score_a} of {score_a + score_b + ties} weeks"
        lead_pill = f"<span style='background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; font-weight:800; padding:4px 12px; border-radius:12px; font-size:0.8rem;'>{p_a['player_name']} Leads {score_a}–{score_b}</span>"
    elif score_b > score_a:
        sub = f"<strong>{p_b['player_name']}</strong> outscored <strong>{p_a['player_name']}</strong> in {score_b} of {score_a + score_b + ties} weeks"
        lead_pill = f"<span style='background:#ecfdf5; color:#047857; border:1px solid #a7f3d0; font-weight:800; padding:4px 12px; border-radius:12px; font-size:0.8rem;'>{p_b['player_name']} Leads {score_b}–{score_a}</span>"
    else:
        sub = f"Both players are tied with <strong>{score_a} weekly wins</strong> each"
        lead_pill = f"<span style='background:#f8fafc; color:#475569; border:1px solid #cbd5e1; font-weight:800; padding:4px 12px; border-radius:12px; font-size:0.8rem;'>Tied Series {score_a}–{score_b}</span>"

    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:14px 20px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'>
        <div>
            <div style='font-size:0.95rem; font-weight:800; color:#0f172a;'>⚔️ Head-to-Head Scoring Record</div>
            <div style='font-size:0.82rem; color:#64748b; margin-top:2px;'>{sub}</div>
        </div>
        <div>
            {lead_pill}
        </div>
    </div>
    """


def _build_comp_verdict_html(comp_data: Any) -> str:
    bullets_html = "".join([f"<li style='margin-bottom:6px;'>{b}</li>" for b in comp_data['verdict_bullets']])
    return f"""
    <div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:18px 22px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,0.03); font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'>
        <div style='display:flex; align-items:center; gap:8px; margin-bottom:10px;'>
            <span style='font-size:1.15rem;'>📊</span>
            <span style='font-weight:800; font-size:0.95rem; color:#0f172a;'>Comparative Performance Summary</span>
        </div>
        <ul style='margin:0 0 12px 18px; padding:0; font-size:0.84rem; color:#334155; line-height:1.5;'>
            {bullets_html}
        </ul>
        <div style='background:#f8fafc; border-left:3px solid #2563eb; padding:10px 14px; border-radius:6px; font-size:0.84rem; color:#0f172a;'>
            📊 {comp_data['recommendation']}
        </div>
    </div>
    """


def _build_comp_tape_html(comp_data: Any) -> str:
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
            <span>📋 Side-by-Side Metric Comparison</span>
            <span style='font-size:0.75rem; color:#64748b;'>✓ Indicates statistical advantage</span>
        </div>
        <div style='overflow-x:auto;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.84rem;'>
                <thead>
                    <tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px;'>
                        <th style='padding:10px 16px; text-align:right; width:36%; color:#1d4ed8;'>{p_a['player_name']}</th>
                        <th style='padding:10px 12px; text-align:center; width:28%;'>Metric</th>
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


def _build_comp_chart_header(comp_data: Any) -> str:
    p_a = comp_data['player_a']
    p_b = comp_data['player_b']

    return f"""
    <div style='display:flex; justify-content:space-between; align-items:center; margin:16px 0 8px 0; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'>
        <div style='font-size:0.95rem; font-weight:800; color:#0f172a;'>
            📊 Weekly Scoring Trajectory (2026 Regular Season)
        </div>
        <div style='display:flex; align-items:center; gap:16px; font-size:0.78rem; color:#64748b;'>
            <div style='display:flex; align-items:center; gap:6px;'>
                <span style='width:12px; height:12px; background:#2563eb; border-radius:3px; display:inline-block;'></span>
                <span style='font-weight:700; color:#1d4ed8;'>{p_a['player_name']}</span>
            </div>
            <div style='display:flex; align-items:center; gap:6px;'>
                <span style='width:12px; height:12px; background:#059669; border-radius:3px; display:inline-block;'></span>
                <span style='font-weight:700; color:#047857;'>{p_b['player_name']}</span>
            </div>
        </div>
    </div>
    """


def _build_comp_h2h_table(comp_data: Any) -> str:
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
            <span>📅 Week-by-Week Scoring Comparison</span>
            <span style='font-size:0.78rem; font-weight:700; color:#0f172a;'>{p_a['player_name']} {score_a} — {score_b} {p_b['player_name']}</span>
        </div>
        <div style='overflow-x:auto;'>
            <table style='width:100%; border-collapse:collapse; font-size:0.84rem;'>
                <thead>
                    <tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px;'>
                        <th style='padding:10px 14px; text-align:left;'>Week</th>
                        <th style='padding:10px 14px; text-align:right; width:130px; color:#1d4ed8;'>{p_a['player_name']}</th>
                        <th style='padding:10px 14px; text-align:right; width:130px; color:#047857;'>{p_b['player_name']}</th>
                        <th style='padding:10px 14px; text-align:center; width:200px;'>Weekly Advantage</th>
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
    comp_data: Any,
    owner_colors: Optional[Dict[str, str]] = None,
    mo: Any = None
) -> Any:
    """
    Produce clean Marimo-native rendered view for head-to-head player comparison.
    Combines player cards, comparative summary card, side-by-side metric table, Altair grouped chart, and weekly matchup table.
    """
    if mo is None:
        import marimo as mo

    if not comp_data:
        return mo.md("Please select two players to compare.")

    headers_html = _build_comp_headers_html(comp_data, owner_colors)
    banner_html = _build_comp_banner_html(comp_data)
    verdict_html = _build_comp_verdict_html(comp_data)
    tape_html = _build_comp_tape_html(comp_data)
    chart_hdr = _build_comp_chart_header(comp_data)
    h2h_html = _build_comp_h2h_table(comp_data)

    chart = build_player_comparison_chart(
        comp_df=comp_data['combined_chart_df'],
        player_a_name=comp_data['player_a']['player_name'],
        player_b_name=comp_data['player_b']['player_name'],
        chart_width=860,
        chart_height=300
    )

    return mo.vstack([
        mo.Html(headers_html),
        mo.Html(banner_html),
        mo.Html(verdict_html),
        mo.Html(tape_html),
        mo.Html(chart_hdr),
        mo.ui.altair_chart(chart),
        mo.Html(h2h_html)
    ], gap=1)
