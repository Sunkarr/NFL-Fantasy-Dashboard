from typing import Dict, List, Optional
import altair as alt
import pandas as pd
from src.config import TEAM_PALETTE, FREE_AGENT_COLOR, NFL_TEAM_COLORS

# Configure Altair data transformer to inline CSV to prevent virtual file cache misses / 404 KeyErrors in marimo
try:
    from marimo._plugins.ui._impl.charts.altair_transformer import register_transformers
    register_transformers()
    alt.data_transformers.enable('marimo_inline_csv')
except Exception:
    try:
        alt.data_transformers.enable('default')
    except Exception:
        pass


def get_owner_color_map(unique_teams: List[str]) -> Dict[str, str]:
    """Map team names to distinct colors with Free Agent as neutral slate."""
    owner_colors = {'Free Agent': FREE_AGENT_COLOR}
    for i, team in enumerate(unique_teams):
        owner_colors[team] = TEAM_PALETTE[i % len(TEAM_PALETTE)]
    return owner_colors


def _abbreviate_name(full_name: str) -> str:
    """Turn 'Patrick Mahomes' into 'P. Mahomes'."""
    if not full_name:
        return ""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0]}. {' '.join(parts[1:])}"
    return full_name


def build_interactive_position_chart(
    pos_data: pd.DataFrame,
    unique_teams: List[str],
    owner_colors: Dict[str, str],
    chart_width: int = 860,
    chart_height: int = 480
) -> alt.Chart:
    """
    Build a crisp, high-performance Altair scatter plot with:
    - Smart anti-overlap label positioning
    - Full hover tooltips
    - High-contrast owner color scheme & top legend
    - Median reference dashed lines
    """
    if pos_data.empty:
        return alt.Chart(pd.DataFrame()).mark_text()

    df_plot = pos_data.copy().sort_values(by=['mean_points', 'std_points'], ascending=[True, True]).reset_index(drop=True)
    owner_counts = df_plot['current_owner'].value_counts()
    df_plot['owner_legend_label'] = df_plot['current_owner'].apply(lambda o: f"{o} ({owner_counts.get(o, 0)})")
    df_plot['short_name'] = df_plot['player_name'].apply(_abbreviate_name)

    # Axis Domain Bounds with padding
    x_min = float(df_plot['mean_points'].min())
    x_max = float(df_plot['mean_points'].max())
    y_min = float(df_plot['std_points'].min())
    y_max = float(df_plot['std_points'].max())

    x_margin = max(2.5, (x_max - x_min) * 0.14)
    y_margin = max(1.8, (y_max - y_min) * 0.14)

    x_domain = [max(0.0, x_min - x_margin), x_max + x_margin + 2.5]
    y_domain = [max(0.0, y_min - y_margin), y_max + y_margin]

    x_med = float(df_plot['mean_points'].median())
    y_med = float(df_plot['std_points'].median())

    # Legend order and palette mapping
    ordered_owners = sorted([o for o in df_plot['current_owner'].unique() if o != 'Free Agent'] if 'current_owner' in df_plot.columns else [])
    if 'current_owner' in df_plot.columns and 'Free Agent' in df_plot['current_owner'].values:
        ordered_owners.append('Free Agent')

    domain_labels = [f"{o} ({owner_counts.get(o, 0)})" for o in ordered_owners]
    range_colors = [owner_colors.get(o, FREE_AGENT_COLOR) for o in ordered_owners]

    # Shared base chart
    base = alt.Chart(df_plot).encode(
        x=alt.X(
            'mean_points:Q',
            title='Mean Points (FPTS)',
            scale=alt.Scale(domain=x_domain),
            axis=alt.Axis(
                gridColor='#e2e8f0',
                titleFontWeight='bold',
                titleFontSize=12,
                labelFontSize=10.5,
                tickCount=10
            )
        ),
        y=alt.Y(
            'std_points:Q',
            title='Standard Deviation (SD)',
            scale=alt.Scale(domain=y_domain),
            axis=alt.Axis(
                gridColor='#e2e8f0',
                titleFontWeight='bold',
                titleFontSize=12,
                labelFontSize=10.5,
                tickCount=8
            )
        )
    )

    # 1. Median Reference Lines
    rule_x = alt.Chart(pd.DataFrame({'x': [x_med]})).mark_rule(
        strokeDash=[4, 4],
        color='#94a3b8',
        size=1.2,
        opacity=0.8
    ).encode(x=alt.X('x:Q', scale=alt.Scale(domain=x_domain)))

    rule_y = alt.Chart(pd.DataFrame({'y': [y_med]})).mark_rule(
        strokeDash=[4, 4],
        color='#94a3b8',
        size=1.2,
        opacity=0.8
    ).encode(y=alt.Y('y:Q', scale=alt.Scale(domain=y_domain)))

    # 2. Main Color Scatter Points with Owner Legend and Comprehensive Tooltip
    scatter_points = base.mark_circle(
        size=220,
        opacity=0.92,
        stroke='#ffffff',
        strokeWidth=1.5
    ).encode(
        color=alt.Color(
            'owner_legend_label:N',
            title='Fantasy Owner',
            scale=alt.Scale(domain=domain_labels, range=range_colors),
            legend=alt.Legend(
                titleFontSize=11.5,
                titleFontWeight='bold',
                labelFontSize=10.5,
                symbolSize=110,
                orient='top',
                columns=4,
                labelLimit=250
            )
        ),
        tooltip=[
            alt.Tooltip('player_name:N', title='Player'),
            alt.Tooltip('position:N', title='Position'),
            alt.Tooltip('nfl_team:N', title='NFL Team'),
            alt.Tooltip('current_owner:N', title='Fantasy Owner'),
            alt.Tooltip('injury_status:N', title='Injury Status'),
            alt.Tooltip('mean_points:Q', title='Mean FPTS', format='.2f'),
            alt.Tooltip('std_points:Q', title='Std Dev (SD)', format='.2f'),
            alt.Tooltip('cv:Q', title='Volatility (CV)', format='.2f'),
            alt.Tooltip('max_points:Q', title='Max FPTS', format='.2f'),
            alt.Tooltip('min_points:Q', title='Min FPTS', format='.2f'),
            alt.Tooltip('total_points:Q', title='Total FPTS', format='.2f'),
            alt.Tooltip('games_played:Q', title='Games Played')
        ]
    )

    # 3. Two-group Alternating Labels (Odd/Even index) for clean zero-collision offset
    df_plot['is_even'] = df_plot.index % 2 == 0
    df_even = df_plot[df_plot['is_even']].copy()
    df_odd = df_plot[~df_plot['is_even']].copy()

    labels_even = alt.Chart(df_even).mark_text(
        align='left',
        baseline='middle',
        dx=11,
        dy=-5,
        fontSize=10,
        fontWeight=600,
        color='#334155',
        opacity=0.95
    ).encode(
        x=alt.X('mean_points:Q', scale=alt.Scale(domain=x_domain)),
        y=alt.Y('std_points:Q', scale=alt.Scale(domain=y_domain)),
        text='short_name:N'
    )

    labels_odd = alt.Chart(df_odd).mark_text(
        align='left',
        baseline='middle',
        dx=11,
        dy=6,
        fontSize=10,
        fontWeight=600,
        color='#334155',
        opacity=0.95
    ).encode(
        x=alt.X('mean_points:Q', scale=alt.Scale(domain=x_domain)),
        y=alt.Y('std_points:Q', scale=alt.Scale(domain=y_domain)),
        text='short_name:N'
    )

    chart = (rule_x + rule_y + scatter_points + labels_even + labels_odd).properties(
        width=chart_width,
        height=chart_height
    ).configure_view(
        stroke='#cbd5e1'
    ).configure_axis(
        domainColor='#cbd5e1'
    )

    return chart


