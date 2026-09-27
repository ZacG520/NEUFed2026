"""
Chart builders. Each takes a standard table from data_sources (dates as the index,
one column per series) and returns a Plotly figure in the team style.

    make_chart(df, "line", title="CPI Inflation", y_suffix="%", ref_lines={2: "2% target"})

Chart types:
    "line"          one line per column
    "contribution"  stacked bars (+/-) per column, with an optional total line on top
    "bar"           bars per column, grouped side by side or stacked
    "dual_axis"     lines on two y-axes (columns listed in right=[...] use the right axis)

Options every chart type accepts are documented in make_chart().
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Team style: everything comes from utils/graph_templates.py (the fed_2025 template),
# so the old notebooks and this tool always match. Change the style there, not here.
# ---------------------------------------------------------------------------

CODE_DIR = Path(__file__).resolve().parent.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
from utils.graph_templates import colors_dict as COLORS, default_colorway as COLORWAY, \
    default_font as FONT, default_text_color as TEXT_COLOR, fed_2025_template  # noqa: E402  (registers "fed_2025")

from .data_sources import _match_column  # noqa: E402

COLORWAY_NAMES = [name for c in COLORWAY for name, hex_ in COLORS.items() if hex_ == c]
TEMPLATE = fed_2025_template.layout
MUTED_TEXT = COLORS["muted_text"]
RECESSION_COLOR = "rgba(135, 147, 150, 0.18)"
WIDTH, HEIGHT = TEMPLATE.width, TEMPLATE.height

FIGURES_DIR = CODE_DIR.parent / "figures"


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def make_chart(df: pd.DataFrame, chart_type: str = "line", *,
               title="", subtitle="", y_title="", x_title="", source="",
               columns=None, labels=None, colors=None,
               start=None, end=None,
               y_suffix="", y_prefix="", decimals=None, y_range=None, x_format=None,
               ref_lines=None, recessions=False, end_labels=None,
               legend=None, width=WIDTH, height=HEIGHT,
               **type_options) -> go.Figure:
    """
    Builds a chart from a standard table.

    Common options:
        title, subtitle: text at the top. Subtitle is smaller, e.g. "Monthly, Seasonally Adjusted"
        y_title, x_title: axis titles (x_title is usually unnecessary for dates)
        source: note at the bottom left, e.g. "Source: BLS via FRED"
        columns: which columns to plot, in order (default: all)
        labels: rename series for the legend, {"CPIAUCSL": "Headline CPI"}
        colors: {series: color}, a team color name ("orange") or hex ("#CF8B40")
        start, end: date limits, "YYYY-MM-DD"
        y_suffix, y_prefix: tick text, e.g. y_suffix="%" or y_prefix="$"
        decimals: decimals on the y-axis and labels (default: automatic)
        y_range: [min, max] for the y-axis
        x_format: date tick format, e.g. "%Y", "%b %Y", "Q%q %Y" (default: automatic)
        ref_lines: horizontal dashed line(s): 2, [0, 2], or {2: "2% target"}
        recessions: True to shade U.S. recessions (NBER, via FRED)
        end_labels: show the latest value at the end of each line (default: on for <= 4 lines)
        legend: "top", "bottom", "right", or "none" (default: chosen from the number of series)
        width, height: size in pixels (PNG is saved at 2x for sharpness)

    Chart-specific options:
        "contribution": total="Real GDP" (column drawn as a line), or total="sum" to add
                        up the bars; total_label="..." renames it
        "bar":          mode="group" (side by side) or "stack"
        "dual_axis":    right=["col", ...] (required), y2_title, y2_suffix, y2_prefix, y2_range
    """
    builders = {
        "line": _line_chart,
        "contribution": _contribution_chart,
        "bar": _bar_chart,
        "dual_axis": _dual_axis_chart,
    }
    if chart_type not in builders:
        raise ValueError(f"chart_type must be one of {list(builders)}, not {chart_type!r}")

    df = _prepare(df, columns, start, end)
    if labels:
        type_options = _rename_options(type_options, labels)
        df = df.rename(columns=labels)
    type_options = _match_option_columns(type_options, df.columns)
    color_map = _assign_colors(df.columns, colors, chart_type, type_options)

    fig = builders[chart_type](df, color_map, **type_options)
    fmt = _number_format(df, decimals)
    fmt2 = None
    if chart_type == "dual_axis":
        right = type_options["right"]
        right = [right] if isinstance(right, str) else right
        fmt = _number_format(df.drop(columns=right), decimals)
        fmt2 = _number_format(df[right], decimals)

    _apply_style(fig, title, subtitle, y_title, x_title, width, height)
    fig.update_yaxes(ticksuffix=y_suffix, tickprefix=y_prefix, tickformat=fmt, **_left_axis(fig))
    if fmt2:
        fig.update_yaxes(tickformat=fmt2, secondary_y=True)
    if y_range:
        fig.update_yaxes(range=y_range, **_left_axis(fig))
    if x_format:
        fig.update_xaxes(tickformat=x_format)

    if ref_lines is not None:
        _add_ref_lines(fig, ref_lines, y_suffix, y_prefix, fmt)
    if recessions:
        source = _add_recessions(fig, df.index, source)

    # Order matters: the legend decides the top margin, which the titles and end labels use
    _place_legend(fig, legend, chart_type)
    _add_titles(fig, title, subtitle)

    line_count = sum(1 for t in fig.data if t.type == "scatter" and "lines" in (t.mode or "") and t.showlegend is not False)
    if end_labels or (end_labels is None and chart_type in ("line", "dual_axis") and line_count <= 4):
        _add_end_labels(fig, y_suffix, y_prefix, fmt, fmt2, type_options)

    if source:
        _add_source(fig, source)  # after the legend, which may have grown the bottom margin
    return fig


def save_png(fig: go.Figure, name: str, folder=None, html=False, scale=2) -> Path:
    """
    Saves the figure as figures/png/<name>.png (and optionally figures/<name>.html).
    scale=2 doubles the pixel count so the PNG stays sharp on slides.
    """
    folder = Path(folder) if folder else FIGURES_DIR / "png"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.png"
    try:
        fig.write_image(path, scale=scale)
    except Exception as err:
        if "chrome" in str(err).lower():
            raise RuntimeError("Saving PNGs needs Google Chrome. Install Chrome, or run `plotly_get_chrome` "
                               "in a terminal with the .venv active, then try again.") from None
        raise
    if html:
        fig.write_html(FIGURES_DIR / f"{name}.html")
    return path


# ---------------------------------------------------------------------------
# Chart types
# ---------------------------------------------------------------------------

def _line_chart(df, color_map, dashes=None):
    """dashes: optional {series: "dash" | "dot" | "dashdot"}"""
    fig = go.Figure()
    for col in df.columns:
        srs = df[col].dropna()
        fig.add_trace(go.Scatter(
            x=srs.index, y=srs.values, name=col, mode="lines",
            line=dict(color=color_map[col], dash=(dashes or {}).get(col, "solid")),  # width from template
        ))
    return fig


def _contribution_chart(df, color_map, total=None, total_label=None):
    fig = go.Figure()
    total_srs = None
    if total == "sum":
        total_srs = df.sum(axis=1, min_count=1).rename(total_label or "Total")
    elif total is not None:
        total_srs = df[total].rename(total_label or total)
        df = df.drop(columns=total)

    for col in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df[col], name=col,
            marker=dict(color=color_map[col], line=dict(color="white", width=1)),
            hovertemplate="%{x|%Y-%m-%d}<br>" + col + ": %{y:.2f}<extra></extra>",
        ))

    if total_srs is not None:
        fig.add_trace(go.Scatter(
            x=total_srs.index, y=total_srs.values, name=total_srs.name, mode="lines+markers",
            line=dict(color=TEXT_COLOR, width=3),
            marker=dict(size=10, color=TEXT_COLOR, line=dict(color="white", width=2)),
        ))

    fig.update_layout(barmode="relative", bargap=0.25)
    fig.update_yaxes(zeroline=True, zerolinecolor=MUTED_TEXT, zerolinewidth=1.5)
    return fig


def _bar_chart(df, color_map, mode="group"):
    if mode not in ("group", "stack"):
        raise ValueError('mode must be "group" or "stack"')
    fig = go.Figure()
    for col in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df[col], name=col,
            marker=dict(color=color_map[col], line=dict(color="white", width=1)),
            hovertemplate="%{x|%Y-%m-%d}<br>" + col + ": %{y:.2f}<extra></extra>",
        ))
    fig.update_layout(barmode="relative" if mode == "stack" else "group", bargap=0.25, bargroupgap=0.05)
    fig.update_yaxes(zeroline=True, zerolinecolor=MUTED_TEXT, zerolinewidth=1.5)
    return fig


def _dual_axis_chart(df, color_map, right=None, y2_title="", y2_suffix="", y2_prefix="", y2_range=None):
    if not right:
        raise ValueError('dual_axis needs right=["column", ...] to say which series use the right axis')
    right = [right] if isinstance(right, str) else list(right)
    missing = [c for c in right if c not in df.columns]
    if missing:
        raise KeyError(f"right={missing} not found. Columns: {list(df.columns)}")
    if len(right) == len(df.columns):
        raise ValueError("At least one series has to stay on the left axis.")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for col in df.columns:
        on_right = col in right
        srs = df[col].dropna()
        fig.add_trace(go.Scatter(
            x=srs.index, y=srs.values, mode="lines",
            name=f"{col} (right axis)" if on_right else f"{col} (left axis)",
            line=dict(color=color_map[col]),
        ), secondary_y=on_right)

    # The template only styles the left axis; give the right axis the same fonts
    fig.update_yaxes(title_text=y2_title or None, ticksuffix=y2_suffix, tickprefix=y2_prefix,
                     showgrid=False, secondary_y=True,
                     tickfont=TEMPLATE.yaxis.tickfont.to_plotly_json(),
                     title_font=TEMPLATE.yaxis.title.font.to_plotly_json())
    if y2_range:
        fig.update_yaxes(range=y2_range, secondary_y=True)
    return fig


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------

def _left_axis(fig):
    """update_yaxes() only accepts secondary_y on two-axis figures; this limits updates to the left axis there."""
    return {"secondary_y": False} if "yaxis2" in fig.layout.to_plotly_json() else {}


def _prepare(df, columns, start, end):
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("Expected a table with dates as the index (use load_data() to make one).")
    if columns is not None:
        columns = [columns] if isinstance(columns, str) else list(columns)
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise KeyError(f"Columns {missing} not found. Available: {list(df.columns)}")
        df = df[columns]
    df = df.sort_index().loc[start:end].dropna(how="all")
    if df.empty:
        raise ValueError("No data left to plot (check start/end and columns).")
    return df


def _rename_options(options, labels):
    """Keeps options like total= or right= working after the columns are renamed."""
    options = dict(options)
    for key in ("total", "right"):
        val = options.get(key)
        if isinstance(val, str):
            options[key] = labels.get(val, val)
        elif isinstance(val, (list, tuple)):
            options[key] = [labels.get(v, v) for v in val]
    if "dashes" in options:
        options["dashes"] = {labels.get(k, k): v for k, v in options["dashes"].items()}
    return options


def _match_option_columns(options, columns):
    """total= and right= name columns; match them forgivingly (case, spacing) with suggestions on typos."""
    options = dict(options)
    if isinstance(options.get("total"), str) and options["total"] != "sum":
        options["total"] = _match_column(options["total"], columns)
    if options.get("right"):
        right = [options["right"]] if isinstance(options["right"], str) else options["right"]
        options["right"] = [_match_column(c, columns) for c in right]
    return options


def _check_color(series, value):
    try:
        go.scatter.Line(color=value)
    except ValueError:
        raise ValueError(f"Color {value!r} for {series!r} isn't a color. Use a team color "
                         f"({', '.join(COLORWAY_NAMES)}), a hex code like '#CF8B40', or a CSS name like 'green'.") from None
    return value


def _assign_colors(columns, colors, chart_type, options):
    """Fixed-order team colors; user choices in `colors` win. Errors instead of repeating colors."""
    colors = {_match_column(k, columns): _check_color(k, COLORS.get(v, v)) for k, v in (colors or {}).items()}
    skip = {options.get("total")} if chart_type == "contribution" else set()
    series = [c for c in columns if c not in skip]
    free = [c for c in COLORWAY if c not in colors.values()]
    result = {}
    for col in series:
        if col in colors:
            result[col] = colors[col]
        elif free:
            result[col] = free.pop(0)
        else:
            raise ValueError(
                f"{len(series)} series is more than the {len(COLORWAY)} team colors, and repeated colors "
                "make series impossible to tell apart. Pick fewer columns (columns=[...]), combine the small ones "
                "into an 'Other' column, or give each extra series a color with colors={...}.")
    return result


def _number_format(df, decimals):
    if decimals is not None:
        return f",.{decimals}f"
    span = (df.max(numeric_only=True).max() - df.min(numeric_only=True).min())
    if pd.isna(span):
        return None
    return ",.0f" if span >= 20 else (",.1f" if span >= 2 else ",.2f")


def _apply_style(fig, title, subtitle, y_title, x_title, width, height):
    """Applies the fed_2025 template, plus layout the template can't know (margins, title placement)."""
    title_font = TEMPLATE.title.font.to_plotly_json()
    fig.update_layout(
        template="fed_2025",
        width=width, height=height,
        font=dict(family=FONT, color=TEXT_COLOR),  # for hover boxes and anything the template doesn't cover
        margin=dict(l=80, r=90, t=0, b=70),  # top margin is set in _add_titles()
    )
    fig.update_xaxes(title_text=x_title or None)
    fig.update_yaxes(title_text=y_title or None, **_left_axis(fig))
    for trace in fig.data:
        if trace.type == "scatter" and trace.hovertemplate is None:
            trace.hovertemplate = "%{x|%Y-%m-%d}<br>" + str(trace.name) + ": %{y:.2f}<extra></extra>"


