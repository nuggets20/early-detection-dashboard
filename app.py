import dash
from dash import dcc, html, dash_table, Input, Output, State, callback_context
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import psycopg2
import psycopg2.extras
from datetime import datetime
import os


# ─────────────────────────────────────────────
# DATABASE CONFIG — update these before running
# ─────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "ep-restless-recipe-ao7psmbg.c-2.ap-southeast-1.aws.neon.tech"),
    "port":     int(os.environ.get("DB_PORT", 5432)),
    "dbname":   os.environ.get("DB_NAME", "neondb"),
    "user":     os.environ.get("DB_USER", "neondb_owner"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "sslmode":  "require",
}

# ─────────────────────────────────────────────
# COLOUR PALETTE — terminal / quant finance
# ─────────────────────────────────────────────
C = {
    "bg":           "#0a0e1a",
    "surface":      "#111827",
    "surface2":     "#1a2235",
    "border":       "#1e2d45",
    "accent":       "#00d4ff",
    "accent2":      "#00ff88",
    "accent3":      "#ff6b35",
    "accent4":      "#ffd700",
    "text":         "#e2e8f0",
    "text_muted":   "#64748b",
    "highest":      "#ffd700",
    "high":         "#00ff88",
    "promoted":     "#00d4ff",
    "watch":        "#ff6b35",
    "standard":     "#64748b",
    "large":        "#00ff88",
    "mid":          "#00d4ff",
    "small":        "#ff6b35",
    "micro":        "#64748b",
}

PRIORITY_COLORS = {
    "Highest Priority": C["highest"],
    "High Priority":    C["high"],
    "Promoted":         C["promoted"],
    "Watch":            C["watch"],
    "Standard":         C["standard"],
}

TIER_COLORS = {
    "Large": C["large"],
    "Mid":   C["mid"],
    "Small": C["small"],
    "Micro": C["micro"],
}

# ─────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────
def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def query(sql, params=None):
    try:
        conn = get_connection()
        df = pd.read_sql(sql, conn, params=params)
        conn.close()
        return df
    except Exception as e:
        print(f"DB error: {e}")
        return pd.DataFrame()

def get_quarters():
    df = query("SELECT DISTINCT quarter FROM early_detection_signals ORDER BY quarter DESC")
    return df["quarter"].tolist() if not df.empty else []

def get_signals(quarter, priorities=None, tiers=None, entry_types=None,
                min_score=None, top_n=None):
    conditions = ["quarter = %(quarter)s"]
    params = {"quarter": quarter}

    if priorities:
        conditions.append("smart_money_priority = ANY(%(priorities)s)")
        params["priorities"] = priorities
    if tiers:
        conditions.append("market_cap_tier = ANY(%(tiers)s)")
        params["tiers"] = tiers
    if entry_types:
        conditions.append("entry_type = ANY(%(entry_types)s)")
        params["entry_types"] = entry_types
    if min_score is not None:
        conditions.append("final_score >= %(min_score)s")
        params["min_score"] = min_score

    where = " AND ".join(conditions)
    limit = f"LIMIT {top_n}" if top_n else ""

    sql = f"""
        SELECT
            quarter_rank,
            ticker,
            company_name,
            market_cap_tier,
            accumulation_tier,
            smart_money_priority,
            entry_type,
            ROUND(final_score::numeric, 1)          AS final_score,
            ROUND(accumulation_score::numeric, 1)   AS accumulation_score,
            tier1_buyer_count,
            ROUND(weighted_conviction::numeric, 1)  AS weighted_conviction,
            above_tier_average_flag,
            specialist_dominated_flag,
            stalled_flag,
            ROUND(pct_fund_growth_2q::numeric, 1)   AS pct_fund_growth_2q,
            cusip
        FROM early_detection_signals
        WHERE {where}
        ORDER BY quarter_rank ASC
        {limit}
    """
    return query(sql, params)

def get_priority_distribution(quarter):
    sql = """
        SELECT
            smart_money_priority,
            market_cap_tier,
            COUNT(*) AS count
        FROM early_detection_signals
        WHERE quarter = %(quarter)s
        GROUP BY smart_money_priority, market_cap_tier
        ORDER BY smart_money_priority, market_cap_tier
    """
    return query(sql, {"quarter": quarter})

def get_score_distribution(quarter):
    sql = """
        SELECT
            final_score,
            market_cap_tier,
            smart_money_priority
        FROM early_detection_signals
        WHERE quarter = %(quarter)s
        ORDER BY final_score DESC
    """
    return query(sql, {"quarter": quarter})

def get_quarterly_trend():
    sql = """
        SELECT
            quarter,
            smart_money_priority,
            COUNT(*) AS count,
            ROUND(AVG(final_score)::numeric, 1) AS avg_score
        FROM early_detection_signals
        GROUP BY quarter, smart_money_priority
        ORDER BY quarter ASC, smart_money_priority
    """
    return query(sql)

def get_tier_base_rates():
    sql = """
        SELECT DISTINCT
            quarter,
            market_cap_tier,
            ROUND(tier_ed_base_rate_pct::numeric, 2) AS base_rate,
            above_tier_average_flag
        FROM early_detection_signals
        ORDER BY quarter DESC, market_cap_tier
    """
    return query(sql)