def build_market_value_scatter_chart(
    val_data: pd.DataFrame,
    unique_teams: List[str],
    owner_colors: Dict[str, str],
    chart_width: int = 860,
    chart_height: int = 480
) -> alt.Chart:
    """
    Build an Altair scatter plot mapping Mean FPTS (PPG) vs Market Trade Value (0 - 100 TV).
    """
    if val_data is None or val_data.empty:
        return alt.Chart(pd.DataFrame()).mark_text()

    df_plot = val_data.copy().sort_values(by=['score', 'trade_value'], ascending=[True, True]).reset_index(drop=True)
    owner_col = 'team_name' if 'team_name' in df_plot.columns else 'current_owner'
    df_plot['owner_clean'] = df_plot[owner_col].fillna('Free Agent')
    owner_counts = df_plot['owner_clean'].value_counts()
    df_plot['owner_legend_label'] = df_plot['owner_clean'].apply(lambda o: f"{o} ({owner_counts.get(o, 0)})")
    df_plot['short_name'] = df_plot['player_name'].apply(_abbreviate_name)

    # Axis Domain Bounds with generous padding
    x_min = float(df_plot['score'].min())
    x_max = float(df_plot['score'].max())
    y_min = float(df_plot['trade_value'].min())
    y_max = float(df_plot['trade_value'].max())

    x_margin = max(2.5, (x_max - x_min) * 0.12)
    y_margin = max(4.0, (y_max - y_min) * 0.12)

    x_domain = [max(0.0, x_min - x_margin), x_max + x_margin + 2.0]
    y_domain = [max(0.0, y_min - y_margin), y_max + y_margin]

    x_med = float(df_plot['score'].median())
    y_med = float(df_plot['trade_value'].median())

    ordered_owners = sorted([o for o in df_plot['owner_clean'].unique() if o != 'Free Agent'])
    if 'Free Agent' in df_plot['owner_clean'].values:
        ordered_owners.append('Free Agent')

    domain_labels = [f"{o} ({owner_counts.get(o, 0)})" for o in ordered_owners]
    range_colors = [owner_colors.get(o, FREE_AGENT_COLOR) for o in ordered_owners]

    base = alt.Chart(df_plot).encode(
        x=alt.X(
            'score:Q',
            title='Mean Points (FPTS / PPG)',
            scale=alt.Scale(domain=x_domain),
            axis=alt.Axis(
                gridColor='#e2e8f0',
                titleFontWeight='bold',
                titleFontSize=12,
                labelFontSize=10.5,
                tickCount=10
            )
        ),
        y=alt.Y(
            'trade_value:Q',
            title='Market Trade Value (0 - 100 TV)',
            scale=alt.Scale(domain=y_domain),
            axis=alt.Axis(
                gridColor='#e2e8f0',
                titleFontWeight='bold',
                titleFontSize=12,
                labelFontSize=10.5,
                tickCount=8
            )
        )
    )

    rule_x = alt.Chart(pd.DataFrame({'x': [x_med]})).mark_rule(
        strokeDash=[4, 4],
        color='#94a3b8',
        size=1.2,
        opacity=0.8
    ).encode(x=alt.X('x:Q', scale=alt.Scale(domain=x_domain)))

    rule_y = alt.Chart(pd.DataFrame({'y': [y_med]})).mark_rule(
        strokeDash=[4, 4],
        color='#94a3b8',
        size=1.2,
        opacity=0.8
    ).encode(y=alt.Y('y:Q', scale=alt.Scale(domain=y_domain)))

    scatter_points = base.mark_circle(
        size=220,
        opacity=0.92,
        stroke='#ffffff',
        strokeWidth=1.5
    ).encode(
        color=alt.Color(
            'owner_legend_label:N',
            title='Fantasy Owner',
            scale=alt.Scale(domain=domain_labels, range=range_colors),
            legend=alt.Legend(
                titleFontSize=11.5,
                titleFontWeight='bold',
                labelFontSize=10.5,
                symbolSize=110,
                orient='top',
                columns=4,
                labelLimit=250
            )
        ),
        tooltip=[
            alt.Tooltip('player_name:N', title='Player'),
            alt.Tooltip('position:N', title='Position'),
            alt.Tooltip('nfl_team:N', title='NFL Team'),
            alt.Tooltip('owner_clean:N', title='Fantasy Owner'),
            alt.Tooltip('injury_status:N', title='Injury Status'),
            alt.Tooltip('trade_value:Q', title='Trade Value (TV)', format='.1f'),
            alt.Tooltip('score:Q', title='Mean FPTS (PPG)', format='.2f'),
            alt.Tooltip('pos_percentile:Q', title='Pos Percentile', format='.0f'),
            alt.Tooltip('pos_rank:Q', title='Pos Rank'),
            alt.Tooltip('games_played:Q', title='Games Played')
        ]
    )

    df_plot['is_even'] = df_plot.index % 2 == 0
    df_even = df_plot[df_plot['is_even']].copy()
    df_odd = df_plot[~df_plot['is_even']].copy()

    labels_even = alt.Chart(df_even).mark_text(
        align='left', baseline='middle', dx=11, dy=-5, fontSize=10, fontWeight=600, color='#334155', opacity=0.95
    ).encode(
        x=alt.X('score:Q', scale=alt.Scale(domain=x_domain)),
        y=alt.Y('trade_value:Q', scale=alt.Scale(domain=y_domain)),
        text='short_name:N'
    )

    labels_odd = alt.Chart(df_odd).mark_text(
        align='left', baseline='middle', dx=11, dy=6, fontSize=10, fontWeight=600, color='#334155', opacity=0.95
    ).encode(
        x=alt.X('score:Q', scale=alt.Scale(domain=x_domain)),
        y=alt.Y('trade_value:Q', scale=alt.Scale(domain=y_domain)),
        text='short_name:N'
    )

    chart = (rule_x + rule_y + scatter_points + labels_even + labels_odd).properties(
        width=chart_width,
        height=chart_height
    ).configure_view(
        stroke='#cbd5e1'
    ).configure_axis(
        domainColor='#cbd5e1'
    )

    return chart