def _add_titles(fig, title, subtitle):
    """
    Title and subtitle as text boxes pinned to the top-left corner, so they sit at the
    same pixel positions on every chart (Plotly's own title/subtitle spacing drifts).
    Fonts come from the template's title settings; the subtitle is ~60% the size, like <sup>.
    The top margin fits the titles, plus room for the legend if it sits above the plot.
    """
    title_font = TEMPLATE.title.font.to_plotly_json()
    title_h = round(title_font["size"] * 1.3)
    sub_size = round(title_font["size"] * 0.62)
    legend_on_top = fig.layout.showlegend and fig.layout.legend.yanchor == "bottom" and fig.layout.legend.y > 1
    top = 14 + (title_h if title else 0) + (round(sub_size * 1.4) if subtitle else 0) + (45 if legend_on_top else 20)
    fig.update_layout(margin_t=max(top, 40))

    left = -fig.layout.margin.l + 30
    if title:
        fig.add_annotation(text=title, xref="paper", x=0, xshift=left, xanchor="left",
                           yref="paper", y=1, yshift=top - 14, yanchor="top", showarrow=False,
                           font=title_font)
    if subtitle:
        fig.add_annotation(text=subtitle, xref="paper", x=0, xshift=left, xanchor="left",
                           yref="paper", y=1, yshift=top - 14 - (title_h if title else 0), yanchor="top",
                           showarrow=False, font={**title_font, "size": sub_size})