def get_stock_detail(cusip, quarter):
    sql = """
        SELECT *
        FROM early_detection_signals
        WHERE cusip = %(cusip)s AND quarter = %(quarter)s
    """
    return query(sql, {"cusip": cusip, "quarter": quarter})

def get_stock_history(cusip):
    sql = """
        SELECT
            quarter,
            quarter_rank,
            ROUND(final_score::numeric, 1)          AS final_score,
            smart_money_priority,
            accumulation_tier,
            tier1_buyer_count,
            ROUND(weighted_conviction::numeric, 1)  AS weighted_conviction
        FROM early_detection_signals
        WHERE cusip = %(cusip)s
        ORDER BY quarter ASC
    """
    return query(sql, {"cusip": cusip})

def get_summary_stats(quarter):
    sql = """
        SELECT
            COUNT(*)                                                            AS total,
            COUNT(*) FILTER (WHERE quarter_rank <= 10)                          AS top_10,
            COUNT(*) FILTER (WHERE quarter_rank <= 50)                          AS top_50,
            COUNT(*) FILTER (WHERE smart_money_priority = 'Highest Priority')   AS highest,
            COUNT(*) FILTER (WHERE smart_money_priority = 'High Priority')      AS high,
            COUNT(*) FILTER (WHERE market_cap_tier IN ('Large','Mid')
                AND quarter_rank <= 50)                                         AS large_mid_top50,
            COUNT(*) FILTER (WHERE stalled_flag = true)                         AS stalled,
            COUNT(*) FILTER (WHERE above_tier_average_flag = true)              AS above_avg,
            ROUND(MAX(final_score)::numeric, 1)                                 AS max_score,
            ROUND(AVG(final_score)::numeric, 1)                                 AS avg_score
        FROM early_detection_signals
        WHERE quarter = %(quarter)s
    """
    df = query(sql, {"quarter": quarter})
    return df.iloc[0].to_dict() if not df.empty else {}

# ─────────────────────────────────────────────
# CHART BUILDERS
# ─────────────────────────────────────────────
CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="'JetBrains Mono', 'Courier New', monospace", color=C["text"], size=11),
    margin=dict(l=40, r=20, t=40, b=40),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor=C["border"]),
)