def build_player_weekly_bar_chart(
    weekly_df: pd.DataFrame,
    mean_points: float,
    player_name: str,
    position: str = "WR",
    chart_width: int = 860,
    chart_height: int = 300,
) -> alt.Chart:
    """
    Build an interactive weekly fantasy points bar chart with NFL team colors,
    historical 2025 game logs, current 2026 season highlight shading, and a dashed season average rule line.
    """
    if weekly_df is None or weekly_df.empty:
        return alt.Chart(pd.DataFrame()).mark_text()

    df_plot = weekly_df.copy()
    if 'season' not in df_plot.columns:
        df_plot['season'] = '2026'

    # Build clear chronological week labels (e.g. '25 W1, '26 W1)
    if 'week_label' not in df_plot.columns:
        df_plot['week_label'] = df_plot.apply(
            lambda r: f"'{str(r['season'])[-2:]} W{r['week']}" if str(r['season']) != '2026' else f"Week {r['week']}",
            axis=1
        )

    # Team colors per week: if player switched NFL teams, each week shows their respective team color
    if 'bar_color' not in df_plot.columns:
        df_plot['bar_color'] = df_plot['nfl_team'].apply(
            lambda t: NFL_TEAM_COLORS.get(str(t).upper(), '#00338D')
        )

    # Relative diff vs current season average
    df_plot['diff_vs_avg'] = (df_plot['points'] - mean_points).round(1)

    # Reverse chronological order: newest games first on the left (e.g. 2026 W4, W3, W2, W1, '25 W18..., '24 W1)
    # This ensures users immediately see the most recent games without needing to scroll right.
    df_plot['chrono_order'] = df_plot['season'].astype(int) * 100 + df_plot['week'].astype(int)
    df_plot = df_plot.sort_values(by='chrono_order', ascending=False).reset_index(drop=True)
    x_order = list(df_plot['week_label'])

    # Opacity: Current 2026 season stands out with 1.0 opacity; historical seasons are slightly dimmed (0.75)
    df_plot['opacity'] = df_plot['season'].apply(lambda s: 1.0 if str(s) == '2026' else 0.75)

    max_pts = float(df_plot['points'].max()) if not df_plot.empty else 20.0
    y_max = max(max_pts + 5.0, mean_points + 5.0, 15.0)

    n_bars = len(df_plot)
    bar_size = 22 if n_bars > 15 else (32 if n_bars > 8 else 42)

    base = alt.Chart(df_plot)

    tooltips = [
        alt.Tooltip('season:N', title='Season'),
        alt.Tooltip('week:Q', title='NFL Week'),
        alt.Tooltip('points:Q', title='Fantasy Points', format='.1f'),
        alt.Tooltip('nfl_team:N', title='NFL Team'),
        alt.Tooltip('diff_vs_avg:Q', title='vs 2026 Avg', format='+.1f'),
    ]
    for col, title in [
        ('fantasy_status', 'Fantasy Status'),
        ('pass_yd', 'Pass Yds'),
        ('pass_td', 'Pass TDs'),
        ('rush_yd', 'Rush Yds'),
        ('rush_td', 'Rush TDs'),
        ('rec', 'Receptions'),
        ('rec_yd', 'Rec Yds'),
        ('rec_td', 'Rec TDs')
    ]:
        if col in df_plot.columns:
            tooltips.append(alt.Tooltip(f'{col}:N' if col == 'fantasy_status' else f'{col}:Q', title=title))

    # Dynamic width: at least chart_width (min 920px) or expanded comfortably for multi-season history
    effective_width = max(chart_width, n_bars * 38)

    bars = base.mark_bar(
        size=bar_size
    ).encode(
        x=alt.X(
            'week_label:O',
            sort=x_order,
            title='Game Week (Newest First on Left ➔ Historical to Right)',
            axis=alt.Axis(
                labelAngle=-45 if n_bars > 10 else 0,
                labelFontSize=9.5 if n_bars > 12 else 11,
                titleFontSize=12,
                titleFontWeight='bold'
            )
        ),
        y=alt.Y(
            'points:Q',
            title='Fantasy Points (FPTS)',
            scale=alt.Scale(domain=[0, y_max]),
            axis=alt.Axis(gridColor='#e2e8f0', labelFontSize=11, titleFontSize=12, titleFontWeight='bold')
        ),
        color=alt.Color('bar_color:N', scale=None),
        opacity=alt.Opacity('opacity:Q', scale=None, legend=None),
        tooltip=tooltips
    )

    text = base.mark_text(
        dy=-8,
        fontSize=9.5 if n_bars > 12 else 11,
        fontWeight=700,
        color='#1e293b'
    ).encode(
        x=alt.X('week_label:O', sort=x_order),
        y=alt.Y('points:Q'),
        text=alt.Text('points:Q', format='.1f')
    )

    avg_df = pd.DataFrame({'avg': [mean_points]})
    rule = alt.Chart(avg_df).mark_rule(
        strokeDash=[5, 5],
        color='#ef4444',
        size=1.8,
        opacity=0.85
    ).encode(
        y='avg:Q',
        tooltip=[alt.Tooltip('avg:Q', title='2026 Season Average', format='.1f')]
    )

    # Clean layered chart: text label removed from inside the chart area (now displayed cleanly in header legend only)
    chart = alt.layer(bars, text, rule).properties(
        width=effective_width,
        height=chart_height
    ).configure_view(
        stroke='#e2e8f0'
    ).configure_axis(
        domainColor='#cbd5e1'
    )

    return chart


