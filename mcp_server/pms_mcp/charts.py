"""Chart rendering: one SVG renderer for every output (inline chat view, PNG for documents).

Follows the reference data-viz specs: validated categorical palette in fixed slot order,
one y-axis, 2px lines with ringed end dots, bars <= 24px with 4px rounded data ends and 2px
gaps, solid hairline grid, legend for >= 2 series, selective direct labels.
"""

from dataclasses import dataclass
from typing import Any, Literal
from xml.sax.saxutils import escape

import vl_convert

from .datasets import Dataset
from .formats import Kind, check_scale, date_labels, format_tick, format_value, infer_kind, nice_ticks
from .i18n import Lang

MAX_SERIES = 8
MAX_BARS = 60
MAX_POINTS = 2000

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "secondary": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
    },
}
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


class ChartError(ValueError):
    pass


@dataclass
class ChartData:
    kind: Literal["line", "bar"]
    title: str
    subtitle: str | None
    x_name: str
    y_name: str
    y_kind: Kind
    categories: list[Any]
    tick_labels: list[str]
    full_labels: list[str]
    series: list[tuple[str, list[float | None]]]  # (name, values aligned to categories)


def build_chart_data(ds: Dataset, kind: str, x: str, y: str, series: str | None, title: str,
                     subtitle: str | None, y_format: Kind | None, lang: Lang = "en") -> ChartData:
    names = [c["name"] for c in ds.columns]
    for col in (x, y, series):
        if col is not None and col not in names:
            raise ChartError(f"Column {col!r} is not in dataset {ds.id}. Columns: {names}")
    xi, yi = names.index(x), names.index(y)
    si = names.index(series) if series else None
    if any(r[yi] is not None and not isinstance(r[yi], (int, float)) for r in ds.rows):
        raise ChartError(f"Column {y!r} is not numeric; charts plot one numeric measure on the y-axis.")

    categories: list[Any] = []
    seen: set = set()
    groups: dict[str, dict[Any, float | None]] = {}
    for r in ds.rows:
        if r[xi] not in seen:
            seen.add(r[xi])
            categories.append(r[xi])
        name = str(r[si]) if si is not None else y
        groups.setdefault(name, {})[r[xi]] = r[yi]
    if not categories:
        raise ChartError("The dataset is empty.")
    if all(r[yi] is None for r in ds.rows):
        raise ChartError(f"Column {y!r} has no values to plot (all NULL).")
    x_kind = infer_kind(x, ds.columns[xi]["type"], categories)
    if x_kind == "date" or all(isinstance(c, (int, float)) for c in categories):
        categories.sort()
    if len(groups) > MAX_SERIES:
        raise ChartError(f"{len(groups)} series is too many to tell apart (max {MAX_SERIES}). Filter to fewer "
                         "values, fold the rest into 'Other' in SQL, or chart without a series column.")
    if kind == "bar" and len(categories) * len(groups) > MAX_BARS:
        raise ChartError(f"{len(categories) * len(groups)} bars is too many (max {MAX_BARS}); "
                         "aggregate to fewer periods or use a line chart.")
    if len(categories) > MAX_POINTS:
        raise ChartError(f"{len(categories)} x values is too many (max {MAX_POINTS}); aggregate first.")

    if x_kind == "date":
        ticks, full = date_labels(categories, lang)
    else:
        ticks = full = [str(c) for c in categories]
    y_values = [r[yi] for r in ds.rows]
    try:
        check_scale(y, y_format, y_values)
    except ValueError as e:
        raise ChartError(str(e)) from None
    return ChartData(
        kind=kind, title=title, subtitle=subtitle, x_name=x, y_name=y,
        y_kind=y_format or infer_kind(y, ds.columns[yi]["type"], y_values),
        categories=categories, tick_labels=ticks, full_labels=full,
        series=[(name, [vals.get(c) for c in categories]) for name, vals in groups.items()],
    )


def _text_width(text: str, size: float) -> float:
    return len(text) * size * 0.56


@dataclass
class Layout:
    width: int
    height: int
    left: float
    right: float
    top: float
    bottom: float
    x_positions: list[float]


