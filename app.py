import marimo

__generated_with = "0.24.2"
app = marimo.App(
    width="full",
    app_title="🏈 NFL Fantasy Analytics",
    html_head_file="templates/update_banner.html"
)


@app.cell
def _():
    import marimo as mo
    import pandas as pd
    import numpy as np

    from src.config import DB_PATH, DEFAULT_LEAGUE_ID, DEFAULT_TEAM_NAME, VERSION
    from src.db import format_last_sync, get_last_sync_time, load_league_data, load_team_matchups
    from src.optimizer import get_current_nfl_week, optimize_team_lineup, render_optimizer_view
    from src.stats import (
        compute_player_aggregates,
        get_league_overview_analytics,
        get_team_roster_analytics,
        get_luck_and_all_play_analytics
    )
    from src.moves import get_roster_move_analytics, render_roster_moves_html
    from src.players import (
        get_player_selection_options,
        get_player_detailed_analytics,
        get_player_comparison_analytics,
        render_player_profile_view,
        render_player_comparison_view,
    )
    from src.sync import start_background_scheduler
    from src.visual import build_interactive_position_chart, get_owner_color_map
    from src.trades import (
        analyze_team_needs_and_surplus,
        calculate_player_trade_values,
        generate_trade_recommendations,
        render_player_market_view,
        render_trade_finder_view,
        simulate_custom_trade
    )

    import altair as alt
    try:
        from marimo._plugins.ui._impl.charts.altair_transformer import register_transformers
        register_transformers()
        alt.data_transformers.enable('marimo_inline_csv')
    except Exception:
        pass

    # Ensure in-process background auto-sync scheduler is running (reliable across local & Docker environments)
    start_background_scheduler(league_id=DEFAULT_LEAGUE_ID)

    # Lightweight observer: update document title, link icon, and custom UI style tweaks
    head_favicon = mo.Html(
        """
        <style>
        /* Mode switch: Keep active blue accent in both states so it toggles between two modes without turning grey */
        marimo-switch[data-label="null"] button[role="switch"],
        marimo-switch[data-label="null"] button[data-state="unchecked"],
        marimo-switch[data-label="null"] button[data-state="checked"] {
            background-color: #2563eb !important;
        }
        marimo-switch[data-label="null"] button[role="switch"]:hover,
        marimo-switch[data-label="null"] button[data-state="unchecked"]:hover,
        marimo-switch[data-label="null"] button[data-state="checked"]:hover {
            background-color: #1d4ed8 !important;
        }
        </style>
        <script>
        (function() {
            function setFavicon() {
                document.title = "🏈 NFL Fantasy Analytics";
                var link = document.querySelector("link[rel*='icon']");
                if (!link) {
                    link = document.createElement('link');
                    link.rel = 'shortcut icon';
                    document.getElementsByTagName('head')[0].appendChild(link);
                }
                if (link.getAttribute('href') !== 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🏈</text></svg>') {
                    link.type = 'image/svg+xml';
                    link.href = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🏈</text></svg>';
                }
            }
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', setFavicon);
            } else {
                setFavicon();
            }
            setTimeout(setFavicon, 1000);
            setTimeout(setFavicon, 3000);
        })();
        </script>
        """
    )

    return (
        DB_PATH,
        DEFAULT_LEAGUE_ID,
        DEFAULT_TEAM_NAME,
        VERSION,
        analyze_team_needs_and_surplus,
        build_interactive_position_chart,
        calculate_player_trade_values,
        compute_player_aggregates,
        format_last_sync,
        generate_trade_recommendations,
        get_last_sync_time,
        get_league_overview_analytics,
        get_luck_and_all_play_analytics,
        get_owner_color_map,
        get_team_roster_analytics,
        head_favicon,
        load_league_data,
        load_team_matchups,
        get_current_nfl_week,
        mo,
        np,
        optimize_team_lineup,
        render_optimizer_view,
        render_player_market_view,
        render_trade_finder_view,
        simulate_custom_trade,
        get_roster_move_analytics,
        render_roster_moves_html,
        get_player_selection_options,
        get_player_detailed_analytics,
        get_player_comparison_analytics,
        render_player_profile_view,
        render_player_comparison_view,
    )


@app.cell
def _(head_favicon):
    head_favicon
    return


@app.cell
def _(mo):
    # Top tab navigation with refresh widget (manual on-demand or user-selected interval, defaults to no auto-tick)
    refresh_btn = mo.ui.refresh(
        options=["30s", "1m", "5m"],
        default_interval=None,
    )
    nav_tabs = mo.ui.tabs({
        "🏆 League Overview": mo.md(""),
        "🛡️ Team Analytics": mo.md(""),
        "⚡ Team Optimizer": mo.md(""),
        "🍀 Luck & All-Play": mo.md(""),
        "📜 Roster Moves": mo.md(""),
        "🤝 Trade Finder": mo.md(""),
        "👤 Player Stats": mo.md(""),
        "💎 Player Market": mo.md(""),
        "📊 Position Scatter": mo.md("")
    })
    _top_bar = mo.hstack([nav_tabs, refresh_btn], justify="space-between", align="center")
    _top_bar
    return nav_tabs, refresh_btn


@app.cell
def _(
    DB_PATH,
    DEFAULT_LEAGUE_ID,
    compute_player_aggregates,
    get_owner_color_map,
    load_league_data,
    load_team_matchups,
    refresh_btn,
):
    _ = refresh_btn.value  # Reactive dependency: re-runs when refresh timer ticks or button clicked
    df_teams, df_current_rosters, df_matchups, df_nfl_stats = load_league_data(DB_PATH, DEFAULT_LEAGUE_ID)
    df_team_matchups = load_team_matchups(DB_PATH, DEFAULT_LEAGUE_ID)
    df_player_stats = compute_player_aggregates(df_nfl_stats) if df_nfl_stats is not None else None

    unique_teams = sorted([t for t in df_teams['team_name'].unique()]) if df_teams is not None and not df_teams.empty else []
    owner_colors = get_owner_color_map(unique_teams)
    return (
        df_current_rosters,
        df_matchups,
        df_nfl_stats,
        df_player_stats,
        df_team_matchups,
        df_teams,
        owner_colors,
        unique_teams,
    )


@app.cell
def _(df_teams, mo):
    if df_teams is None or df_teams.empty:
        mo.stop(
            mo.md(
                """
                > ⚠️ **No data found in `data/fantasy.db`!**  
                > Please run `python downloader.py` to populate the database.
                """
            )
        )
    return


@app.cell
def _(mo):
    # Persistent Position Scatter UI controls (never reset across tab switches or background refreshes)
    pos_select = mo.ui.radio(
        options=["QB", "RB", "WR", "TE", "DEF", "K"],
        value="QB",
        inline=True,
        label="Position:"
    )
    min_pts_slider = mo.ui.slider(
        start=0,
        stop=20,
        step=1,
        value=3,
        label="Min Avg Points:"
    )
    limit_slider = mo.ui.slider(
        start=10,
        stop=35,
        step=5,
        value=20,
        label="Max Players:"
    )
    return limit_slider, min_pts_slider, pos_select


@app.cell
def _(get_current_nfl_week, mo):
    # Persistent Team Optimizer UI controls (week, mode, injury switches)
    _curr_wk = get_current_nfl_week()
    _week_options = {f"🏈 Week {_curr_wk} (Upcoming)": _curr_wk}
    for _w in range(_curr_wk - 1, 0, -1):
        _week_options[f"📜 Week {_w} (Completed)"] = _w

    opt_week_dropdown = mo.ui.dropdown(
        options=_week_options,
        value=list(_week_options.keys())[0] if _week_options else None,
        label="Week:"
    )

    opt_mode_switch = mo.ui.switch(
        value=False
    )

    opt_injury_switch = mo.ui.switch(
        value=True,
        label="🛡️ Bench Inactive & BYE Players (Out / IR / Doubtful / BYE)"
    )
    return opt_injury_switch, opt_mode_switch, opt_week_dropdown


@app.cell
def _(DB_PATH, DEFAULT_LEAGUE_ID, DEFAULT_TEAM_NAME, mo):
    # Persistent Team Selector UI control (shared across Team Analytics and Team Optimizer)
    import sqlite3
    _team_names = []
    if DB_PATH.exists():
        try:
            _conn = sqlite3.connect(str(DB_PATH))
            _cur = _conn.cursor()
            _cur.execute(
                "SELECT DISTINCT team_name FROM teams WHERE league_id = ? ORDER BY team_name",
                (DEFAULT_LEAGUE_ID,)
            )
            _rows = _cur.fetchall()
            _team_names = [r[0] for r in _rows if r[0]]
            _conn.close()
        except Exception:
            pass

    if not _team_names:
        _team_names = [DEFAULT_TEAM_NAME] if DEFAULT_TEAM_NAME else ["wetschproblem"]

    _default_val = DEFAULT_TEAM_NAME if DEFAULT_TEAM_NAME in _team_names else _team_names[0]

    team_dropdown = mo.ui.dropdown(
        options=_team_names,
        value=_default_val,
        label="Team:"
    )
    return team_dropdown,