def chart_priority_bar(df_priority):
    if df_priority.empty:
        return go.Figure()

    priority_order = ["Highest Priority", "High Priority", "Promoted", "Watch", "Standard"]
    df = df_priority.groupby("smart_money_priority")["count"].sum().reset_index()
    df["smart_money_priority"] = pd.Categorical(df["smart_money_priority"],
                                                categories=priority_order, ordered=True)
    df = df.sort_values("smart_money_priority")

    colors = [PRIORITY_COLORS.get(p, C["standard"]) for p in df["smart_money_priority"]]

    fig = go.Figure(go.Bar(
        x=df["smart_money_priority"],
        y=df["count"],
        marker=dict(
            color=colors,
            line=dict(color="rgba(0,0,0,0.3)", width=1)
        ),
        text=df["count"],
        textposition="outside",
        textfont=dict(color=C["text"], size=11),
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Signals by Priority Class", font=dict(size=13, color=C["accent"])),
        xaxis=dict(showgrid=False, linecolor=C["border"]),
        yaxis=dict(showgrid=True, gridcolor=C["border"], linecolor=C["border"]),
        showlegend=False,
    )
    return fig

def chart_tier_donut(df_signals):
    if df_signals.empty:
        return go.Figure()

    counts = df_signals["market_cap_tier"].value_counts()
    tier_order = ["Large", "Mid", "Small", "Micro"]
    labels = [t for t in tier_order if t in counts.index]
    values = [counts[t] for t in labels]
    colors = [TIER_COLORS.get(t, C["text_muted"]) for t in labels]

    fig = go.Figure(go.Pie(
        labels=labels,
        values=values,
        hole=0.6,
        marker=dict(colors=colors, line=dict(color=C["bg"], width=2)),
        textinfo="label+percent",
        textfont=dict(size=11),
        hovertemplate="%{label}: %{value} stocks<extra></extra>",
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Market Cap Tier Mix", font=dict(size=13, color=C["accent"])),
        showlegend=False,
        annotations=[dict(
            text=f"<b>{sum(values)}</b><br>signals",
            x=0.5, y=0.5, font=dict(size=14, color=C["text"]),
            showarrow=False
        )]
    )
    return fig

def chart_score_histogram(df_scores):
    if df_scores.empty:
        return go.Figure()

    fig = go.Figure()
    for tier in ["Large", "Mid", "Small", "Micro"]:
        sub = df_scores[df_scores["market_cap_tier"] == tier]
        if sub.empty:
            continue
        fig.add_trace(go.Histogram(
            x=sub["final_score"],
            name=tier,
            marker_color=TIER_COLORS.get(tier, C["text_muted"]),
            opacity=0.7,
            nbinsx=20,
            hovertemplate=f"{tier}<br>Score: %{{x}}<br>Count: %{{y}}<extra></extra>",
        ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Score Distribution by Tier", font=dict(size=13, color=C["accent"])),
        barmode="overlay",
        xaxis=dict(title="Final Score", showgrid=False, linecolor=C["border"]),
        yaxis=dict(title="Count", showgrid=True, gridcolor=C["border"]),
    )
    return fig

def chart_quarterly_trend(df_trend):
    if df_trend.empty:
        return go.Figure()

    fig = go.Figure()
    for priority in ["Highest Priority", "High Priority", "Promoted"]:
        sub = df_trend[df_trend["smart_money_priority"] == priority]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["quarter"],
            y=sub["count"],
            mode="lines+markers",
            name=priority,
            line=dict(color=PRIORITY_COLORS.get(priority), width=2),
            marker=dict(size=7),
            hovertemplate=f"{priority}<br>%{{x}}: %{{y}} signals<extra></extra>",
        ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Signal Count Trend by Quarter", font=dict(size=13, color=C["accent"])),
        xaxis=dict(showgrid=False, linecolor=C["border"]),
        yaxis=dict(showgrid=True, gridcolor=C["border"]),
        hovermode="x unified",
    )
    return fig

def chart_base_rate_heatmap(df_rates):
    if df_rates.empty:
        return go.Figure()

    pivot = df_rates.pivot_table(
        index="market_cap_tier", columns="quarter",
        values="base_rate", aggfunc="mean"
    )
    tier_order = ["Large", "Mid", "Small", "Micro"]
    pivot = pivot.reindex([t for t in tier_order if t in pivot.index])

    fig = go.Figure(go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=[[0, C["surface"]], [0.5, "#1a4a6b"], [1, C["accent"]]],
        text=[[f"{v:.2f}%" if pd.notna(v) else "" for v in row] for row in pivot.values],
        texttemplate="%{text}",
        textfont=dict(size=10),
        hovertemplate="Tier: %{y}<br>Quarter: %{x}<br>Base Rate: %{z:.2f}%<extra></extra>",
        showscale=True,
        colorbar=dict(
            tickfont=dict(color=C["text"]),
            outlinecolor=C["border"],
        )
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text="Early Detection Base Rate Heatmap (%)", font=dict(size=13, color=C["accent"])),
        xaxis=dict(side="bottom", tickangle=-30),
        yaxis=dict(autorange="reversed"),
    )
    return fig

def chart_stock_history(df_history, company_name):
    if df_history.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_history["quarter"],
        y=df_history["final_score"],
        mode="lines+markers",
        name="Final Score",
        line=dict(color=C["accent"], width=2),
        marker=dict(
            size=10,
            color=[PRIORITY_COLORS.get(p, C["standard"]) for p in df_history["smart_money_priority"]],
            line=dict(color=C["bg"], width=2)
        ),
        hovertemplate="Quarter: %{x}<br>Score: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=df_history["quarter"],
        y=df_history["tier1_buyer_count"],
        name="Tier 1 Buyers",
        marker_color=C["accent2"],
        opacity=0.4,
        yaxis="y2",
        hovertemplate="Tier 1 Buyers: %{y}<extra></extra>",
    ))
    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=f"Signal History — {company_name}", font=dict(size=13, color=C["accent"])),
        yaxis=dict(title="Final Score", showgrid=True, gridcolor=C["border"]),
        yaxis2=dict(title="Tier 1 Buyers", overlaying="y", side="right",
                    showgrid=False),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig

# ─────────────────────────────────────────────
# TABLE HELPERS
# ─────────────────────────────────────────────
def make_action_badge(row):
    """Return a buy/watch/hold recommendation string."""
    p = row.get("smart_money_priority", "")
    tier = row.get("market_cap_tier", "")
    stalled = row.get("stalled_flag", False)
    score = row.get("final_score", 0)
    above = row.get("above_tier_average_flag", False)

    if stalled:
        return "⚠ STALLED"
    if p == "Highest Priority" and tier in ("Large", "Mid"):
        return "★ STRONG BUY"
    if p == "High Priority" and tier in ("Large", "Mid") and above:
        return "▲ BUY"
    if p == "High Priority" and tier in ("Large", "Mid"):
        return "▲ BUY"
    if p == "High Priority" and tier == "Small":
        return "→ WATCH"
    if p == "Promoted" and score >= 50:
        return "→ WATCH"
    return "· MONITOR"

# ─────────────────────────────────────────────
# APP INITIALISATION
# ─────────────────────────────────────────────
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.CYBORG,
        "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Syne:wght@400;700;800&display=swap",
    ],
    title="Early Detection Dashboard",
)
server = app.server  