def render_svg(chart: ChartData, theme: str = "light", width: int = 800, height: int = 450) -> tuple[str, Layout]:
    t = THEMES[theme]
    pad = 20
    out: list[str] = []
    multi = len(chart.series) > 1

    def text(x, y, s, size=11, fill=t["muted"], anchor="start", weight=400):
        out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
                   f'font-weight="{weight}">{escape(s)}</text>')

    top = pad
    if chart.title:
        text(pad, top + 15, chart.title, 16, t["ink"], weight=600)
        top += 26
    if chart.subtitle:
        text(pad, top + 12, chart.subtitle, 12, t["secondary"])
        top += 22
    if multi:  # legend: line keys for lines, rounded squares for bars; wraps to more rows
        lx = pad
        for i, (name, _) in enumerate(chart.series):
            color = t["series"][i]
            item_w = 20 + _text_width(name, 12) + 18
            if lx > pad and lx + item_w > width - pad:
                lx = pad
                top += 20
            if chart.kind == "line":
                out.append(f'<line x1="{lx}" y1="{top + 8}" x2="{lx + 14}" y2="{top + 8}" stroke="{color}" '
                           'stroke-width="2" stroke-linecap="round"/>')
            else:
                out.append(f'<rect x="{lx + 2}" y="{top + 3}" width="10" height="10" rx="2" fill="{color}"/>')
            text(lx + 20, top + 12, name, 12, t["secondary"])
            lx += item_w
        top += 24
    top += 10

    # y scale: bars start at zero; lines get a padded range.
    values = [v for _, vals in chart.series for v in vals if v is not None]
    lo, hi = min(values), max(values)
    if chart.kind == "bar":
        lo, hi = min(lo, 0), max(hi, 0)
        hi += (hi - lo) * 0.08  # headroom for value labels
    else:
        span = (hi - lo) or abs(hi) * 0.1 or 1
        lo, hi = lo - span * 0.08, hi + span * 0.08
        if values and min(values) >= 0 and lo < 0:
            lo = 0
    ticks = nice_ticks(lo, hi)
    y0, y1 = ticks[0], ticks[-1]
    step = ticks[1] - ticks[0] if len(ticks) > 1 else 1
    tick_text = [format_tick(v, chart.y_kind, step) for v in ticks]

    # direct end labels for <= 4 line series, dropped if they would collide
    end_labels: list[tuple[float, str]] = []
    left = pad + max(_text_width(s, 11) for s in tick_text) + 10
    bottom = height - pad - 20
    right_pad = pad

    def ys(v: float) -> float:
        return bottom - (v - y0) / (y1 - y0) * (bottom - top)

    if chart.kind == "line" and len(chart.series) <= 4:
        candidates = []
        for name, vals in chart.series:
            last = next((v for v in reversed(vals) if v is not None), None)
            if last is not None:
                label = (f"{name} " if multi else "") + format_value(last, chart.y_kind)
                candidates.append((ys(last), label))
        ordered = sorted(y for y, _ in candidates)
        if all(b - a >= 15 for a, b in zip(ordered, ordered[1:])):
            end_labels = candidates
            right_pad = pad + 8 + max(_text_width(label, 11) for _, label in end_labels)
    right = width - right_pad

    # grid + y ticks
    for v, s in zip(ticks, tick_text):
        y = ys(v)
        stroke = t["axis"] if v == 0 else t["grid"]
        out.append(f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{right:.1f}" y2="{y:.1f}" stroke="{stroke}" '
                   'stroke-width="1" shape-rendering="crispEdges"/>')
        text(left - 8, y + 4, s, anchor="end")

    n = len(chart.categories)
    plot_w = right - left
    if chart.kind == "line":
        xs = [left + (i * plot_w / (n - 1) if n > 1 else plot_w / 2) for i in range(n)]
    else:
        band = plot_w / n
        xs = [left + band * (i + 0.5) for i in range(n)]

    # x tick labels, thinned to fit
    widest = max(_text_width(s, 11) for s in chart.tick_labels) + 12
    every = max(1, int(-(-n * widest // plot_w)))
    for i in range(0, n, every):
        anchor = "middle"
        if chart.kind == "line" and i == 0:
            anchor = "start"
        elif chart.kind == "line" and i == n - 1 and not end_labels:
            anchor = "end"
        text(xs[i], bottom + 16, chart.tick_labels[i], anchor=anchor)

    base = ys(max(y0, min(0, y1)))
    if chart.kind == "line":
        for si, (name, vals) in enumerate(chart.series):
            color = t["series"][si]
            segments, current = [], []
            for x, v in zip(xs, vals):
                if v is None:
                    if current:
                        segments.append(current)
                    current = []
                else:
                    current.append((x, ys(v)))
            if current:
                segments.append(current)
            for seg in segments:
                d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in seg)
                out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
                           'stroke-linejoin="round" stroke-linecap="round"/>')
            if segments:  # end dot with a surface ring
                x, y = segments[-1][-1]
                out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" stroke="{t["surface"]}" '
                           'stroke-width="2"/>')
        for y, label in end_labels:
            text(right + 8, y + 4, label, fill=t["secondary"])
    else:
        k = len(chart.series)
        band = plot_w / n
        group_w = min(band * 0.72, k * 24 + (k - 1) * 2)
        bar_w = min(24.0, (group_w - (k - 1) * 2) / k)
        group_w = k * bar_w + (k - 1) * 2
        # Value labels only where they fit over their own bar; otherwise hover/table carry them.
        room = band * 0.9 if k == 1 else bar_w + 4
        label_bars = n * k <= 16 and all(
            _text_width(format_value(v, chart.y_kind), 10) <= room
            for _, vals in chart.series for v in vals if v is not None)
        for ci, cx in enumerate(xs):
            for si, (name, vals) in enumerate(chart.series):
                v = vals[ci]
                if v is None:
                    continue
                x = cx - group_w / 2 + si * (bar_w + 2)
                yv = ys(v)
                h = abs(base - yv)
                r = min(4, bar_w / 2, h)
                if v >= 0:
                    d = (f"M{x:.1f},{base:.1f} V{yv + r:.1f} Q{x:.1f},{yv:.1f} {x + r:.1f},{yv:.1f} "
                         f"H{x + bar_w - r:.1f} Q{x + bar_w:.1f},{yv:.1f} {x + bar_w:.1f},{yv + r:.1f} V{base:.1f} Z")
                else:
                    d = (f"M{x:.1f},{base:.1f} V{yv - r:.1f} Q{x:.1f},{yv:.1f} {x + r:.1f},{yv:.1f} "
                         f"H{x + bar_w - r:.1f} Q{x + bar_w:.1f},{yv:.1f} {x + bar_w:.1f},{yv - r:.1f} V{base:.1f} Z")
                out.append(f'<path d="{d}" fill="{t["series"][si]}"/>')
                if label_bars:
                    ty = yv - 6 if v >= 0 else yv + 14
                    text(x + bar_w / 2, ty, format_value(v, chart.y_kind), 10, t["secondary"], "middle")

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" font-family="{escape(FONT)}" role="img" aria-label="{escape(chart.title)}">'
           f'<rect width="{width}" height="{height}" fill="{t["surface"]}"/>' + "".join(out) + "</svg>")
    return svg, Layout(width, height, left, right, top, bottom, xs)