def _place_legend(fig, legend, chart_type):
    shown = [t for t in fig.data if t.showlegend is not False and t.name]
    if legend is None:
        if len(shown) <= 1:
            legend = "none"  # a single series is named by the title
        elif chart_type == "contribution" or len(shown) > 5:
            legend = "right"
        elif sum(len(str(t.name)) for t in shown) > 60:
            legend = "bottom"
        else:
            legend = "top"

    # Only the position changes here; font and background come from the template
    if legend == "none":
        fig.update_layout(showlegend=False)
    elif legend == "top":
        fig.update_layout(legend=dict(orientation="h", x=1, xanchor="right", y=1.02, yanchor="bottom"))
    elif legend == "bottom":
        fig.update_layout(legend=dict(orientation="h", x=0, xanchor="left", y=-0.12, yanchor="top"))
        fig.update_layout(margin_b=fig.layout.margin.b + 50)
    elif legend == "right":
        fig.update_layout(legend=dict(orientation="v", x=1.02, xanchor="left", y=0.5, yanchor="middle",
                                      traceorder="normal"))
    else:
        raise ValueError('legend must be "top", "bottom", "right", or "none"')

    # Plotly lists stacked bars bottom-to-top; reverse so the legend reads like the stack
    if chart_type == "contribution" and legend == "right":
        fig.update_layout(legend_traceorder="reversed")
    fig.update_layout(showlegend=legend != "none")