# ─────────────────────────────────────────────
# REUSABLE COMPONENTS
# ─────────────────────────────────────────────
def stat_card(title, value, subtitle=None, color=C["accent"]):
    return html.Div([
        html.Div(title, style={
            "fontSize": "10px", "letterSpacing": "2px", "textTransform": "uppercase",
            "color": C["text_muted"], "marginBottom": "6px", "fontFamily": "'JetBrains Mono', monospace"
        }),
        html.Div(str(value), style={
            "fontSize": "28px", "fontWeight": "700", "color": color,
            "fontFamily": "'Syne', sans-serif", "lineHeight": "1"
        }),
        html.Div(subtitle or "", style={
            "fontSize": "10px", "color": C["text_muted"], "marginTop": "4px",
            "fontFamily": "'JetBrains Mono', monospace"
        }),
    ], style={
        "background": C["surface"],
        "border": f"1px solid {C['border']}",
        "borderTop": f"2px solid {color}",
        "padding": "16px 20px",
        "borderRadius": "4px",
        "flex": "1",
        "minWidth": "120px",
    })

def section_header(title, subtitle=None):
    return html.Div([
        html.Div(title, style={
            "fontSize": "12px", "letterSpacing": "3px", "textTransform": "uppercase",
            "color": C["accent"], "fontFamily": "'JetBrains Mono', monospace",
            "fontWeight": "500",
        }),
        html.Div(subtitle or "", style={
            "fontSize": "10px", "color": C["text_muted"], "marginTop": "2px",
            "fontFamily": "'JetBrains Mono', monospace"
        }),
    ], style={"marginBottom": "16px", "paddingBottom": "8px",
              "borderBottom": f"1px solid {C['border']}"})