@app.cell
def _(DEFAULT_TEAM_NAME, mo, unique_teams):
    # Persistent Trade Finder Team & Focus UI controls
    _t_names = unique_teams if unique_teams else (["wetschproblem"] if not DEFAULT_TEAM_NAME else [DEFAULT_TEAM_NAME])
    _def_a = DEFAULT_TEAM_NAME if DEFAULT_TEAM_NAME in _t_names else _t_names[0]
    _other_teams = [t for t in _t_names if t != _def_a]
    _def_b = _other_teams[0] if _other_teams else _def_a

    trade_team_a_dropdown = mo.ui.dropdown(
        options=_t_names,
        value=_def_a,
        label="Team A:"
    )
    trade_team_b_dropdown = mo.ui.dropdown(
        options=_t_names,
        value=_def_b,
        label="Team B:"
    )
    trade_focus_dropdown = mo.ui.dropdown(
        options=["All Teams"] + _t_names,
        value="All Teams",
        label="Recommendations Focus:"
    )
    return trade_focus_dropdown, trade_team_a_dropdown, trade_team_b_dropdown


@app.cell
def _(
    calculate_player_trade_values,
    df_current_rosters,
    df_player_stats,
    mo,
    trade_team_a_dropdown,
    trade_team_b_dropdown,
):
    # Trade Calculator player selection options for Team A and Team B
    val_df_calc = (
        calculate_player_trade_values(df_current_rosters, df_player_stats)
        if df_current_rosters is not None and not df_current_rosters.empty
        else None
    )

    opts_a = {}
    if val_df_calc is not None and not val_df_calc.empty and trade_team_a_dropdown.value:
        t_a_p = val_df_calc[val_df_calc["team_name"] == trade_team_a_dropdown.value].sort_values(
            by="score", ascending=False
        )
        for _, r in t_a_p.iterrows():
            lbl = str(r["player_name"])
            if lbl in opts_a:
                lbl = f"{lbl} ({r['position']})"
            opts_a[lbl] = str(r["player_id"])

    opts_b = {}
    if val_df_calc is not None and not val_df_calc.empty and trade_team_b_dropdown.value:
        t_b_p = val_df_calc[val_df_calc["team_name"] == trade_team_b_dropdown.value].sort_values(
            by="score", ascending=False
        )
        for _, r in t_b_p.iterrows():
            lbl = str(r["player_name"])
            if lbl in opts_b:
                lbl = f"{lbl} ({r['position']})"
            opts_b[lbl] = str(r["player_id"])

    trade_pids_a_select = mo.ui.multiselect(
        options=opts_a,
        value=[],
        label="Select Players from Team A:"
    )

    trade_pids_b_select = mo.ui.multiselect(
        options=opts_b,
        value=[],
        label="Select Players from Team B:"
    )
    return trade_pids_a_select, trade_pids_b_select, val_df_calc


@app.cell
def _(mo, unique_teams):
    # Persistent Player Stats filter controls
    _t_names = unique_teams if unique_teams else []
    player_mode_radio = mo.ui.radio(
        options=["👤 Single Player", "⚔️ Compare Players"],
        value="👤 Single Player",
        inline=True,
        label="Mode:"
    )
    player_pos_radio = mo.ui.radio(
        options=["ALL", "QB", "RB", "WR", "TE", "K", "DEF"],
        value="ALL",
        inline=True,
        label="Position:"
    )
    player_owner_dropdown = mo.ui.dropdown(
        options=["Rostered Only", "ALL", "Free Agents"] + _t_names,
        value="Rostered Only",
        label="Owner:"
    )
    player_search_input = mo.ui.text(
        value="",
        placeholder="Filter by name (e.g. Allen)...",
        label="Search:"
    )
    return (
        player_mode_radio,
        player_owner_dropdown,
        player_pos_radio,
        player_search_input,
    )


@app.cell
def _(
    df_current_rosters,
    df_player_stats,
    get_player_selection_options,
    mo,
    player_owner_dropdown,
    player_pos_radio,
    player_search_input,
):
    # Compute available player options based on position, ownership, and search query
    _opts = get_player_selection_options(
        df_player_stats=df_player_stats,
        df_rosters=df_current_rosters,
        pos_filter=player_pos_radio.value if player_pos_radio is not None else "ALL",
        owner_filter=player_owner_dropdown.value if player_owner_dropdown is not None else "Rostered Only",
        search_query=player_search_input.value if player_search_input is not None else "",
    )
    _keys = list(_opts.keys())
    _def_p1 = _keys[0] if _keys else None
    _def_p2 = _keys[1] if len(_keys) > 1 else _def_p1

    player_1_dropdown = mo.ui.dropdown(
        options=_opts,
        value=_def_p1,
        label="Player 1:"
    )
    player_2_dropdown = mo.ui.dropdown(
        options=_opts,
        value=_def_p2,
        label="Player 2 (Compare):"
    )
    return player_1_dropdown, player_2_dropdown


@app.cell
def _(mo, unique_teams):
    # Controls for dedicated Player Market & Value page
    _t_names = unique_teams if unique_teams else []
    market_pos_dropdown = mo.ui.dropdown(
        options=["ALL", "QB", "RB", "WR", "TE", "K", "DEF"],
        value="ALL",
        label="Position:"
    )
    market_team_dropdown = mo.ui.dropdown(
        options=["ALL"] + _t_names,
        value="ALL",
        label="Team:"
    )
    market_search_input = mo.ui.text(
        value="",
        placeholder="Filter by player...",
        label="Search:"
    )
    return market_pos_dropdown, market_search_input, market_team_dropdown


@app.cell
def _(mo, unique_teams):
    # Persistent Controls for Roster Moves Revisitor / Grader
    _t_names = unique_teams if unique_teams else []
    moves_team_dropdown = mo.ui.dropdown(
        options=["All Teams"] + _t_names,
        value="All Teams",
        label="Team:"
    )
    moves_type_dropdown = mo.ui.dropdown(
        options=["All Types", "Add & Drop", "Free Add / IR Fill", "Pure Drop", "Trades"],
        value="All Types",
        label="Move Type:"
    )
    moves_sort_dropdown = mo.ui.dropdown(
        options={
            "🕒 Newest First": "newest",
            "🌟 Best Move (Net PPG)": "best",
            "💔 Worst Move (Net PPG)": "worst",
            "💎 Trade Value Delta": "net_tv",
            "📊 Cumulative Net FPTS": "net_total"
        },
        value="🕒 Newest First",
        label="Sort By:"
    )
    return moves_sort_dropdown, moves_team_dropdown, moves_type_dropdown


@app.cell
def _(
    limit_slider,
    market_pos_dropdown,
    market_search_input,
    market_team_dropdown,
    min_pts_slider,
    mo,
    moves_sort_dropdown,
    moves_team_dropdown,
    moves_type_dropdown,
    nav_tabs,
    opt_injury_switch,
    opt_mode_switch,
    opt_week_dropdown,
    player_1_dropdown,
    player_2_dropdown,
    player_mode_radio,
    player_owner_dropdown,
    player_pos_radio,
    player_search_input,
    pos_select,
    team_dropdown,
    trade_focus_dropdown,
):
    # Filter bar renderer: displays active tab controls without re-instantiating them
    if nav_tabs.value == "📊 Position Scatter":
        _filter_bar = mo.hstack([pos_select, min_pts_slider, limit_slider], justify="start", align="center", gap=2)
    elif nav_tabs.value == "👤 Player Stats":
        if player_mode_radio is not None and player_mode_radio.value == "⚔️ Compare Players":
            _filter_bar = mo.vstack([
                mo.hstack([player_mode_radio, player_pos_radio, player_owner_dropdown, player_search_input], justify="start", align="center", gap=1.5, wrap=True),
                mo.hstack([player_1_dropdown, player_2_dropdown], justify="start", align="center", gap=2, wrap=True)
            ], gap=0.8)
        else:
            _filter_bar = mo.vstack([
                mo.hstack([player_mode_radio, player_pos_radio, player_owner_dropdown, player_search_input], justify="start", align="center", gap=1.5, wrap=True),
                mo.hstack([player_1_dropdown], justify="start", align="center", gap=2, wrap=True)
            ], gap=0.8)
    elif nav_tabs.value == "🛡️ Team Analytics":
        _filter_bar = mo.hstack([team_dropdown], justify="start", align="center", gap=2)
    elif nav_tabs.value == "🤝 Trade Finder":
        _filter_bar = mo.hstack([trade_focus_dropdown], justify="start", align="center", gap=2)
    elif nav_tabs.value == "💎 Player Market":
        _filter_bar = mo.hstack([market_pos_dropdown, market_team_dropdown, market_search_input], justify="start", align="center", gap=2)
    elif nav_tabs.value == "📜 Roster Moves":
        _filter_bar = mo.hstack([moves_team_dropdown, moves_type_dropdown, moves_sort_dropdown], justify="start", align="center", gap=2)
    elif nav_tabs.value == "⚡ Team Optimizer":
        _divider1 = mo.md("<span style='color:#cbd5e1; font-size:1.1rem; margin:0 4px;'>|</span>")
        _divider2 = mo.md("<span style='color:#cbd5e1; font-size:1.1rem; margin:0 4px;'>|</span>")
        _divider3 = mo.md("<span style='color:#cbd5e1; font-size:1.1rem; margin:0 4px;'>|</span>")
        _label_mode1 = mo.md("<span style='font-size:0.83rem; font-weight:600; color:#334155; white-space:nowrap;'>🎯 Matchup / Actual</span>")
        _label_mode2 = mo.md("<span style='font-size:0.83rem; font-weight:600; color:#334155; white-space:nowrap;'>📈 Season PPG</span>")

        _filter_bar = mo.hstack([
            team_dropdown,
            _divider1,
            opt_week_dropdown,
            _divider2,
            _label_mode1,
            opt_mode_switch,
            _label_mode2,
            _divider3,
            opt_injury_switch
        ], justify="start", align="center", gap=0.7)
    else:
        _filter_bar = None

    _filter_bar if _filter_bar is not None else mo.md("")
    return