def _fmt_value(value, prefix, suffix, fmt):
    decimals = int(fmt[-2]) if fmt and fmt[-1] == "f" else 1
    return f"{prefix}{value:,.{decimals}f}{suffix}"


def _add_end_labels(fig, suffix, prefix, fmt, fmt2, options):
    """
    Dot at the end of each line + a column of latest-value labels at the right edge.
    Each label has a small dot in its line's color. Labels are spread apart so none
    overlap, measuring positions as a fraction of each axis's range so this also
    works when lines are on two different axes.
    """
    lines = []
    for trace in list(fig.data):
        if trace.type != "scatter" or "lines" not in (trace.mode or "") or len(trace.y) == 0:
            continue
        lines.append((trace, str(trace.name).endswith("(right axis)")))

    # Fix each y-axis range explicitly (unless the user set one), so that a 0-1 position
    # means the same pixel height on both axes. Ref lines are kept inside the range.
    ranges = {}
    ref_values = [s.y0 for s in fig.layout.shapes if s.y0 is not None and s.y0 == s.y1]
    for on_right in (False, True):
        ys = [pd.Series(t.y, dtype=float) for t, r in lines if r == on_right]
        if not ys:
            continue
        axis = fig.layout.yaxis2 if on_right else fig.layout.yaxis
        if axis.range:
            low, high = axis.range
        else:
            if not on_right and ref_values:
                ys.append(pd.Series(ref_values, dtype=float))
            all_y = pd.concat(ys)
            pad = (all_y.max() - all_y.min()) * 0.06 or 1
            low, high = all_y.min() - pad, all_y.max() + pad
            fig.update_yaxes(range=[low, high], **({"secondary_y": True} if on_right else _left_axis(fig)))
        ranges[on_right] = (low, high - low)

    # Keep labels at least ~26 pixels apart (as a fraction of the plot's height)
    min_gap = 26 / (fig.layout.height - fig.layout.margin.t - fig.layout.margin.b)
    positions = [(float(t.y[-1]) - ranges[r][0]) / ranges[r][1] for t, r in lines]
    placed = {}
    for i in sorted(range(len(lines)), key=lambda i: positions[i]):
        y = positions[i]
        if placed and y - max(placed.values()) < min_gap:
            y = max(placed.values()) + min_gap
        placed[i] = y
    # Labels pushed past the top of the plot would disappear; slide them back down
    ceiling = 1.0
    for i in sorted(placed, key=placed.get, reverse=True):
        placed[i] = min(placed[i], ceiling)
        ceiling = placed[i] - min_gap

    label_x = max(pd.Timestamp(t.x[-1]) for t, _ in lines)
    first_x = min(pd.Timestamp(t.x[0]) for t, _ in lines)
    # Extra room past the last date so labels sit inside the plot, clear of any right axis
    fig.update_xaxes(range=[first_x, label_x + (label_x - first_x) * 0.08])
    for i, (trace, on_right) in enumerate(lines):
        yref = "y2" if on_right else "y"
        low, span = ranges[on_right]
        moved = abs(placed[i] - positions[i]) > 1e-9 or pd.Timestamp(trace.x[-1]) != label_x
        value_text = _fmt_value(
            float(trace.y[-1]),
            options.get("y2_prefix", "") if on_right else prefix,
            options.get("y2_suffix", "") if on_right else suffix,
            fmt2 if on_right else fmt)
        fig.add_trace(go.Scatter(
            x=[trace.x[-1]], y=[trace.y[-1]], mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=10, color=trace.line.color, line=dict(color="white", width=2)),
            yaxis=yref,
        ))
        fig.add_annotation(
            x=label_x, y=low + placed[i] * span, yref=yref, xanchor="left", xshift=10, showarrow=False,
            # The colored dot is only needed when the label had to move away from its line
            text=(f"<span style='color:{trace.line.color}'>●</span> " if moved else "") + f"<b>{value_text}</b>",
            font=dict(family=FONT, size=16, color=TEXT_COLOR),
        )