# ─────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────
app.layout = html.Div([

    # ── HEADER ──────────────────────────────
    html.Div([
        html.Div([
            html.Div("◈", style={
                "fontSize": "24px", "color": C["accent"],
                "fontFamily": "'JetBrains Mono', monospace", "marginRight": "12px"
            }),
            html.Div([
                html.Div("EARLY DETECTION SIGNAL DASHBOARD", style={
                    "fontSize": "13px", "letterSpacing": "4px", "fontWeight": "700",
                    "color": C["text"], "fontFamily": "'Syne', sans-serif",
                }),
                html.Div("Institutional 13F Accumulation Intelligence", style={
                    "fontSize": "10px", "color": C["text_muted"],
                    "fontFamily": "'JetBrains Mono', monospace", "letterSpacing": "1px"
                }),
            ]),
        ], style={"display": "flex", "alignItems": "center"}),

        html.Div([
            html.Div("QUARTER", style={
                "fontSize": "9px", "letterSpacing": "2px", "color": C["text_muted"],
                "fontFamily": "'JetBrains Mono', monospace", "marginBottom": "4px"
            }),
            dcc.Dropdown(
                id="quarter-select",
                clearable=False,
                style={
                    "width": "150px", "backgroundColor": C["surface2"],
                    "color": C["text"], "border": f"1px solid {C['border']}",
                    "fontFamily": "'JetBrains Mono', monospace", "fontSize": "12px",
                },
            ),
        ]),
    ], style={
        "background": C["surface"],
        "borderBottom": f"1px solid {C['border']}",
        "padding": "16px 32px",
        "display": "flex", "justifyContent": "space-between", "alignItems": "center",
    }),

    # ── MAIN BODY ────────────────────────────
    html.Div([

        # ── SIDEBAR ─────────────────────────
        html.Div([

            # Filters
            html.Div([
                section_header("Filters"),

                html.Div("PRIORITY", style={
                    "fontSize": "9px", "letterSpacing": "2px", "color": C["text_muted"],
                    "fontFamily": "'JetBrains Mono', monospace", "marginBottom": "6px"
                }),
                dcc.Checklist(
                    id="priority-filter",
                    options=[
                        {"label": " ★ Highest Priority", "value": "Highest Priority"},
                        {"label": " ▲ High Priority",    "value": "High Priority"},
                        {"label": " → Promoted",          "value": "Promoted"},
                        {"label": " · Watch",             "value": "Watch"},
                        {"label": "   Standard",          "value": "Standard"},
                    ],
                    value=["Highest Priority", "High Priority", "Promoted"],
                    style={"fontFamily": "'JetBrains Mono', monospace",
                           "fontSize": "11px", "color": C["text"]},
                    labelStyle={"display": "block", "marginBottom": "4px",
                                "cursor": "pointer"},
                    inputStyle={"marginRight": "8px", "accentColor": C["accent"]},
                ),

                html.Hr(style={"borderColor": C["border"], "margin": "16px 0"}),

                html.Div("MARKET CAP TIER", style={
                    "fontSize": "9px", "letterSpacing": "2px", "color": C["text_muted"],
                    "fontFamily": "'JetBrains Mono', monospace", "marginBottom": "6px"
                }),
                dcc.Checklist(
                    id="tier-filter",
                    options=[
                        {"label": " Large",  "value": "Large"},
                        {"label": " Mid",    "value": "Mid"},
                        {"label": " Small",  "value": "Small"},
                        {"label": " Micro",  "value": "Micro"},
                    ],
                    value=["Large", "Mid", "Small"],
                    style={"fontFamily": "'JetBrains Mono', monospace",
                           "fontSize": "11px", "color": C["text"]},
                    labelStyle={"display": "block", "marginBottom": "4px",
                                "cursor": "pointer"},
                    inputStyle={"marginRight": "8px", "accentColor": C["accent"]},
                ),

                html.Hr(style={"borderColor": C["border"], "margin": "16px 0"}),

                html.Div("ENTRY TYPE", style={
                    "fontSize": "9px", "letterSpacing": "2px", "color": C["text_muted"],
                    "fontFamily": "'JetBrains Mono', monospace", "marginBottom": "6px"
                }),
                dcc.Checklist(
                    id="entry-filter",
                    options=[
                        {"label": " Quiet Accumulation",   "value": "Quiet Accumulation"},
                        {"label": " New Listing Discovery", "value": "New Listing Discovery"},
                    ],
                    value=["Quiet Accumulation", "New Listing Discovery"],
                    style={"fontFamily": "'JetBrains Mono', monospace",
                           "fontSize": "11px", "color": C["text"]},
                    labelStyle={"display": "block", "marginBottom": "4px",
                                "cursor": "pointer"},
                    inputStyle={"marginRight": "8px", "accentColor": C["accent"]},
                ),

                html.Hr(style={"borderColor": C["border"], "margin": "16px 0"}),

                html.Div("MIN SCORE", style={
                    "fontSize": "9px", "letterSpacing": "2px", "color": C["text_muted"],
                    "fontFamily": "'JetBrains Mono', monospace", "marginBottom": "8px"
                }),
                dcc.Slider(
                    id="min-score",
                    min=0, max=90, step=5, value=30,
                    marks={0: "0", 30: "30", 60: "60", 90: "90"},
                    tooltip={"placement": "bottom", "always_visible": True},
                ),

                html.Hr(style={"borderColor": C["border"], "margin": "16px 0"}),

                html.Div("SHOW TOP N", style={
                    "fontSize": "9px", "letterSpacing": "2px", "color": C["text_muted"],
                    "fontFamily": "'JetBrains Mono', monospace", "marginBottom": "8px"
                }),
                dcc.Slider(
                    id="top-n",
                    min=10, max=200, step=10, value=50,
                    marks={10: "10", 50: "50", 100: "100", 200: "200"},
                    tooltip={"placement": "bottom", "always_visible": True},
                ),

            ], style={
                "background": C["surface"],
                "border": f"1px solid {C['border']}",
                "borderRadius": "4px",
                "padding": "20px",
                "marginBottom": "12px",
            }),

            # Legend
            html.Div([
                section_header("Signal Guide"),
                html.Div([
                    html.Div([
                        html.Span("★ STRONG BUY", style={
                            "color": C["highest"], "fontFamily": "'JetBrains Mono', monospace",
                            "fontSize": "10px", "fontWeight": "700"
                        }),
                        html.Div("Highest Priority + Large/Mid", style={
                            "color": C["text_muted"], "fontSize": "9px",
                            "fontFamily": "'JetBrains Mono', monospace"
                        }),
                    ], style={"marginBottom": "8px"}),
                    html.Div([
                        html.Span("▲ BUY", style={
                            "color": C["high"], "fontFamily": "'JetBrains Mono', monospace",
                            "fontSize": "10px", "fontWeight": "700"
                        }),
                        html.Div("High Priority + Large/Mid", style={
                            "color": C["text_muted"], "fontSize": "9px",
                            "fontFamily": "'JetBrains Mono', monospace"
                        }),
                    ], style={"marginBottom": "8px"}),
                    html.Div([
                        html.Span("→ WATCH", style={
                            "color": C["promoted"], "fontFamily": "'JetBrains Mono', monospace",
                            "fontSize": "10px", "fontWeight": "700"
                        }),
                        html.Div("High Priority Small / Promoted 50+", style={
                            "color": C["text_muted"], "fontSize": "9px",
                            "fontFamily": "'JetBrains Mono', monospace"
                        }),
                    ], style={"marginBottom": "8px"}),
                    html.Div([
                        html.Span("⚠ STALLED", style={
                            "color": C["watch"], "fontFamily": "'JetBrains Mono', monospace",
                            "fontSize": "10px", "fontWeight": "700"
                        }),
                        html.Div("3+ quarters Early Stage, no growth", style={
                            "color": C["text_muted"], "fontSize": "9px",
                            "fontFamily": "'JetBrains Mono', monospace"
                        }),
                    ]),
                ]),
            ], style={
                "background": C["surface"],
                "border": f"1px solid {C['border']}",
                "borderRadius": "4px",
                "padding": "20px",
            }),

        ], style={"width": "220px", "flexShrink": "0", "display": "flex",
                  "flexDirection": "column", "gap": "0"}),

        # ── CONTENT AREA ────────────────────
        html.Div([

            # ── STAT CARDS ──────────────────
            html.Div(id="stat-cards", style={
                "display": "flex", "gap": "12px", "marginBottom": "20px",
                "flexWrap": "wrap"
            }),

            # ── TOP CHARTS ROW ──────────────
            html.Div([
                html.Div([
                    dcc.Graph(id="chart-priority", config={"displayModeBar": False},
                              style={"height": "250px"})
                ], style={
                    "flex": "1", "background": C["surface"],
                    "border": f"1px solid {C['border']}", "borderRadius": "4px",
                    "padding": "16px",
                }),
                html.Div([
                    dcc.Graph(id="chart-tier-donut", config={"displayModeBar": False},
                              style={"height": "250px"})
                ], style={
                    "width": "280px", "background": C["surface"],
                    "border": f"1px solid {C['border']}", "borderRadius": "4px",
                    "padding": "16px",
                }),
                html.Div([
                    dcc.Graph(id="chart-score-hist", config={"displayModeBar": False},
                              style={"height": "250px"})
                ], style={
                    "flex": "1", "background": C["surface"],
                    "border": f"1px solid {C['border']}", "borderRadius": "4px",
                    "padding": "16px",
                }),
            ], style={"display": "flex", "gap": "12px", "marginBottom": "20px"}),

            # ── SIGNAL TABLE ────────────────
            html.Div([
                html.Div([
                    section_header("Watchlist", "Click a row to see stock detail"),
                ], style={"display": "flex", "justifyContent": "space-between",
                          "alignItems": "flex-start"}),

                dash_table.DataTable(
                    id="signal-table",
                    columns=[
                        {"name": "Rank",        "id": "quarter_rank"},
                        {"name": "Action",      "id": "action"},
                        {"name": "Ticker",      "id": "ticker"},
                        {"name": "Company",     "id": "company_name"},
                        {"name": "Tier",        "id": "market_cap_tier"},
                        {"name": "Priority",    "id": "smart_money_priority"},
                        {"name": "Score",       "id": "final_score"},
                        {"name": "Acc Score",   "id": "accumulation_score"},
                        {"name": "T1 Buyers",   "id": "tier1_buyer_count"},
                        {"name": "Conviction",  "id": "weighted_conviction"},
                        {"name": "Above Avg",   "id": "above_tier_average_flag"},
                        {"name": "Entry Type",  "id": "entry_type"},
                        {"name": "2Q Growth",   "id": "pct_fund_growth_2q"},
                        {"name": "CUSIP",       "id": "cusip"},
                    ],
                    style_table={"overflowX": "auto"},
                    style_header={
                        "backgroundColor": C["surface2"],
                        "color": C["text_muted"],
                        "fontFamily": "'JetBrains Mono', monospace",
                        "fontSize": "9px",
                        "letterSpacing": "1px",
                        "textTransform": "uppercase",
                        "border": f"1px solid {C['border']}",
                        "fontWeight": "500",
                        "padding": "8px 12px",
                    },
                    style_cell={
                        "backgroundColor": C["surface"],
                        "color": C["text"],
                        "fontFamily": "'JetBrains Mono', monospace",
                        "fontSize": "11px",
                        "border": f"1px solid {C['border']}",
                        "padding": "8px 12px",
                        "textOverflow": "ellipsis",
                        "maxWidth": "180px",
                        "whiteSpace": "nowrap",
                        "overflow": "hidden",
                    },
                    style_data_conditional=[
                        {"if": {"row_index": "odd"},
                         "backgroundColor": "rgba(255,255,255,0.02)"},
                        {"if": {"filter_query": '{action} contains "STRONG BUY"'},
                         "color": C["highest"], "fontWeight": "700"},
                        {"if": {"filter_query": '{action} contains "▲ BUY"'},
                         "color": C["high"]},
                        {"if": {"filter_query": '{action} contains "WATCH"'},
                         "color": C["promoted"]},
                        {"if": {"filter_query": '{action} contains "STALLED"'},
                         "color": C["watch"]},
                        {"if": {"filter_query": '{market_cap_tier} = "Large"',
                                "column_id": "market_cap_tier"},
                         "color": C["large"]},
                        {"if": {"filter_query": '{market_cap_tier} = "Mid"',
                                "column_id": "market_cap_tier"},
                         "color": C["mid"]},
                        {"if": {"filter_query": '{market_cap_tier} = "Small"',
                                "column_id": "market_cap_tier"},
                         "color": C["small"]},
                        {"if": {"filter_query": '{market_cap_tier} = "Micro"',
                                "column_id": "market_cap_tier"},
                         "color": C["micro"]},
                        {"if": {"column_id": "above_tier_average_flag",
                                "filter_query": '{above_tier_average_flag} = True'},
                         "color": C["accent2"]},
                        {"if": {"state": "selected"},
                         "backgroundColor": "rgba(0,212,255,0.1)",
                         "border": f"1px solid {C['accent']}"},
                    ],
                    page_size=20,
                    sort_action="native",
                    filter_action="native",
                    row_selectable="single",
                    selected_rows=[],
                    hidden_columns=["cusip"],
                ),
            ], style={
                "background": C["surface"],
                "border": f"1px solid {C['border']}",
                "borderRadius": "4px",
                "padding": "20px",
                "marginBottom": "20px",
            }),

            # ── BOTTOM CHARTS ROW ───────────
            html.Div([
                html.Div([
                    dcc.Graph(id="chart-trend", config={"displayModeBar": False},
                              style={"height": "280px"})
                ], style={
                    "flex": "1", "background": C["surface"],
                    "border": f"1px solid {C['border']}", "borderRadius": "4px",
                    "padding": "16px",
                }),
                html.Div([
                    dcc.Graph(id="chart-heatmap", config={"displayModeBar": False},
                              style={"height": "280px"})
                ], style={
                    "flex": "1", "background": C["surface"],
                    "border": f"1px solid {C['border']}", "borderRadius": "4px",
                    "padding": "16px",
                }),
            ], style={"display": "flex", "gap": "12px", "marginBottom": "20px"}),

            # ── STOCK DETAIL PANEL ──────────
            html.Div(id="stock-detail-panel", style={"marginBottom": "20px"}),

        ], style={"flex": "1", "overflowY": "auto", "overflowX": "hidden"}),

    ], style={
        "display": "flex", "gap": "20px", "padding": "24px 32px",
        "background": C["bg"], "minHeight": "calc(100vh - 70px)",
    }),

], style={"background": C["bg"], "minHeight": "100vh",
          "fontFamily": "'JetBrains Mono', monospace"})