def build_player_comparison_chart(
    df_comp: pd.DataFrame,
    name_a: str,
    name_b: str,
    color_a: str = '#2563eb',
    color_b: str = '#059669',
    chart_width: int = 860,
    chart_height: int = 320,
) -> alt.Chart:
    """
    Build an interactive side-by-side grouped bar chart comparing two players week-by-week.
    """
    if df_comp is None or df_comp.empty:
        return alt.Chart(pd.DataFrame()).mark_text()

    df_plot = df_comp.copy()
    if 'week_label' not in df_plot.columns:
        df_plot['week_label'] = df_plot['week'].apply(lambda w: f"Week {w}")

    max_pts = float(df_plot['points'].max()) if not df_plot.empty else 20.0
    y_max = max(max_pts + 6.0, 15.0)

    base = alt.Chart(df_plot)

    bars = base.mark_bar(
        size=26
    ).encode(
        x=alt.X('week_label:O', title='NFL Game Week', axis=alt.Axis(labelAngle=0, labelFontSize=11, titleFontSize=12, titleFontWeight='bold')),
        y=alt.Y('points:Q', title='Fantasy Points (FPTS)', scale=alt.Scale(domain=[0, y_max]), axis=alt.Axis(gridColor='#e2e8f0', labelFontSize=11, titleFontSize=12, titleFontWeight='bold')),
        xOffset='player_name:N',
        color=alt.Color(
            'player_name:N',
            title='Player',
            scale=alt.Scale(domain=[name_a, name_b], range=[color_a, color_b]),
            legend=alt.Legend(
                titleFontSize=11.5,
                titleFontWeight='bold',
                labelFontSize=11,
                symbolSize=100,
                orient='top'
            )
        ),
        tooltip=[
            alt.Tooltip('player_name:N', title='Player'),
            alt.Tooltip('week_label:N', title='Week'),
            alt.Tooltip('points:Q', title='Points', format='.1f'),
            alt.Tooltip('position:N', title='Pos'),
            alt.Tooltip('nfl_team:N', title='NFL Team')
        ]
    )

    text = base.mark_text(
        dy=-8,
        fontSize=10,
        fontWeight=700
    ).encode(
        x=alt.X('week_label:O'),
        y=alt.Y('points:Q'),
        xOffset='player_name:N',
        text=alt.Text('points:Q', format='.1f'),
        color=alt.Color('player_name:N', scale=alt.Scale(domain=[name_a, name_b], range=[color_a, color_b]), legend=None)
    )

    chart = (bars + text).properties(
        width=chart_width,
        height=chart_height
    ).configure_view(
        stroke='#e2e8f0'
    ).configure_axis(
        domainColor='#cbd5e1'
    )

    return chart