def render_png(svg: str, scale: float = 2) -> bytes:
    return vl_convert.svg_to_png(svg, scale=scale)


def _variant(chart: ChartData, width: int, height: int) -> dict[str, Any]:
    light, layout = render_svg(chart, "light", width, height)
    dark, _ = render_svg(chart, "dark", width, height)
    return {
        "svg_light": light,
        "svg_dark": dark,
        "width": layout.width,
        "height": layout.height,
        "plot": {"left": layout.left, "right": layout.right, "top": layout.top, "bottom": layout.bottom},
        "x_positions": [round(x, 1) for x in layout.x_positions],
    }


def chart_payload(chart: ChartData) -> dict[str, Any]:
    """Everything the chat UI needs: light/dark SVGs for wide and narrow (phone) layouts, the
    hover geometry of each, and formatted values."""
    series = [
        {"name": name, "color_light": THEMES["light"]["series"][i], "color_dark": THEMES["dark"]["series"][i],
         "values": [format_value(v, chart.y_kind) for v in vals]}
        for i, (name, vals) in enumerate(chart.series)
    ]
    return {
        "kind": chart.kind,
        "title": chart.title,
        **_variant(chart, 800, 450),
        "narrow": _variant(chart, 420, 360),
        "x_labels": chart.full_labels,
        "series": series,
    }