# ─────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────

# Populate quarter dropdown on load
@app.callback(
    Output("quarter-select", "options"),
    Output("quarter-select", "value"),
    Input("quarter-select", "id"),
)
def load_quarters(_):
    quarters = get_quarters()
    if not quarters:
        return [], None
    options = [{"label": q, "value": q} for q in quarters]
    return options, quarters[0]


# Update stat cards
@app.callback(
    Output("stat-cards", "children"),
    Input("quarter-select", "value"),
)
def update_stats(quarter):
    if not quarter:
        return []
    s = get_summary_stats(quarter)
    if not s:
        return []
    return [
        stat_card("Total Signals",        s.get("total", 0),    "this quarter"),
        stat_card("Highest Priority",     s.get("highest", 0),  "strongest signals",    C["highest"]),
        stat_card("High Priority",        s.get("high", 0),     "actionable signals",   C["high"]),
        stat_card("Top 50",               s.get("top_50", 0),   "Large/Mid dominated",  C["promoted"]),
        stat_card("Large/Mid in Top 50",  s.get("large_mid_top50", 0), "predictive tier", C["mid"]),
        stat_card("Above Tier Avg",       s.get("above_avg", 0), "unusual activity",    C["accent"]),
        stat_card("Stalled Signals",      s.get("stalled", 0),  "investigate before acting", C["watch"]),
        stat_card("Max Score",            s.get("max_score", 0), f"avg {s.get('avg_score',0)}", C["accent2"]),
    ]