@app.cell
def _(
    DB_PATH,
    DEFAULT_LEAGUE_ID,
    VERSION,
    analyze_team_needs_and_surplus,
    get_roster_move_analytics,
    render_roster_moves_html,
    moves_sort_dropdown,
    moves_team_dropdown,
    moves_type_dropdown,
    build_interactive_position_chart,
    df_current_rosters,
    df_matchups,
    df_nfl_stats,
    df_player_stats,
    df_team_matchups,
    df_teams,
    format_last_sync,
    generate_trade_recommendations,
    get_current_nfl_week,
    get_last_sync_time,
    get_league_overview_analytics,
    get_luck_and_all_play_analytics,
    get_player_comparison_analytics,
    get_player_detailed_analytics,
    get_team_roster_analytics,
    limit_slider,
    market_pos_dropdown,
    market_search_input,
    market_team_dropdown,
    min_pts_slider,
    mo,
    nav_tabs,
    np,
    opt_injury_switch,
    opt_mode_switch,
    opt_week_dropdown,
    optimize_team_lineup,
    owner_colors,
    player_1_dropdown,
    player_2_dropdown,
    player_mode_radio,
    pos_select,
    refresh_btn,
    render_optimizer_view,
    render_player_comparison_view,
    render_player_market_view,
    render_player_profile_view,
    render_trade_finder_view,
    simulate_custom_trade,
    team_dropdown,
    trade_focus_dropdown,
    trade_pids_a_select,
    trade_pids_b_select,
    trade_team_a_dropdown,
    trade_team_b_dropdown,
    unique_teams,
    val_df_calc,
):
    _ = refresh_btn.value

    # Retrieve last data fetch timestamp
    _last_dt = get_last_sync_time(DB_PATH)
    _last_fetch_str = format_last_sync(_last_dt)
    _last_fetch_title = (
        f"Schedule: Every 30 min (:00 & :30) | Last DB sync: {_last_dt.strftime('%Y-%m-%d %H:%M:%S')}"
        if _last_dt else "Schedule: Every 30 min (:00 & :30)"
    )

    # Fixed Floating Bottom-Right Corner Badge with Version & Last Fetch
    _fixed_corner_badge = mo.Html(
        f"""<div style="position: fixed; bottom: 14px; right: 16px; z-index: 9999; display: flex; align-items: center; gap: 8px; background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(10px); border: 1px solid #e2e8f0; border-radius: 20px; padding: 6px 14px; box-shadow: 0 4px 16px rgba(0,0,0,0.08); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 0.76rem; color: #475569;"><span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 8px rgba(34, 197, 94, 0.7);"></span><span style="font-weight: 700; color: #0f172a;">v{VERSION}</span><span style="color: #cbd5e1;">•</span><span style="color: #64748b; font-size: 0.72rem; cursor: help;" title="{_last_fetch_title}">Last data fetch: {_last_fetch_str}</span></div>"""
    )

    if nav_tabs.value == "📊 Position Scatter":
        _pos_code = pos_select.value if pos_select is not None else "QB"
        _min_pts = min_pts_slider.value if min_pts_slider is not None else 3
        _top_limit = limit_slider.value if limit_slider is not None else 20

        _filtered_pos = df_player_stats[
            (df_player_stats['position'] == _pos_code) &
            (df_player_stats['mean_points'] >= _min_pts)
        ].sort_values(by='mean_points', ascending=False).head(_top_limit).copy()

        if _filtered_pos.empty:
            _content = mo.md("No players match the current criteria.")
        else:
            _content = build_interactive_position_chart(
                pos_data=_filtered_pos,
                unique_teams=unique_teams,
                owner_colors=owner_colors,
                chart_width=880,
                chart_height=520
            )

        _view = mo.vstack([_content, _fixed_corner_badge], gap=1)

    elif nav_tabs.value == "🤝 Trade Finder":
        _focus_t = None if (trade_focus_dropdown is None or trade_focus_dropdown.value == "All Teams") else trade_focus_dropdown.value
        _analysis = analyze_team_needs_and_surplus(df_teams, df_current_rosters, df_player_stats)
        _recs = generate_trade_recommendations(df_teams, df_current_rosters, df_player_stats, focus_team=_focus_t)

        _calc_res = None
        if (
            trade_team_a_dropdown is not None
            and trade_team_b_dropdown is not None
            and trade_pids_a_select is not None
            and trade_pids_b_select is not None
            and (bool(trade_pids_a_select.value) or bool(trade_pids_b_select.value))
        ):
            _calc_res = simulate_custom_trade(
                team_a_name=trade_team_a_dropdown.value,
                team_b_name=trade_team_b_dropdown.value,
                team_a_pids=trade_pids_a_select.value,
                team_b_pids=trade_pids_b_select.value,
                df_teams=df_teams,
                df_rosters=df_current_rosters,
                df_player_stats=df_player_stats
            )

        _trade_view = render_trade_finder_view(
            analysis=_analysis,
            recommendations=_recs,
            calc_result=_calc_res,
            calc_team_a_control=trade_team_a_dropdown,
            calc_team_b_control=trade_team_b_dropdown,
            calc_pids_a_control=trade_pids_a_select,
            calc_pids_b_control=trade_pids_b_select,
            owner_colors=owner_colors,
            mo=mo
        )
        _view = mo.vstack([_trade_view, _fixed_corner_badge], gap=1)

    elif nav_tabs.value == "💎 Player Market":
        _market_view = render_player_market_view(
            val_df=val_df_calc,
            unique_teams=unique_teams,
            owner_colors=owner_colors,
            pos_filter=market_pos_dropdown.value if market_pos_dropdown is not None else "ALL",
            team_filter=market_team_dropdown.value if market_team_dropdown is not None else "ALL",
            search_query=market_search_input.value if market_search_input is not None else "",
            mo=mo
        )
        _view = mo.vstack([_market_view, _fixed_corner_badge], gap=1)

    elif nav_tabs.value == "👤 Player Stats":
        _p1_id = player_1_dropdown.value if player_1_dropdown is not None else None
        _p2_id = player_2_dropdown.value if player_2_dropdown is not None else None
        _is_comp = (player_mode_radio is not None and player_mode_radio.value == "⚔️ Compare Players")

        if _is_comp:
            if not _p1_id or not _p2_id:
                _content = mo.md("Please select two players above to run head-to-head comparison.")
            else:
                _comp_data = get_player_comparison_analytics(
                    player_a_id=_p1_id,
                    player_b_id=_p2_id,
                    df_player_stats=df_player_stats,
                    df_nfl_stats=df_nfl_stats,
                    df_matchups=df_matchups,
                    df_rosters=df_current_rosters,
                    val_df=val_df_calc,
                    db_path=DB_PATH
                )
                _content = render_player_comparison_view(_comp_data, owner_colors=owner_colors, mo=mo)
        else:
            if not _p1_id:
                _content = mo.md("Please select a player above to inspect detailed analytics.")
            else:
                _p_data = get_player_detailed_analytics(
                    player_id=_p1_id,
                    df_player_stats=df_player_stats,
                    df_nfl_stats=df_nfl_stats,
                    df_matchups=df_matchups,
                    df_rosters=df_current_rosters,
                    val_df=val_df_calc,
                    db_path=DB_PATH
                )
                _content = render_player_profile_view(_p_data, owner_colors=owner_colors, mo=mo)

        _view = mo.vstack([_content, _fixed_corner_badge], gap=1)

    elif nav_tabs.value == "🛡️ Team Analytics":
        if team_dropdown is None or not team_dropdown.value:
            _view = mo.md("Please select a team.")
        else:
            _selected_team = team_dropdown.value
            _active_wk = opt_week_dropdown.value if (opt_week_dropdown is not None and opt_week_dropdown.value is not None) else None
            _t = get_team_roster_analytics(_selected_team, df_current_rosters, df_player_stats, df_teams, val_df=val_df_calc, week=_active_wk)

            if not _t:
                _view = mo.md(f"No roster data available for {_selected_team}.")
            else:
                # Sleek Unified KPI Box
                _pos_pills = []
                _pos_colors = {
                    'QB': '#f43f5e',
                    'RB': '#06b6d4',
                    'WR': '#3b82f6',
                    'TE': '#f59e0b',
                    'K': '#a855f7',
                    'DEF': '#64748b'
                }
                for _p in ['QB', 'RB', 'WR', 'TE', 'DEF', 'K']:
                    _val = _t['pos_breakdown'].get(_p, 0.0)
                    _p_col = _pos_colors.get(_p, '#64748b')
                    _pos_pills.append(
                        f"""<div style="display:flex; align-items:center; gap:6px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:4px 10px;"><span style="font-weight:700; font-size:0.75rem; color:{_p_col};">{_p}</span><span style="font-weight:600; font-size:0.82rem; color:#1e293b;">{_val:.1f} <span style="font-size:0.7rem; color:#94a3b8; font-weight:normal;">PPG</span></span></div>"""
                    )

                _ir_cnt = int((_t['bench_df']['slot'] == 'IR').sum()) if 'slot' in _t['bench_df'].columns else 0
                _bye_cnt = int((_t['bench_df']['slot'] == 'BYE').sum()) if 'slot' in _t['bench_df'].columns else 0
                _pure_bn = len(_t['bench_df']) - _ir_cnt - _bye_cnt
                _b_parts = []
                if _pure_bn > 0:
                    _b_parts.append(f"{_pure_bn} BN")
                if _bye_cnt > 0:
                    _b_parts.append(f"{_bye_cnt} BYE")
                if _ir_cnt > 0:
                    _b_parts.append(f"{_ir_cnt} IR")
                _bench_count_desc = " + ".join(_b_parts) if _b_parts else f"{len(_t['bench_df'])} Bench Options"

                _kpi_box = mo.Html(
                    f"""<div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; padding:18px 22px; margin-bottom:18px; box-shadow:0 1px 4px rgba(0,0,0,0.03); font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"><div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap:16px; padding-bottom:16px; border-bottom:1px solid #f1f5f9;"><div><div style="font-size:0.76rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Team Record</div><div style="font-size:1.45rem; font-weight:800; color:#0f172a; margin:2px 0;">{_t['wins']} - {_t['losses']}</div><div style="font-size:0.74rem; color:#94a3b8;">Total: {_t['total_fpts']:.1f} FPTS</div></div><div><div style="font-size:0.76rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Starting PPG</div><div style="font-size:1.45rem; font-weight:800; color:#0f172a; margin:2px 0;">{_t['starter_ppg']:.1f} <span style="font-size:0.85rem; font-weight:600; color:#64748b;">FPTS</span></div><div style="font-size:0.74rem; color:#94a3b8;">Avg Starter Output / Wk</div></div><div><div style="font-size:0.76rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Bench Depth</div><div style="font-size:1.45rem; font-weight:800; color:#0f172a; margin:2px 0;">{_t['bench_ppg']:.1f} <span style="font-size:0.85rem; font-weight:600; color:#64748b;">FPTS</span></div><div style="font-size:0.74rem; color:#94a3b8;">{_bench_count_desc}</div></div><div><div style="font-size:0.76rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Roster TV</div><div style="font-size:1.45rem; font-weight:800; color:#7c3aed; margin:2px 0;">{_t['total_roster_tv']:.1f} <span style="font-size:0.85rem; font-weight:600; color:#64748b;">TV</span></div><div style="font-size:0.74rem; color:#94a3b8;">Starters: {_t['starter_tv']:.1f} • Bench: {_t['bench_tv']:.1f}</div></div><div><div style="font-size:0.76rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Avg Pos Rank</div><div style="font-size:1.45rem; font-weight:800; color:#0f172a; margin:2px 0;">#{_t['avg_pos_rank_starters']:.1f} <span style="font-size:0.85rem; font-weight:600; color:#64748b;">Starters</span></div><div style="font-size:0.74rem; color:#94a3b8;">Bench: #{_t['avg_pos_rank_bench']:.1f} • All: #{_t['avg_pos_rank_total']:.1f}</div></div><div><div style="font-size:0.76rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">⭐ Top 10 Assets</div><div style="font-size:1.45rem; font-weight:800; color:#0f172a; margin:2px 0;">{_t['top_10_count']} <span style="font-size:0.85rem; font-weight:600; color:#64748b;">Players</span></div><div style="font-size:0.74rem; color:#94a3b8;">Top-10 at their position</div></div><div><div style="font-size:0.76rem; font-weight:600; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Roster Health</div><div style="font-size:1.45rem; font-weight:800; color:#0f172a; margin:2px 0;">{len(_t['all_roster_df']) - _t['injured_count']} <span style="font-size:0.95rem; font-weight:500; color:#94a3b8;">/ {len(_t['all_roster_df'])}</span></div><div style="font-size:0.74rem; color:#16a34a; font-weight:500;">{_t['injured_count']} Questionable / Out</div></div></div><div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:14px;"><div style="font-size:0.74rem; font-weight:700; color:#64748b; text-transform:uppercase; margin-right:4px;">Starter Breakdown:</div>{''.join(_pos_pills)}</div></div>"""
                )

                # Lineup table generator with pin-point badges
                def _build_roster_html(df_sub, title, is_starters=True):
                    _rows = []
                    for _, _r in df_sub.iterrows():
                        _inj = str(_r.get('injury_status', 'Healthy') or 'Healthy')
                        if _inj == 'Healthy':
                            _inj_html = "<span style='display:inline-flex; align-items:center; gap:4px; color:#16a34a; font-weight:600; font-size:0.75rem;'><span style='width:6px; height:6px; border-radius:50%; background:#22c55e;'></span>Active</span>"
                        elif _inj in ['Questionable', 'Probable']:
                            _inj_html = f"<span style='background:#fef3c7; border:1px solid #fde68a; color:#b45309; border-radius:6px; padding:2px 7px; font-weight:700; font-size:0.72rem;'>{_inj}</span>"
                        else:
                            _inj_html = f"<span style='background:#fee2e2; border:1px solid #fca5a5; color:#991b1b; border-radius:6px; padding:2px 7px; font-weight:700; font-size:0.72rem;'>{_inj}</span>"

                        _rk_val = _r.get('pos_rank')
                        if pd.notna(_rk_val) and int(_rk_val) <= 5:
                            _rank_html = f"<span style='background:#fef3c7; border:1px solid #fde68a; color:#b45309; border-radius:6px; padding:2px 8px; font-weight:800; font-size:0.75rem;'>#{int(_rk_val)} Elite</span>"
                        elif pd.notna(_rk_val) and int(_rk_val) <= 12:
                            _rank_html = f"<span style='background:#eff6ff; border:1px solid #bfdbfe; color:#1d4ed8; border-radius:6px; padding:2px 8px; font-weight:700; font-size:0.75rem;'>#{int(_rk_val)} Starter</span>"
                        elif pd.notna(_rk_val) and int(_rk_val) < 99:
                            _rank_html = f"<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#475569; border-radius:6px; padding:2px 8px; font-weight:600; font-size:0.75rem;'>#{int(_rk_val)}</span>"
                        else:
                            _rank_html = "<span style='color:#94a3b8; font-size:0.75rem;'>—</span>"

                        _tier_val = _r.get('consistency_tier')
                        _tier = str(_tier_val) if pd.notna(_tier_val) and _tier_val is not None else ""
                        if "Low" in _tier or "Rock Solid" in _tier:
                            _tier_html = "<span style='display:inline-flex; align-items:center; gap:4px; background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:6px; padding:2px 8px; font-weight:700; font-size:0.74rem;'><span style='width:6px; height:6px; border-radius:50%; background:#22c55e;'></span>Low Variance</span>"
                        elif "Moderate" in _tier:
                            _tier_html = "<span style='display:inline-flex; align-items:center; gap:4px; background:#fefce8; border:1px solid #fef08a; color:#854d0e; border-radius:6px; padding:2px 8px; font-weight:600; font-size:0.74rem;'><span style='width:6px; height:6px; border-radius:50%; background:#eab308;'></span>Moderate</span>"
                        elif "High" in _tier or "Boom" in _tier:
                            _tier_html = "<span style='display:inline-flex; align-items:center; gap:4px; background:#fef2f2; border:1px solid #fecaca; color:#991b1b; border-radius:6px; padding:2px 8px; font-weight:700; font-size:0.74rem;'><span style='width:6px; height:6px; border-radius:50%; background:#ef4444;'></span>High Variance</span>"
                        else:
                            _tier_html = "<span style='color:#94a3b8; font-size:0.75rem;'>—</span>"

                        _slot_label = str(_r.get('slot', 'BN'))
                        _pos_slot_colors = {
                            'QB': '#f43f5e',
                            'RB': '#06b6d4',
                            'WR': '#3b82f6',
                            'TE': '#f59e0b',
                            'FLEX': 'linear-gradient(135deg, #06b6d4 0%, #3b82f6 50%, #f59e0b 100%)',
                            'K': '#a855f7',
                            'DEF': '#64748b',
                            'BN': '#64748b',
                            'BYE': '#7c3aed',
                            'IR': '#ef4444'
                        }
                        if is_starters:
                            _slot_bg = _pos_slot_colors.get(_slot_label, _pos_slot_colors.get(_r.get('position', ''), '#2563eb'))
                        elif _slot_label == 'IR':
                            _slot_bg = '#ef4444'
                        elif _slot_label == 'BYE':
                            _slot_bg = '#7c3aed'
                        else:
                            _slot_bg = '#64748b'

                        _tv = float(_r.get('trade_value', 0.0)) if pd.notna(_r.get('trade_value')) else 0.0
                        _mean_pts = float(_r.get('mean_points', 0.0)) if pd.notna(_r.get('mean_points')) else 0.0
                        _std_pts = float(_r.get('std_points', 0.0)) if pd.notna(_r.get('std_points')) else 0.0
                        _gp = int(_r.get('games_played', 0)) if pd.notna(_r.get('games_played')) else 0
                        _pname = str(_r.get('player_name', 'Unknown'))
                        _pos = str(_r.get('position', 'WR'))
                        _nfl_team = str(_r.get('nfl_team', ''))
                        _headshot = str(_r.get('headshot_url', ''))

                        _row_html = f"""<tr style='border-bottom: 1px solid #f1f5f9; height: 50px;'><td style='padding: 8px 10px; width: 65px;'><span style='background:{_slot_bg}; color:#ffffff; font-weight:700; font-size:0.75rem; border-radius:6px; padding:3px 8px; display:inline-block; text-align:center; min-width:44px;'>{_slot_label}</span></td><td style='padding: 8px 6px; width: 44px;'><img src='{_headshot}' style='width:36px; height:36px; border-radius:50%; object-fit:cover; background:#e2e8f0; border:1px solid #cbd5e1;' onerror="this.src='https://sleepercdn.com/images/v2/icons/player_default.webp'"/></td><td style='padding: 8px 12px;'><div style='font-weight:700; font-size:0.88rem; color:#0f172a;'>{_pname}</div><div style='font-size:0.74rem; color:#64748b;'>{_pos} • {_nfl_team}</div></td><td style='padding: 8px 12px; text-align:center;'>{_rank_html}</td><td style='padding: 8px 12px; text-align:right; font-weight:800; font-size:0.88rem; color:#7c3aed;'>{_tv:.1f}</td><td style='padding: 8px 12px; text-align:right; font-weight:700; font-size:0.9rem; color:#0f172a;'>{_mean_pts:.2f}</td><td style='padding: 8px 12px; text-align:right; font-size:0.84rem; color:#475569;'>±{_std_pts:.1f}</td><td style='padding: 8px 12px; text-align:center;'>{_tier_html}</td><td style='padding: 8px 12px; text-align:center;'>{_inj_html}</td><td style='padding: 8px 12px; text-align:center; font-size:0.82rem; color:#64748b;'>{_gp}</td></tr>"""
                        _rows.append(_row_html)

                    _ir_cnt = int((df_sub['slot'] == 'IR').sum()) if 'slot' in df_sub.columns else 0
                    _bye_cnt = int((df_sub['slot'] == 'BYE').sum()) if 'slot' in df_sub.columns else 0
                    if not is_starters and (_ir_cnt > 0 or _bye_cnt > 0):
                        _pure_bn = len(df_sub) - _ir_cnt - _bye_cnt
                        _c_parts = []
                        if _pure_bn > 0:
                            _c_parts.append(f"{_pure_bn} BN")
                        if _bye_cnt > 0:
                            _c_parts.append(f"{_bye_cnt} BYE")
                        if _ir_cnt > 0:
                            _c_parts.append(f"{_ir_cnt} IR")
                        _joined_c_parts = " + ".join(_c_parts)
                        _count_str = f"{len(df_sub)} Players ({_joined_c_parts})"
                    else:
                        _count_str = f"{len(df_sub)} Players"

                    return f"""<div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-bottom:18px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'><div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'><span>{title}</span><span style='font-size:0.75rem; color:#64748b; font-weight:500;'>{_count_str}</span></div><div style='overflow-x:auto;'><table style='width:100%; border-collapse:collapse; font-size:0.84rem;'><thead><tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px;'><th style='padding:10px 10px; text-align:left; width:65px;'>Slot</th><th style='padding:10px 6px; width:44px;'></th><th style='padding:10px 12px; text-align:left;'>Player</th><th style='padding:10px 12px; text-align:center; width:110px;'>Pos Rank</th><th style='padding:10px 12px; text-align:right; width:80px;'>TV</th><th style='padding:10px 12px; text-align:right; width:90px;'>PPG</th><th style='padding:10px 12px; text-align:right; width:75px;'>Std Dev</th><th style='padding:10px 12px; text-align:center; width:125px;'>Variance</th><th style='padding:10px 12px; text-align:center; width:100px;'>Status</th><th style='padding:10px 12px; text-align:center; width:65px;'>GP</th></tr></thead><tbody>{"".join(_rows)}</tbody></table></div></div>"""

                _starters_html = _build_roster_html(_t['starters_df'], "⚡ Starting Lineup", is_starters=True)
                _bench_html = _build_roster_html(_t['bench_df'], "🪵 Bench Depth", is_starters=False)

                _view = mo.vstack([
                    _kpi_box,
                    mo.Html(_starters_html),
                    mo.Html(_bench_html),
                    _fixed_corner_badge
                ], gap=0)

    elif nav_tabs.value == "⚡ Team Optimizer":
        if team_dropdown is None or not team_dropdown.value:
            _view = mo.md("Please select a team.")
        else:
            _selected_team = team_dropdown.value
            _active_wk = get_current_nfl_week()
            _target_wk = opt_week_dropdown.value if (opt_week_dropdown is not None and opt_week_dropdown.value is not None) else _active_wk

            if opt_mode_switch is not None and opt_mode_switch.value:
                _mode = "ppg"
            elif _target_wk < _active_wk:
                _mode = "retro"
            else:
                _mode = "projection"

            _ignore_inj = opt_injury_switch.value if opt_injury_switch is not None else True

            _opt_res = optimize_team_lineup(
                team_name=_selected_team,
                mode=_mode,
                selected_week=_target_wk,
                ignore_injured=_ignore_inj,
                df_teams=df_teams,
                df_rosters=df_current_rosters,
                df_matchups=df_matchups,
                df_player_stats=df_player_stats,
                season="2026",
                league_id=DEFAULT_LEAGUE_ID,
                db_path=DB_PATH
            )
            _content = render_optimizer_view(_opt_res, mo)
            _view = mo.vstack([_content, _fixed_corner_badge], gap=1)

    elif nav_tabs.value == "🍀 Luck & All-Play":
        _luck_an = get_luck_and_all_play_analytics(df_teams, df_team_matchups)

        if not _luck_an:
            _view = mo.Html(
                """<div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:24px; text-align:center; color:#64748b; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;'><div style='font-size:2rem; margin-bottom:8px;'>🍀</div><div style='font-size:1.1rem; font-weight:700; color:#0f172a; margin-bottom:4px;'>No Matchup Data Available Yet</div><div style='font-size:0.85rem;'>Once completed match weeks are recorded, All-Play standings, Luck Index, and weekly score breakdown will appear here.</div></div>"""
            )
        else:
            _df_ap = _luck_an['all_play_df']
            _comp_weeks = _luck_an['completed_weeks']
            _medians = _luck_an['weekly_medians']

            # Top KPI Summary Grid (English)
            _kpi_luck = mo.Html(
                f"""<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap:12px; width:100%; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#15803d; text-transform:uppercase;">🍀 Luckiest Team</div><div style="font-size:1.3rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_luck_an['luckiest_team']['team_name']}</div><div style="font-size:0.78rem; color:#15803d; font-weight:700;">+{_luck_an['luckiest_team']['luck_diff']:.2f} Wins Above Expected</div><div style="font-size:0.72rem; color:#94a3b8; margin-top:2px;">Actual: {_luck_an['luckiest_team']['actual_record']} • Expected: {_luck_an['luckiest_team']['expected_wins']:.2f} xW</div></div><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#b91c1c; text-transform:uppercase;">💔 Toughest Schedule</div><div style="font-size:1.3rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_luck_an['unluckiest_team']['team_name']}</div><div style="font-size:0.78rem; color:#b91c1c; font-weight:700;">{_luck_an['unluckiest_team']['luck_diff']:.2f} Wins Below Expected</div><div style="font-size:0.72rem; color:#94a3b8; margin-top:2px;">Actual: {_luck_an['unluckiest_team']['actual_record']} • Expected: {_luck_an['unluckiest_team']['expected_wins']:.2f} xW</div></div><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#b45309; text-transform:uppercase;">👑 True All-Play Leader</div><div style="font-size:1.3rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_luck_an['ap_leader']['team_name']}</div><div style="font-size:0.78rem; color:#b45309; font-weight:700;">{_luck_an['ap_leader']['ap_record']} ({_luck_an['ap_leader']['ap_win_pct']*100:.1f}% Win Rate)</div><div style="font-size:0.72rem; color:#94a3b8; margin-top:2px;">Would have defeated most opponents every week</div></div><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#2563eb; text-transform:uppercase;">🎯 Median Dominator</div><div style="font-size:1.3rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_luck_an['median_leader']['team_name']}</div><div style="font-size:0.78rem; color:#2563eb; font-weight:700;">{_luck_an['median_leader']['median_record']} vs Weekly Median</div><div style="font-size:0.72rem; color:#94a3b8; margin-top:2px;">Avg {_luck_an['median_leader']['avg_score']:.1f} FPTS per week</div></div></div>"""
            )

            # All-Play Standings Table (English)
            _ap_rows = []
            for _, _r_ap in _df_ap.iterrows():
                _rank = _r_ap['ap_rank']
                if _rank == 1:
                    _rank_badge = "<span style='background:#fef3c7; color:#b45309; border:1px solid #fde68a; border-radius:50%; width:26px; height:26px; display:inline-flex; align-items:center; justify-content:center; font-weight:800; font-size:0.78rem;'>🥇</span>"
                elif _rank == 2:
                    _rank_badge = "<span style='background:#f1f5f9; color:#475569; border:1px solid #cbd5e1; border-radius:50%; width:26px; height:26px; display:inline-flex; align-items:center; justify-content:center; font-weight:800; font-size:0.78rem;'>🥈</span>"
                elif _rank == 3:
                    _rank_badge = "<span style='background:#ffedd5; color:#c2410c; border:1px solid #fed7aa; border-radius:50%; width:26px; height:26px; display:inline-flex; align-items:center; justify-content:center; font-weight:800; font-size:0.78rem;'>🥉</span>"
                else:
                    _rank_badge = f"<span style='color:#94a3b8; font-weight:700; font-size:0.85rem;'>#{_rank}</span>"

                _diff = _r_ap['rank_diff']
                if _diff > 0:
                    _diff_html = f"<span style='color:#16a34a; font-weight:700; font-size:0.76rem;' title='All-Play rank is {_diff} spot(s) HIGHER than official standings!'>+{_diff} ▲</span>"
                elif _diff < 0:
                    _diff_html = f"<span style='color:#dc2626; font-weight:700; font-size:0.76rem;' title='All-Play rank is {abs(_diff)} spot(s) LOWER than official standings'>{_diff} ▼</span>"
                else:
                    _diff_html = "<span style='color:#94a3b8; font-size:0.76rem;' title='All-Play rank matches official standings'>=</span>"

                _luck = _r_ap['luck_diff']
                if _luck > 0.2:
                    _luck_badge = f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:8px; padding:3px 10px; font-weight:700; font-size:0.82rem;' title='Favorable schedule: +{_luck:.2f} wins above statistical expectation'>+{_luck:.2f} 🍀</span>"
                elif _luck < -0.2:
                    _luck_badge = f"<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; border-radius:8px; padding:3px 10px; font-weight:700; font-size:0.82rem;' title='Unfavorable schedule: {_luck:.2f} wins below statistical expectation'>{_luck:.2f} 💔</span>"
                else:
                    _luck_badge = f"<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#475569; border-radius:8px; padding:3px 10px; font-weight:600; font-size:0.82rem;' title='Neutral schedule: In line with expected performance'>{_luck:+.2f} ⚖️</span>"

                _t_dot = f"<span style='display:inline-block; width:10px; height:10px; border-radius:50%; background-color:{owner_colors.get(_r_ap['team_name'], '#3b82f6')};'></span>"

                _ap_rows.append(
                    f"""<tr style='border-bottom:1px solid #f1f5f9; height:46px;'><td style='padding:8px 6px; text-align:center; width:44px;'>{_rank_badge}</td><td style='padding:8px 6px; text-align:center; width:44px;'>{_diff_html}</td><td style='padding:8px 4px 8px 8px; width:20px;'>{_t_dot}</td><td style='padding:8px 12px 8px 4px; text-align:left;'><div style='font-weight:700; color:#0f172a; font-size:0.88rem;'>{_r_ap['team_name']}</div><div style='font-size:0.72rem; color:#64748b;'>{_r_ap['owner_name']}</div></td><td style='padding:8px 12px; text-align:center; font-weight:700; color:#0f172a;'>{_r_ap['actual_record']} <span style='font-size:0.72rem; font-weight:500; color:#94a3b8;'>({_r_ap['actual_win_pct']:.3f})</span></td><td style='padding:8px 12px; text-align:center; font-weight:800; color:#2563eb;'>{_r_ap['ap_record']} <span style='font-size:0.72rem; font-weight:600; color:#60a5fa;'>({_r_ap['ap_win_pct']:.3f})</span></td><td style='padding:8px 12px; text-align:center; font-weight:700; color:#334155;'>{_r_ap['expected_wins']:.2f}</td><td style='padding:8px 12px; text-align:center;'>{_luck_badge}</td><td style='padding:8px 12px; text-align:center; font-weight:600; color:#475569;'>{_r_ap['median_record']}</td><td style='padding:8px 12px; text-align:right; font-weight:700; color:#0f172a;'>{_r_ap['avg_score']:.1f}</td><td style='padding:8px 12px; text-align:center; font-size:0.8rem; color:#64748b;'>{_r_ap['min_score']:.1f} – {_r_ap['max_score']:.1f}</td><td style='padding:8px 12px; text-align:center; font-size:0.8rem; color:#64748b;'>±{_r_ap['std_score']:.1f}</td></tr>"""
                )

            _ap_table = mo.Html(
                f"""<div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:14px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'><div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'><span>🍀 All-Play Standings & Luck Index (Weeks {min(_comp_weeks)}–{max(_comp_weeks)})</span><span style='font-size:0.75rem; color:#64748b; font-weight:500;'>Expected Wins = All-Play Win % × Games Played</span></div><div style='overflow-x:auto;'><table style='width:100%; border-collapse:collapse; font-size:0.84rem;'><thead><tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.5px;'><th style='padding:10px 6px; text-align:center; width:44px;'>AP</th><th style='padding:10px 6px; text-align:center; width:44px;'>Shift</th><th style='padding:10px 4px 10px 8px; width:20px;'></th><th style='padding:10px 12px 10px 4px; text-align:left;'>Team / Manager</th><th style='padding:10px 12px; text-align:center; width:110px;'>Actual Record</th><th style='padding:10px 12px; text-align:center; width:125px;'>All-Play Record</th><th style='padding:10px 12px; text-align:center; width:95px;' title='Statistically expected wins based on all-play performance'>Exp. Wins (xW)</th><th style='padding:10px 12px; text-align:center; width:125px;' title='Difference of Actual Wins - Expected Wins'>Luck Index (ΔW)</th><th style='padding:10px 12px; text-align:center; width:100px;' title='Record against the weekly league median'>vs Median</th><th style='padding:10px 12px; text-align:right; width:90px;'>Avg Score</th><th style='padding:10px 12px; text-align:center; width:120px;'>Range (Min–Max)</th><th style='padding:10px 12px; text-align:center; width:95px;' title='Standard deviation of weekly scores (volatility)'>Volatility (SD)</th></tr></thead><tbody>{''.join(_ap_rows)}</tbody></table></div></div>"""
            )

            # Weekly Matrix Breakdown Table (Simplified, decluttered build)
            _wk_headers = "".join([f"<th style='padding:10px 12px; text-align:center; min-width:135px;'>Week {w}</th>" for w in _comp_weeks])
            _matrix_rows = []

            for _, _r_mat in _df_ap.iterrows():
                _t_dot = f"<span style='display:inline-block; width:10px; height:10px; border-radius:50%; background-color:{owner_colors.get(_r_mat['team_name'], '#3b82f6')};'></span>"
                _wk_cells = []

                for _w in _comp_weeks:
                    _w_res = _r_mat['weekly_results'].get(_w, {})
                    _pts = _w_res.get('points', 0.0)
                    _rk = _w_res.get('rank_in_week', 0)
                    _res = _w_res.get('result', '-')
                    _opp = _w_res.get('opp_name', 'Unknown')
                    _opp_pts = _w_res.get('opp_pts', 0.0)
                    _margin = _w_res.get('margin', 0.0)

                    if _res == 'W':
                        _res_text = 'Won'
                        _res_color = '#16a34a'
                        _cell_bg = 'rgba(22, 163, 74, 0.09)'
                    elif _res == 'L':
                        _res_text = 'Lost'
                        _res_color = '#dc2626'
                        _cell_bg = 'rgba(220, 38, 38, 0.08)'
                    else:
                        _res_text = 'Tied'
                        _res_color = '#64748b'
                        _cell_bg = 'transparent'

                    _crown_html = (
                        "<span style='font-size:0.8rem; margin-left:3px;' title='Weekly High Scorer (#1)'>👑</span>"
                        if _rk == 1 else ""
                    )

                    _tooltip = f"Week {_w}: {_pts:.1f} FPTS (Rank #{_rk} in league) • {_res_text} vs {_opp} ({_opp_pts:.1f} FPTS) by {_margin:+.1f} pts"

                    _cell_content = f"""<div style='display:flex; flex-direction:column; align-items:center; gap:2px;' title='{_tooltip}'><div style='display:flex; align-items:center;'><span style='font-weight:750; color:#0f172a; font-size:0.92rem; letter-spacing:-0.2px;'>{_pts:.1f}</span>{_crown_html}</div><div style='display:flex; align-items:center; gap:4px; font-size:0.73rem;'><span style='font-weight:800; color:{_res_color};'>{_res}</span><span style='color:#64748b; font-weight:500; max-width:85px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;' title='vs {_opp} ({_opp_pts:.1f} pts)'>vs {_opp}</span><span style='color:#94a3b8; font-size:0.7rem;'>({_margin:+.1f})</span></div></div>"""
                    _wk_cells.append(f"<td style='padding:8px 8px; text-align:center; vertical-align:middle; background:{_cell_bg}; border-left:1px solid #f8fafc; border-right:1px solid #f8fafc;'>{_cell_content}</td>")

                _luck = _r_mat['luck_diff']
                if _luck > 0.2:
                    _mat_luck_badge = f"<span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:6px; padding:2px 8px; font-weight:700; font-size:0.78rem;'>+{_luck:.2f} 🍀</span>"
                elif _luck < -0.2:
                    _mat_luck_badge = f"<span style='background:#fef2f2; border:1px solid #fecaca; color:#b91c1c; border-radius:6px; padding:2px 8px; font-weight:700; font-size:0.78rem;'>{_luck:.2f} 💔</span>"
                else:
                    _mat_luck_badge = f"<span style='background:#f8fafc; border:1px solid #e2e8f0; color:#475569; border-radius:6px; padding:2px 8px; font-weight:600; font-size:0.78rem;'>{_luck:+.2f} ⚖️</span>"

                _matrix_rows.append(
                    f"""<tr style='border-bottom:1px solid #f1f5f9; height:52px;'><td style='padding:8px 6px; text-align:center; font-weight:700; color:#94a3b8; font-size:0.82rem; width:44px;'>#{_r_mat['ap_rank']}</td><td style='padding:8px 4px 8px 8px; width:20px;'>{_t_dot}</td><td style='padding:8px 12px 8px 4px; text-align:left; min-width:140px;'><div style='font-weight:700; color:#0f172a; font-size:0.86rem;'>{_r_mat['team_name']}</div><div style='font-size:0.72rem; color:#64748b;'>{_r_mat['owner_name']}</div></td>{''.join(_wk_cells)}<td style='padding:8px 12px; text-align:center; font-weight:750; color:#0f172a; font-size:0.86rem;'>{_r_mat['actual_record']}</td><td style='padding:8px 12px; text-align:right; font-weight:800; color:#0f172a; font-size:0.88rem;'>{_r_mat['avg_score']:.1f}</td><td style='padding:8px 12px; text-align:center;'>{_mat_luck_badge}</td></tr>"""
                )

            # Weekly League Median Row
            _med_cells = "".join([f"<td style='padding:9px 8px; text-align:center; font-weight:750; color:#2563eb; font-size:0.86rem;'>{_medians[w]:.1f}</td>" for w in _comp_weeks])
            _median_row = f"""<tr style='background:#f8fafc; font-weight:700; border-top:2px solid #e2e8f0; height:44px;'><td colspan='3' style='padding:9px 14px; text-align:left; color:#475569; font-size:0.76rem; text-transform:uppercase; letter-spacing:0.5px;'>🎯 League Median</td>{_med_cells}<td style='padding:9px 12px; text-align:center; color:#94a3b8; font-size:0.76rem;'>—</td><td style='padding:9px 12px; text-align:right; color:#2563eb; font-weight:800; font-size:0.86rem;'>{float(np.mean(list(_medians.values()))):.1f}</td><td style='padding:9px 12px; text-align:center; color:#94a3b8; font-size:0.75rem;'>—</td></tr>"""

            _weekly_matrix_table = mo.Html(
                f"""<div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:14px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'><div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;'><span>📅 Weekly Matchup & Score Matrix</span><span style='font-size:0.75rem; color:#64748b; font-weight:500;'>Weekly scores, matchups & margins</span></div><div style='overflow-x:auto;'><table style='width:100%; border-collapse:collapse; font-size:0.84rem;'><thead><tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.5px;'><th style='padding:10px 8px; text-align:center; width:44px;'>AP</th><th style='padding:10px 4px 10px 8px; width:20px;'></th><th style='padding:10px 12px 10px 4px; text-align:left; min-width:140px;'>Team / Manager</th>{_wk_headers}<th style='padding:10px 12px; text-align:center; width:80px;'>Record</th><th style='padding:10px 12px; text-align:right; width:90px;'>Avg Score</th><th style='padding:10px 12px; text-align:center; width:100px;'>Luck Index</th></tr></thead><tbody>{''.join(_matrix_rows)}{_median_row}</tbody></table></div></div>"""
            )

            _methodology_box = mo.Html(
                """<div style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:14px 18px; margin-top:14px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size:0.82rem; color:#475569; line-height:1.5;'><div style='font-weight:700; color:#0f172a; margin-bottom:6px; display:flex; align-items:center; gap:6px;'><span>💡 How All-Play & Schedule Luck Work</span></div><div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap:12px; margin-top:8px;'><div><strong style='color:#0f172a;'>All-Play Record:</strong> Simulates what would have occurred if each team had played against <em>all</em> other 5 league managers every single week (5 matchups per week). This completely eliminates head-to-head schedule luck.</div><div><strong style='color:#0f172a;'>Expected Wins (xW):</strong> Calculated as <code>All-Play Win % × Weeks Played</code>. Represents how many wins a team deserved based solely on points scored.</div><div><strong style='color:#0f172a;'>Luck Index (Δ Wins):</strong> <code>Actual Wins - Expected Wins</code>. A positive value (🍀) indicates favorable matchups (facing lower-scoring opponents). A negative value (💔) reveals tough schedule breaks (taking losses despite high scoring).</div></div></div>"""
            )

            _view = mo.vstack([
                _kpi_luck,
                _ap_table,
                _weekly_matrix_table,
                _methodology_box,
                _fixed_corner_badge
            ], gap=1)

    elif nav_tabs.value == "📜 Roster Moves":
        _moves_data = get_roster_move_analytics(
            db_path=DB_PATH,
            league_id=DEFAULT_LEAGUE_ID,
            team_filter=moves_team_dropdown.value if moves_team_dropdown is not None else None,
            type_filter=moves_type_dropdown.value if moves_type_dropdown is not None else None,
            sort_by=moves_sort_dropdown.value if moves_sort_dropdown is not None else "newest"
        )
        _moves_html = render_roster_moves_html(_moves_data, owner_colors=owner_colors)
        _view = mo.vstack([mo.Html(_moves_html), _fixed_corner_badge], gap=1)

    else:
        # League Overview Page
        _league_an = get_league_overview_analytics(df_teams, df_current_rosters, df_player_stats)

        if not _league_an:
            _view = mo.md("No league data available.")
        else:
            _standings = _league_an['standings_df']

            # Responsive HTML Grid for League KPI Cards (Works on mobile & desktop)
            _league_kpi_grid = mo.Html(
                f"""<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; width:100%; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;"><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;">👑 1st Place Leader</div><div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_league_an['leader_team']['team_name']}</div><div style="font-size:0.75rem; color:#94a3b8;">{_league_an['leader_team']['wins']}-{_league_an['leader_team']['losses']} • {_league_an['leader_team']['pf']:.1f} PF</div></div><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;">⚡ League Avg Starters</div><div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_league_an['avg_starter_ppg']:.1f} <span style="font-size:0.85rem; font-weight:600; color:#64748b;">FPTS</span></div><div style="font-size:0.75rem; color:#94a3b8;">Avg Weekly Team Score</div></div><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;">🔥 Top Scoring Offense</div><div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_league_an['high_pf_team']['team_name']}</div><div style="font-size:0.75rem; color:#94a3b8;">{_league_an['high_pf_team']['pf']:.1f} Points For</div></div><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;">🧱 Toughest Schedule</div><div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_league_an['tough_sched_team']['team_name']}</div><div style="font-size:0.75rem; color:#94a3b8;">{_league_an['tough_sched_team']['pa']:.1f} Points Against</div></div><div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,0.02);"><div style="font-size:0.75rem; font-weight:600; color:#64748b; text-transform:uppercase;">🪵 Deepest Bench</div><div style="font-size:1.35rem; font-weight:800; color:#0f172a; margin:4px 0 2px 0;">{_league_an['deepest_bench_team']['team_name']}</div><div style="font-size:0.75rem; color:#94a3b8;">{_league_an['deepest_bench_team']['bench_ppg']:.1f} Bench PPG</div></div></div>"""
            )

            # Map total roster trade value per team
            _team_tv_map = {}
            if val_df_calc is not None and not val_df_calc.empty:
                _team_tv_map = val_df_calc.groupby("team_name")["trade_value"].sum().to_dict()

            # Build Standings Table Rows with matching column alignments
            _standings_rows = []
            for _, _r_st in _standings.iterrows():
                _t_name = _r_st['team_name']
                _rank = _r_st['rank']
                if _rank == 1:
                    _rank_html = "<span style='background:#fef3c7; color:#b45309; border:1px solid #fde68a; border-radius:50%; width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; font-weight:800; font-size:0.8rem;'>🥇</span>"
                elif _rank == 2:
                    _rank_html = "<span style='background:#f1f5f9; color:#475569; border:1px solid #cbd5e1; border-radius:50%; width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; font-weight:800; font-size:0.8rem;'>🥈</span>"
                elif _rank == 3:
                    _rank_html = "<span style='background:#ffedd5; color:#c2410c; border:1px solid #fed7aa; border-radius:50%; width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; font-weight:800; font-size:0.8rem;'>🥉</span>"
                else:
                    _rank_html = f"<span style='color:#94a3b8; font-weight:700; font-size:0.85rem;'>#{_rank}</span>"

                _diff_val = _r_st['diff']
                if _diff_val > 0:
                    _diff_html = f"<span style='color:#16a34a; font-weight:700;'>+{_diff_val:.1f}</span>"
                elif _diff_val < 0:
                    _diff_html = f"<span style='color:#dc2626; font-weight:700;'>{_diff_val:.1f}</span>"
                else:
                    _diff_html = "<span style='color:#64748b;'>0.0</span>"

                _owner_col = owner_colors.get(_t_name, '#94a3b8')

                # CSS Micro-Dot Pinpoint Health Indicator (consistent with Consistency / Status dots)
                _healthy = _r_st['healthy_count']
                _total = _r_st['total_roster_count']
                _starter_inj = _r_st['starter_injured_count']
                _starters_needed = _r_st['starters_total']
                _st_details = _r_st.get('starter_inj_details', '')
                _bn_details = _r_st.get('bench_inj_details', '')

                if _healthy < _starters_needed:
                    _tooltip = f"CRITICAL SHORTAGE: Only {_healthy} healthy players available ({_starters_needed} starters needed)!"
                    _dot_color = "#991b1b"
                    _text_color = "#991b1b"
                    _extra_style = "background:#fee2e2; border:1px solid #fca5a5; padding:2px 8px; border-radius:12px;"
                elif _starter_inj > 0:
                    _tooltip = f"Starter Injured: {_st_details}"
                    _dot_color = "#ef4444"
                    _text_color = "#dc2626"
                    _extra_style = ""
                elif _healthy < _total:
                    _tooltip = f"Bench Injured: {_bn_details}"
                    _dot_color = "#f59e0b"
                    _text_color = "#b45309"
                    _extra_style = ""
                else:
                    _tooltip = "100% Healthy: Full roster fit and active"
                    _dot_color = "#22c55e"
                    _text_color = "#16a34a"
                    _extra_style = ""

                _health_html = f"""<span title="{_tooltip}" style="display:inline-flex; align-items:center; justify-content:center; gap:6px; color:{_text_color}; font-weight:600; font-size:0.8rem; white-space:nowrap; cursor:help; {_extra_style}"><span style="width:7px; height:7px; min-width:7px; min-height:7px; border-radius:50%; background:{_dot_color}; display:inline-block;"></span><span>{_healthy} / {_total}</span></span>"""

                _row_html = f"""<tr style='border-bottom: 1px solid #f1f5f9;'><td style='padding:10px 12px; text-align:center; width:52px;'>{_rank_html}</td><td style='padding:10px 4px 10px 10px; width:24px; min-width:24px; max-width:24px; text-align:center;'><div style='width:10px; height:10px; min-width:10px; min-height:10px; aspect-ratio:1/1; border-radius:50%; background:{_owner_col}; margin:0 auto;'></div></td><td style='padding:10px 14px 10px 4px; text-align:left;'><div style='font-weight:700; font-size:0.88rem; color:#0f172a;'>{_t_name}</div><div style='font-size:0.75rem; color:#64748b;'>{_r_st['owner_name']}</div></td><td style='padding:10px 14px; text-align:center; width:110px;'><span style='font-weight:800; font-size:0.9rem; color:#0f172a;'>{_r_st['wins']} - {_r_st['losses']}</span><div style='font-size:0.72rem; color:#64748b;'>{_r_st['win_pct']:.3f}</div></td><td style='padding:10px 14px; text-align:right; font-weight:700; font-size:0.88rem; color:#0f172a; width:100px;'>{_r_st['pf']:.2f}</td><td style='padding:10px 14px; text-align:right; font-size:0.86rem; color:#64748b; width:100px;'>{_r_st['pa']:.2f}</td><td style='padding:10px 14px; text-align:right; font-size:0.86rem; width:80px;'>{_diff_html}</td><td style='padding:10px 14px; text-align:right; font-weight:600; color:#1e293b; width:90px;'>{_r_st['starter_ppg']:.1f}</td><td style='padding:10px 14px; text-align:right; color:#64748b; width:85px;'>{_r_st['bench_ppg']:.1f}</td><td style='padding:10px 14px; text-align:center; width:95px;'><span style='background:#eff6ff; border:1px solid #bfdbfe; color:#1d4ed8; border-radius:6px; padding:3px 9px; font-weight:700; font-size:0.82rem;' title='Avg Positional Rank of all Starters (excluding IR) | Full Team Avg: #{_r_st['avg_pos_rank_total']:.1f}'>#{_r_st['avg_pos_rank_starters']:.1f}</span></td><td style='padding:10px 14px; text-align:center; width:95px;'><span style='background:#f8fafc; border:1px solid #e2e8f0; color:#475569; border-radius:6px; padding:3px 9px; font-weight:600; font-size:0.82rem;' title='Avg Positional Rank of all Bench Players (excluding IR) | Full Team Avg: #{_r_st['avg_pos_rank_total']:.1f}'>#{_r_st['avg_pos_rank_bench']:.1f}</span></td><td style='padding:10px 14px; text-align:center; width:95px;'><span style='background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:3px 10px; font-weight:700; font-size:0.82rem; color:#0f172a;'>⭐ {_r_st['top_10_count']}</span></td><td style='padding:10px 14px; text-align:right; font-weight:700; font-size:0.88rem; color:#7c3aed; width:95px;'>{_team_tv_map.get(_t_name, 0.0):.1f}</td><td style='padding:10px 14px; text-align:center; width:85px;'>{_health_html}</td><td style='padding:10px 14px; text-align:center; width:95px;'><span style='background:#f0fdf4; border:1px solid #bbf7d0; color:#15803d; border-radius:8px; padding:3px 10px; font-weight:800; font-size:0.82rem;'>{_r_st['power_score']:.1f}</span></td></tr>"""
                _standings_rows.append(_row_html)

            _standings_table = mo.Html(
                f"""<div style='background:#ffffff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; margin-top:14px; font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; box-shadow:0 1px 4px rgba(0,0,0,0.03);'><div style='background:#f8fafc; padding:12px 18px; font-weight:700; font-size:0.92rem; color:#0f172a; border-bottom:1px solid #e2e8f0;'>🏆 League Standings & Power Rankings</div><div style='overflow-x:auto;'><table style='width:100%; border-collapse:collapse; font-size:0.84rem;'><thead><tr style='background:#fafbfc; border-bottom:1px solid #e2e8f0; color:#64748b; font-size:0.75rem; text-transform:uppercase; letter-spacing:0.5px;'><th style='padding:10px 12px; text-align:center; width:52px;'>Rank</th><th style='padding:10px 4px 10px 10px; width:24px; min-width:24px; max-width:24px;'></th><th style='padding:10px 14px 10px 4px; text-align:left;'>Team / Manager</th><th style='padding:10px 14px; text-align:center; width:110px;'>Record (Win %)</th><th style='padding:10px 14px; text-align:right; width:100px;'>Points For (PF)</th><th style='padding:10px 14px; text-align:right; width:100px;'>Points Against (PA)</th><th style='padding:10px 14px; text-align:right; width:80px;'>Diff (+/-)</th><th style='padding:10px 14px; text-align:right; width:90px;'>Starter PPG</th><th style='padding:10px 14px; text-align:right; width:85px;'>Bench PPG</th><th style='padding:10px 14px; text-align:center; width:95px;'>Avg Starter Rank</th><th style='padding:10px 14px; text-align:center; width:95px;'>Avg Bench Rank</th><th style='padding:10px 14px; text-align:center; width:95px;'>Top 10 Assets</th><th style='padding:10px 14px; text-align:right; width:95px;'>Roster TV</th><th style='padding:10px 14px; text-align:center; width:85px;'>Health</th><th style='padding:10px 14px; text-align:center; width:95px;'>Power Index</th></tr></thead><tbody>{"".join(_standings_rows)}</tbody></table></div></div>"""
            )

            _view = mo.vstack([
                _league_kpi_grid,
                _standings_table,
                _fixed_corner_badge
            ], gap=1)

    _view
    return


if __name__ == "__main__":
    app.run()