def _add_ref_lines(fig, ref_lines, suffix, prefix, fmt):
    if isinstance(ref_lines, (int, float)):
        ref_lines = {ref_lines: ""}
    elif isinstance(ref_lines, (list, tuple)):
        ref_lines = {v: "" for v in ref_lines}
    for value, label in ref_lines.items():
        fig.add_hline(y=value, line=dict(color=MUTED_TEXT, width=1.5, dash="dash"), layer="below")
        if label:
            fig.add_annotation(x=0.005, xref="paper", y=value, yanchor="bottom", xanchor="left",
                               text=label, showarrow=False, bgcolor="rgba(255,255,255,0.85)",
                               font=dict(family=FONT, size=15, color=MUTED_TEXT))


def _add_recessions(fig, index, source):
    """Shades NBER recession months (FRED series USREC) within the chart's date range."""
    from .data_sources import load_fred
    rec = load_fred("USREC", start=index.min() - pd.DateOffset(months=1), end=index.max())["USREC"]
    in_rec = rec == 1
    starts = rec.index[in_rec & ~in_rec.shift(1, fill_value=False)]
    ends = rec.index[in_rec & ~in_rec.shift(-1, fill_value=False)]
    for s, e in zip(starts, ends):
        fig.add_vrect(x0=max(s, index.min()), x1=min(e + pd.offsets.MonthEnd(1), index.max()),
                      fillcolor=RECESSION_COLOR, line_width=0, layer="below")
    note = "Shaded areas indicate U.S. recessions."
    return f"{source}  {note}" if source else note


def _add_source(fig, source):
    fig.add_annotation(x=0, xref="paper", y=0, yref="paper", yshift=-fig.layout.margin.b + 8,
                       xanchor="left", yanchor="bottom", showarrow=False, text=source,
                       font=dict(family=FONT, size=13, color=MUTED_TEXT))