# Update signal table
@app.callback(
    Output("signal-table", "data"),
    Input("quarter-select",  "value"),
    Input("priority-filter", "value"),
    Input("tier-filter",     "value"),
    Input("entry-filter",    "value"),
    Input("min-score",       "value"),
    Input("top-n",           "value"),
)
def update_table(quarter, priorities, tiers, entry_types, min_score, top_n):
    if not quarter:
        return []
    df = get_signals(quarter, priorities, tiers, entry_types, min_score, top_n)
    if df.empty:
        return []
    df["action"] = df.apply(make_action_badge, axis=1)
    df["above_tier_average_flag"] = df["above_tier_average_flag"].apply(
        lambda x: "✓ Yes" if x else "—"
    )
    df["pct_fund_growth_2q"] = df["pct_fund_growth_2q"].apply(
        lambda x: f"{x:+.1f}%" if pd.notna(x) and x != 0 else "—"
    )
    cols = ["quarter_rank", "action", "ticker", "company_name", "market_cap_tier",
            "smart_money_priority", "final_score", "accumulation_score",
            "tier1_buyer_count", "weighted_conviction", "above_tier_average_flag",
            "entry_type", "pct_fund_growth_2q", "cusip"]
    return df[cols].to_dict("records")


# Update priority chart
@app.callback(
    Output("chart-priority", "figure"),
    Input("quarter-select", "value"),
)
def update_priority_chart(quarter):
    if not quarter:
        return go.Figure()
    df = get_priority_distribution(quarter)
    return chart_priority_bar(df)


# Update tier donut
@app.callback(
    Output("chart-tier-donut", "figure"),
    Input("quarter-select",  "value"),
    Input("priority-filter", "value"),
    Input("tier-filter",     "value"),
)
def update_donut(quarter, priorities, tiers):
    if not quarter:
        return go.Figure()
    df = get_signals(quarter, priorities, tiers)
    return chart_tier_donut(df)


# Update score histogram
@app.callback(
    Output("chart-score-hist", "figure"),
    Input("quarter-select", "value"),
)
def update_hist(quarter):
    if not quarter:
        return go.Figure()
    df = get_score_distribution(quarter)
    return chart_score_histogram(df)


# Update trend chart (static — uses all quarters)
@app.callback(
    Output("chart-trend", "figure"),
    Input("quarter-select", "id"),
)
def update_trend(_):
    df = get_quarterly_trend()
    return chart_quarterly_trend(df)


# Update heatmap (static — uses all quarters)
@app.callback(
    Output("chart-heatmap", "figure"),
    Input("quarter-select", "id"),
)
def update_heatmap(_):
    df = get_tier_base_rates()
    return chart_base_rate_heatmap(df)


# Update stock detail panel on row click
@app.callback(
    Output("stock-detail-panel", "children"),
    Input("signal-table", "selected_rows"),
    State("signal-table", "data"),
    State("quarter-select", "value"),
)
def update_stock_detail(selected_rows, table_data, quarter):
    if not selected_rows or not table_data:
        return html.Div()

    row = table_data[selected_rows[0]]
    cusip = row.get("cusip", "")
    if not cusip:
        return html.Div()

    company = row.get("company_name", "Unknown")
    ticker = row.get("ticker") or cusip
    action_raw = row.get("action", "")
    action_color = (C["highest"] if "STRONG" in action_raw
                    else C["high"] if "BUY" in action_raw
                    else C["watch"] if "STALLED" in action_raw
                    else C["promoted"])

    history = get_stock_history(cusip)

    return html.Div([
        html.Div([

            # Left: key metrics
            html.Div([
                section_header(f"{ticker} — {company}", "Stock Deep Dive"),

                html.Div([
                    html.Span(action_raw, style={
                        "color": action_color, "fontSize": "14px", "fontWeight": "700",
                        "fontFamily": "'JetBrains Mono', monospace",
                        "padding": "4px 12px",
                        "border": f"1px solid {action_color}",
                        "borderRadius": "2px",
                        "marginBottom": "16px",
                        "display": "inline-block",
                    }),
                ]),

                html.Div([
                    html.Div([
                        html.Div("Final Score",
                                 style={"fontSize": "9px", "color": C["text_muted"],
                                        "letterSpacing": "1px"}),
                        html.Div(str(row.get("final_score", "—")),
                                 style={"fontSize": "24px", "color": C["accent"],
                                        "fontWeight": "700", "fontFamily": "'Syne', sans-serif"}),
                    ], style={"marginBottom": "16px"}),

                    html.Div([
                        html.Div([
                            html.Span("Priority   ", style={"color": C["text_muted"]}),
                            html.Span(str(row.get("smart_money_priority", "—")),
                                      style={"color": PRIORITY_COLORS.get(
                                          str(row.get("smart_money_priority", "")),
                                          C["text"])}),
                        ], style={"marginBottom": "6px"}),
                        html.Div([
                            html.Span("Tier       ", style={"color": C["text_muted"]}),
                            html.Span(str(row.get("market_cap_tier", "—")),
                                      style={"color": TIER_COLORS.get(
                                          str(row.get("market_cap_tier", "")),
                                          C["text"])}),
                        ], style={"marginBottom": "6px"}),
                        html.Div([
                            html.Span("Acc Score  ", style={"color": C["text_muted"]}),
                            html.Span(str(row.get("accumulation_score", "—"))),
                        ], style={"marginBottom": "6px"}),
                        html.Div([
                            html.Span("T1 Buyers  ", style={"color": C["text_muted"]}),
                            html.Span(str(row.get("tier1_buyer_count", "—")),
                                      style={"color": C["accent2"]}),
                        ], style={"marginBottom": "6px"}),
                        html.Div([
                            html.Span("Conviction ", style={"color": C["text_muted"]}),
                            html.Span(str(row.get("weighted_conviction", "—")),
                                      style={"color": C["accent2"]}),
                        ], style={"marginBottom": "6px"}),
                        html.Div([
                            html.Span("2Q Growth  ", style={"color": C["text_muted"]}),
                            html.Span(str(row.get("pct_fund_growth_2q", "—"))),
                        ], style={"marginBottom": "6px"}),
                        html.Div([
                            html.Span("Entry Type ", style={"color": C["text_muted"]}),
                            html.Span(str(row.get("entry_type", "—"))),
                        ], style={"marginBottom": "6px"}),
                        html.Div([
                            html.Span("Above Avg  ", style={"color": C["text_muted"]}),
                            html.Span(str(row.get("above_tier_average_flag", "—")),
                                      style={"color": C["accent2"] if
                                             "Yes" in str(row.get("above_tier_average_flag", ""))
                                             else C["text"]}),
                        ]),
                    ], style={"fontFamily": "'JetBrains Mono', monospace", "fontSize": "11px"}),
                ]),
            ], style={"width": "280px", "flexShrink": "0"}),

            # Right: history chart
            html.Div([
                dcc.Graph(
                    figure=chart_stock_history(history, company),
                    config={"displayModeBar": False},
                    style={"height": "300px"},
                )
            ], style={"flex": "1"}),

        ], style={"display": "flex", "gap": "32px"}),
    ], style={
        "background": C["surface"],
        "border": f"1px solid {C['accent']}",
        "borderRadius": "4px",
        "padding": "24px",
        "boxShadow": f"0 0 20px rgba(0,212,255,0.1)",
    })


# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  EARLY DETECTION DASHBOARD")
    print("="*60)
    print(f"\n  Update DB_CONFIG at the top of this file first.")
    print(f"  Then open: http://127.0.0.1:8050\n")
    app.run(debug=False, host="0.0.0.0", port=8050)
