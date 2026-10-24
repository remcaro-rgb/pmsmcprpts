"""Charts as Vega-Lite specs (https://vega.github.io/vega-lite/), drawn from stored datasets.

make_chart builds the spec from a chart type (line, bar, stacked or horizontal bar, area,
scatter, pie, donut, heatmap, histogram, box plot) with optional trend lines and a second measure
on its own axis, or takes a full Vega-Lite spec for anything else. The data always comes from the
dataset: specs may not carry data or load anything from a URL. The same spec is rendered as a PNG
here (vl-convert, for documents and downloads) and interactively in the website (vega-embed).

Styling follows the reference data-viz specs: validated categorical palette in fixed slot order,
2px lines, bars with rounded data ends, hairline horizontal grid, legend for >= 2 series.
"""

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Literal

import vl_convert

from .datasets import Dataset
from .documents import pretty
from .formats import Kind, currency_prefix, date_labels, format_value, infer_kind
from .i18n import Lang

CHART_TYPES = ("line", "bar", "stacked_bar", "horizontal_bar", "area", "stacked_area", "scatter", "pie",
               "donut", "heatmap", "histogram", "boxplot")
ChartType = Literal["line", "bar", "stacked_bar", "horizontal_bar", "area", "stacked_area", "scatter", "pie",
                    "donut", "heatmap", "histogram", "boxplot"]
Trend = Literal["linear", "moving_average"]
MAX_SERIES = 12
MAX_ROWS = 5000
TABLE_ROWS = 500
VL_VERSION = "6.4"
# Sizes for the PNG (documents, downloads); the website fits the chart to its column.
PNG_WIDTH, PNG_HEIGHT = 720, 340

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "secondary": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948",
                   "#5aa1e8", "#b85a1f", "#7fc8a9", "#8c6d1f"],
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "secondary": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767",
                   "#6fb0f0", "#c46a2f", "#5fb894", "#a8873a"],
    },
}
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
# Numbers read 1,234.5 in both languages (see the agent's language rules).
TIME_LOCALES = {"en": "en-US", "es": "es-MX"}
# Keys a spec may not contain anywhere: data comes from the dataset, nothing loads from the network.
FORBIDDEN_KEYS = {"data", "datasets", "url", "href", "image", "usermeta", "$schema"}


class ChartError(ValueError):
    pass


@dataclass
class Chart:
    spec: dict[str, Any]   # Vega-Lite spec without data, size or theme
    rows: list[dict[str, Any]]
    title: str
    lang: Lang
    currency: str
    table: dict[str, Any] = field(default_factory=dict)
    series: list[str] = field(default_factory=list)


def theme_config(theme: str) -> dict[str, Any]:
    t = THEMES[theme]
    axis = {"labelColor": t["muted"], "titleColor": t["secondary"], "gridColor": t["grid"], "domainColor": t["axis"],
            "tickColor": t["axis"], "labelFontSize": 11, "titleFontSize": 11, "titleFontWeight": 400,
            "labelFont": FONT, "titleFont": FONT}
    return {
        "background": t["surface"], "font": FONT, "padding": 12,
        "title": {"color": t["ink"], "fontSize": 16, "fontWeight": 600, "anchor": "start", "font": FONT,
                  "subtitleColor": t["secondary"], "subtitleFontSize": 12, "subtitleFont": FONT, "offset": 14},
        "axis": axis, "axisX": {"grid": False}, "axisY": {"domain": False, "ticks": False},
        "legend": {"labelColor": t["secondary"], "titleColor": t["secondary"], "labelFontSize": 12,
                   "titleFontSize": 12, "orient": "top", "labelFont": FONT, "titleFont": FONT, "symbolSize": 80},
        "header": {"labelColor": t["secondary"], "titleColor": t["secondary"]},
        "range": {"category": t["series"], "ramp": {"scheme": "blues"}},
        "view": {"stroke": None},
        "mark": {"color": t["series"][0]},
        "line": {"strokeWidth": 2, "strokeCap": "round", "strokeJoin": "round", "color": t["series"][0]},
        "bar": {"cornerRadiusEnd": 3, "color": t["series"][0]},
        "area": {"color": t["series"][0]},
        "rect": {"color": t["series"][0]},
        "boxplot": {"color": t["series"][0]},
        "point": {"filled": True, "size": 40, "color": t["series"][0]},
        "arc": {"stroke": t["surface"], "strokeWidth": 1},
        "text": {"color": t["secondary"], "font": FONT},
        "rule": {"color": t["muted"]},
    }


def format_locale(currency: str) -> dict[str, Any]:
    return {"decimal": ".", "thousands": ",", "grouping": [3], "currency": [currency_prefix(currency), ""]}


def time_locale(lang: Lang) -> dict[str, Any]:
    return vl_convert.get_time_format_locale(TIME_LOCALES[lang])


def d3_format(kind: Kind, axis: bool = False) -> str | None:
    return {"percent": ".0%" if axis else ".1%", "points": "+.1%", "currency": "$,.0f" if axis else "$,.2f",
            "integer": ",.0f", "decimal": ",.0f" if axis else ",.2f"}.get(kind)


# --- the data -------------------------------------------------------------------------------------

def _rows(ds: Dataset, kinds: dict[str, Kind]) -> list[dict[str, Any]]:
    if len(ds.rows) > MAX_ROWS:
        raise ChartError(f"{len(ds.rows)} rows is too many to chart (max {MAX_ROWS}); aggregate in SQL first.")
    names = [c["name"] for c in ds.columns]
    out = []
    for r in ds.rows:
        row = {}
        for n, v in zip(names, r):
            # Dates as local midnight, so they fall on the same day in every time zone.
            row[n] = f"{v}T00:00:00" if kinds.get(n) == "date" and isinstance(v, str) and len(v) == 10 else v
        out.append(row)
    return out


def _kinds(ds: Dataset) -> dict[str, Kind]:
    return {c["name"]: infer_kind(c["name"], c["type"], [r[i] for r in ds.rows]) for i, c in enumerate(ds.columns)}


def _column(ds: Dataset, name: str | None, what: str) -> None:
    names = [c["name"] for c in ds.columns]
    if name is not None and name not in names:
        raise ChartError(f"Column {name!r} ({what}) is not in dataset {ds.id}. Columns: {names}")


def _table(ds: Dataset, kinds: dict[str, Kind], columns: list[str], lang: Lang, currency: str,
           x: str | None = None, series: str | None = None, y: str | None = None) -> dict[str, Any]:
    """The 'Show data' table: x by series when the chart has both, else the columns it uses."""
    names = [c["name"] for c in ds.columns]

    def fmt(col: str, values: list[Any]) -> list[str]:
        if kinds[col] == "date":
            return date_labels([str(v) for v in values], lang)[1]
        return [format_value(v, kinds[col], lang, currency) for v in values]

    if x and series and y:
        xi, si, yi = names.index(x), names.index(series), names.index(y)
        cats: list[Any] = list(dict.fromkeys(r[xi] for r in ds.rows))
        groups: list[str] = list(dict.fromkeys(str(r[si]) for r in ds.rows))
        cells = {(r[xi], str(r[si])): r[yi] for r in ds.rows}
        labels = fmt(x, cats)
        rows = [[labels[i]] + [format_value(cells.get((c, g)), kinds[y], lang, currency) for g in groups]
                for i, c in enumerate(cats)]
        return {"columns": [pretty(x, lang)] + groups, "rows": rows[:TABLE_ROWS], "numeric": [False] + [True] * len(groups)}
    cols = [c for c in dict.fromkeys(columns) if c in names]
    by_col = {c: fmt(c, [r[names.index(c)] for r in ds.rows]) for c in cols}
    rows = [[by_col[c][i] for c in cols] for i in range(min(len(ds.rows), TABLE_ROWS))]
    numeric = [kinds[c] in ("percent", "points", "currency", "integer", "decimal") for c in cols]
    return {"columns": [pretty(c, lang) for c in cols], "rows": rows, "numeric": numeric}


# --- chart types ----------------------------------------------------------------------------------

def _field(ds: Dataset, kinds: dict[str, Kind], name: str, lang: Lang, *, axis_title: str | None = None,
           role: str = "measure") -> dict[str, Any]:
    kind = kinds[name]
    title = axis_title if axis_title is not None else pretty(name, lang)
    if kind == "date":
        monthly = _monthly(ds, name)
        return {"field": name, "type": "temporal", "title": title,
                "timeUnit": "yearmonth" if monthly else "yearmonthdate",
                "axis": {"format": "%b %Y" if monthly else "%d %b", "labelOverlap": True}}
    if role == "category" or kind == "text":
        return {"field": name, "type": "nominal", "title": title, "sort": None}
    fmt = d3_format(kind, axis=True)
    return {"field": name, "type": "quantitative", "title": title, **({"axis": {"format": fmt}} if fmt else {})}


def _monthly(ds: Dataset, name: str) -> bool:
    i = [c["name"] for c in ds.columns].index(name)
    return all(isinstance(r[i], str) and r[i][8:10] == "01" for r in ds.rows if r[i])


def _tooltip(ds: Dataset, kinds: dict[str, Kind], fields: list[str], lang: Lang) -> list[dict[str, Any]]:
    tips = []
    for f in dict.fromkeys(f for f in fields if f):
        kind = kinds[f]
        tip: dict[str, Any] = {"field": f, "title": pretty(f, lang)}
        if kind == "date":
            tip.update(type="temporal", format="%B %Y" if _monthly(ds, f) else "%-d %b %Y")
        elif kind == "text":
            tip["type"] = "nominal"
        else:
            tip.update(type="quantitative", **({"format": d3_format(kind)} if d3_format(kind) else {}))
        tips.append(tip)
    return tips


def build_chart(ds: Dataset, chart_type: str, title: str, x: str | None = None, y: str | None = None,
                series: str | None = None, subtitle: str | None = None, y_format: Kind | None = None,
                lang: Lang = "en", currency: str = "EUR", trend: str | None = None, trend_window: int = 3,
                y2: str | None = None, y2_type: str = "line", y2_format: Kind | None = None) -> Chart:
    if chart_type not in CHART_TYPES:
        raise ChartError(f"chart_type must be one of {', '.join(CHART_TYPES)}, or pass a Vega-Lite spec.")
    for name, what in ((x, "x"), (y, "y"), (series, "series"), (y2, "y2")):
        _column(ds, name, what)
    if not ds.rows:
        raise ChartError("The dataset is empty.")
    if x is None:
        raise ChartError("Pass x (the column for the x-axis, or the categories of a pie chart).")
    if y is None and chart_type != "histogram":
        raise ChartError("Pass y (the numeric column to plot).")
    kinds = _kinds(ds)
    if y_format and y:
        kinds[y] = y_format
    if y2_format and y2:
        kinds[y2] = y2_format
    names = [c["name"] for c in ds.columns]
    numeric_cols = [y, y2] + ([x] if chart_type in ("scatter", "histogram") else [])
    for col in filter(None, numeric_cols):
        i = names.index(col)
        if any(r[i] is not None and not isinstance(r[i], (int, float)) for r in ds.rows):
            raise ChartError(f"Column {col!r} is not numeric; it must hold numbers to be plotted.")
        if all(r[i] is None for r in ds.rows):
            raise ChartError(f"Column {col!r} has no values to plot (all NULL).")
    groups = list(dict.fromkeys(str(r[names.index(series)]) for r in ds.rows)) if series else []
    if len(groups) > MAX_SERIES:
        raise ChartError(f"{len(groups)} series is too many to tell apart (max {MAX_SERIES}). Filter to fewer "
                         "values, fold the rest into 'Other' in SQL, or chart without a series column.")

    color = {"field": series, "type": "nominal", "title": pretty(series, lang), "sort": None} if series else None
    tip = _tooltip(ds, kinds, [x, series, y, y2], lang)
    enc: dict[str, Any] = {}
    layers: list[dict[str, Any]] = []
    stack = None

    if chart_type in ("line", "area", "stacked_area", "bar", "stacked_bar"):
        enc = {"x": _field(ds, kinds, x, lang, role="category" if kinds[x] != "date" else "measure"),
               "y": _field(ds, kinds, y, lang), "tooltip": tip}
        if color:
            enc["color"] = color
        if chart_type == "line":
            mark = {"type": "line", "point": {"size": 30}}
        elif chart_type in ("area", "stacked_area"):
            mark = {"type": "area", "opacity": 0.85 if chart_type == "stacked_area" else 0.35, "line": True}
            stack = "zero" if chart_type == "stacked_area" else None
            enc["y"]["stack"] = stack
        else:
            mark = {"type": "bar"}
            if chart_type == "bar" and color:
                enc["xOffset"] = {"field": series, "sort": None}
            if chart_type == "bar":
                enc["y"]["stack"] = None
            if kinds[x] == "date":  # bars per period, not on a continuous time scale; short labels
                enc["x"] = {**enc["x"], "type": "ordinal",
                            "axis": {"format": "%b %y" if _monthly(ds, x) else "%-d %b", "labelOverlap": "greedy",
                                     "labelAngle": 0}}
        layers.append({"mark": mark, "encoding": enc})
    elif chart_type == "horizontal_bar":
        enc = {"y": {**_field(ds, kinds, x, lang, role="category"), "sort": "-x"},
               "x": _field(ds, kinds, y, lang), "tooltip": tip}
        if color:
            enc["color"] = color
        layers.append({"mark": {"type": "bar"}, "encoding": enc})
    elif chart_type == "scatter":
        enc = {"x": {**_field(ds, kinds, x, lang), "scale": {"zero": False}},
               "y": {**_field(ds, kinds, y, lang), "scale": {"zero": False}}, "tooltip": tip}
        if color:
            enc["color"] = color
        layers.append({"mark": {"type": "point", "size": 60, "opacity": 0.8}, "encoding": enc})
    elif chart_type in ("pie", "donut"):
        enc = {"theta": {"field": y, "type": "quantitative", "stack": True},
               "color": {"field": x, "type": "nominal", "title": pretty(x, lang), "sort": None}, "tooltip": tip}
        mark = {"type": "arc", **({"innerRadius": 70} if chart_type == "donut" else {})}
        layers.append({"mark": mark, "encoding": enc})
    elif chart_type == "heatmap":
        if not series:
            raise ChartError("A heatmap needs x (columns), series (rows) and y (the value that sets the color).")
        enc = {"x": _field(ds, kinds, x, lang, role="category"),
               "y": {"field": series, "type": "nominal", "title": pretty(series, lang), "sort": None},
               "color": {"field": y, "type": "quantitative", "title": pretty(y, lang),
                         **({"legend": {"format": d3_format(kinds[y], True)}} if d3_format(kinds[y]) else {})},
               "tooltip": tip}
        if kinds[x] == "date":
            enc["x"] = {**_field(ds, kinds, x, lang), "type": "ordinal"}
        layers.append({"mark": {"type": "rect", "cornerRadius": 2}, "encoding": enc})
    elif chart_type == "histogram":
        enc = {"x": {"field": x, "type": "quantitative", "bin": {"maxbins": 30}, "title": pretty(x, lang)},
               "y": {"aggregate": "count", "type": "quantitative", "title": "Count" if lang == "en" else "Cantidad"}}
        if color:
            enc["color"] = color
        layers.append({"mark": {"type": "bar"}, "encoding": enc})
    elif chart_type == "boxplot":
        enc = {"x": _field(ds, kinds, x, lang, role="category"), "y": _field(ds, kinds, y, lang)}
        if color:
            enc["color"] = color
        layers.append({"mark": {"type": "boxplot", "extent": 1.5}, "encoding": enc})

    if trend:
        if chart_type not in ("line", "bar", "stacked_bar", "area", "scatter"):
            raise ChartError("Trend lines go on line, bar, area and scatter charts.")
        layers.append(_trend(enc, x, y, series if chart_type != "stacked_bar" else None, trend, trend_window,
                             kinds, lang))
    if y2:
        if chart_type not in ("line", "bar", "stacked_bar", "area"):
            raise ChartError("A second measure (y2) goes on line, bar and area charts.")
        y2_enc = {"x": enc["x"], "y": _field(ds, kinds, y2, lang), "tooltip": tip}
        y2_color = THEMES["light"]["series"][1]
        y2_mark = {"type": "line", "point": {"size": 30, "color": y2_color}, "color": y2_color} \
            if y2_type == "line" else {"type": "bar", "opacity": 0.5}
        layers.append({"mark": y2_mark, "encoding": y2_enc})

    spec: dict[str, Any] = {"title": {"text": title, **({"subtitle": subtitle} if subtitle else {})}}
    if y2:
        # The chart (and its trend) on the left axis, the second measure on the right.
        main = layers[:-1]
        spec["layer"] = [main[0] if len(main) == 1 else {"layer": main}, layers[-1]]
        spec["resolve"] = {"scale": {"y": "independent"}}
    elif len(layers) == 1:
        spec.update(layers[0])
    else:
        spec["layer"] = layers
    table = _table(ds, kinds, [x, series, y, y2], lang, currency,
                   x if chart_type not in ("scatter", "histogram") else None, series, y)
    return Chart(spec=spec, rows=_rows(ds, kinds), title=title, lang=lang, currency=currency, table=table,
                 series=groups)


def _trend(enc: dict[str, Any], x: str, y: str, series: str | None, trend: str, window: int,
           kinds: dict[str, Kind], lang: Lang) -> dict[str, Any]:
    """A dashed trend line on the same x as the chart (dates, periods or categories): a least-squares
    line over the points in x order (over x itself on scatter charts), or a moving average."""
    group = {"groupby": [series]} if series else {}
    by_x = [{"filter": f"isValid(datum[{json.dumps(y)}])"},
            {"window": [{"op": "row_number", "as": "_i"}], "sort": [{"field": x}], **group}]
    if trend == "moving_average":
        transform = by_x + [{"window": [{"op": "mean", "field": y, "as": "_trend"}], "frame": [-(window - 1), 0],
                             "sort": [{"field": x}], **group}]
        label = f"{window}-period average" if lang == "en" else f"Promedio de {window} períodos"
    else:
        i = f"datum[{json.dumps(x)}]" if kinds[x] not in ("date", "text") else "datum._i"
        yv = f"datum[{json.dumps(y)}]"
        transform = by_x + [
            {"calculate": i, "as": "_x"},
            {"joinaggregate": [{"op": "mean", "field": "_x", "as": "_mx"}, {"op": "mean", "field": y, "as": "_my"}],
             **group},
            {"calculate": f"(datum._x - datum._mx) * ({yv} - datum._my)", "as": "_sxy"},
            {"calculate": "(datum._x - datum._mx) * (datum._x - datum._mx)", "as": "_sxx"},
            {"joinaggregate": [{"op": "sum", "field": "_sxy", "as": "_Sxy"}, {"op": "sum", "field": "_sxx", "as": "_Sxx"}],
             **group},
            {"calculate": "datum._my + (datum._Sxx ? datum._Sxy / datum._Sxx : 0) * (datum._x - datum._mx)",
             "as": "_trend"},
        ]
        label = "Trend" if lang == "en" else "Tendencia"
    # On the measure's own axis (same title and format, so the axes merge).
    same_axis = {k: v for k, v in enc["y"].items() if k in ("title", "axis")}
    layer_enc: dict[str, Any] = {"x": enc["x"], "y": {"field": "_trend", "type": "quantitative", **same_axis}}
    if "xOffset" in enc:
        layer_enc["xOffset"] = enc["xOffset"]
    if series:
        layer_enc["color"] = {"field": series, "type": "nominal", "sort": None}
        layer_enc["detail"] = {"field": series}
    mark = {"type": "line", "strokeDash": [6, 4], "strokeWidth": 2, "opacity": 0.9,
            **({} if series else {"color": THEMES["light"]["muted"]})}  # the same grey in both themes
    tip = [{"field": "_trend", "type": "quantitative", "title": label,
            **({"format": d3_format(kinds[y])} if d3_format(kinds[y]) else {})}]
    return {"transform": transform, "mark": mark, "encoding": {**layer_enc, "tooltip": tip}}


# --- a full spec ----------------------------------------------------------------------------------

def _walk(node: Any, path: str = "") -> Any:
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, k, v
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def _defined_fields(spec: dict[str, Any]) -> set[str]:
    """Field names transforms create ("as", regression/loess/fold outputs...)."""
    out: set[str] = set()
    for _, k, v in _walk(spec):
        if k == "as":
            out.update([v] if isinstance(v, str) else [a for a in v if isinstance(a, str)] if isinstance(v, list) else [])
        elif k in ("regression", "loess", "density", "quantile") and isinstance(v, str):
            out.update({v, "value", "prob", "density"})
        elif k == "fold":
            out.update({"key", "value"})
        elif k == "pivot" and isinstance(v, str):
            out.add("*")  # pivot creates a column per value
    return out


def build_custom(ds: Dataset, spec: dict[str, Any], title: str, subtitle: str | None = None,
                 lang: Lang = "en", currency: str = "EUR") -> Chart:
    if not isinstance(spec, dict) or not spec:
        raise ChartError("spec must be a Vega-Lite specification (a JSON object).")
    spec = copy.deepcopy(spec)
    spec.pop("$schema", None)
    for path, k, _ in _walk(spec):
        if k in FORBIDDEN_KEYS:
            where = f"{path}.{k}" if path else k
            raise ChartError(f"The spec may not contain {where!r}: the data comes from dataset {ds.id} "
                             "and charts can't load anything from the network.")
    if not ds.rows:
        raise ChartError("The dataset is empty.")
    columns = {c["name"] for c in ds.columns}
    defined = _defined_fields(spec)
    for _, k, v in _walk(spec):
        if k == "field" and isinstance(v, str) and v not in columns and v not in defined and "*" not in defined:
            raise ChartError(f"Field {v!r} is not a column of dataset {ds.id} (columns: {sorted(columns)}) "
                             "or a field a transform creates.")
    kinds = _kinds(ds)
    if "title" not in spec:
        spec["title"] = {"text": title, **({"subtitle": subtitle} if subtitle else {})}
    used = [v for _, k, v in _walk(spec) if k == "field" and isinstance(v, str) and v in columns]
    chart = Chart(spec=spec, rows=_rows(ds, kinds), title=title, lang=lang, currency=currency,
                  table=_table(ds, kinds, used or [c["name"] for c in ds.columns], lang, currency))
    render_png(chart, scale=1)  # compile now, so mistakes come back as errors
    return chart


# --- output ---------------------------------------------------------------------------------------

def _composite(spec: dict[str, Any]) -> bool:
    return any(k in spec for k in ("facet", "repeat", "concat", "hconcat", "vconcat")) or "facet" in spec.get(
        "encoding", {}) or "row" in spec.get("encoding", {}) or "column" in spec.get("encoding", {})


def full_spec(chart: Chart, theme: str = "light", width: Any = PNG_WIDTH, height: int = PNG_HEIGHT) -> dict[str, Any]:
    spec = {**chart.spec, "data": {"values": chart.rows}, "config": theme_config(theme)}
    if not _composite(spec):
        spec.setdefault("width", width)
        spec.setdefault("height", height)
    return spec


def render_png(chart: Chart, scale: float = 2) -> bytes:
    try:
        return vl_convert.vegalite_to_png(full_spec(chart), vl_version=VL_VERSION, scale=scale,
                                          format_locale=format_locale(chart.currency),
                                          time_format_locale=time_locale(chart.lang), allowed_base_urls=[])
    except Exception as e:  # vl-convert reports spec errors as plain exceptions
        reason = " ".join(str(e).split()).replace("Vega-Lite to PNG conversion failed: ", "").split(" at ")[0]
        raise ChartError(f"The chart could not be drawn (check the Vega-Lite spec): {reason[:400]}") from e


# The types a chart can switch between on the website, by the type it was made as.
SWITCHABLE = {
    "line": ("bar", "line", "area"), "bar": ("bar", "line", "area"), "area": ("bar", "line", "area"),
    "stacked_bar": ("stacked_bar", "line", "stacked_area"), "stacked_area": ("stacked_bar", "line", "stacked_area"),
}


def _sized(spec: dict[str, Any]) -> dict[str, Any]:
    if not _composite(spec):
        spec.setdefault("width", "container")
        spec.setdefault("height", 300)
        spec.setdefault("autosize", {"type": "fit-x", "contains": "padding"})
    return spec


def chart_variants(chart_type: str, build) -> dict[str, dict[str, Any]]:
    """The same chart as the other types it can switch to (specs without data: the website adds the
    chart's data). `build(type)` makes the chart as that type."""
    out = {}
    for other in SWITCHABLE.get(chart_type, ()):
        if other == chart_type:
            continue
        try:
            out[other] = json.loads(json.dumps(_sized({**build(other).spec}), default=str))
        except ChartError:
            continue
    return out


def chart_payload(chart: Chart, chart_type: str | None = None,
                  variants: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Everything the website needs to draw the chart interactively: the spec with its data, the
    light and dark themes, number and date locales, the 'Show data' table, and the other types it
    can be shown as."""
    spec = _sized({**chart.spec, "data": {"values": chart.rows}})
    return {
        "kind": "vega-lite",
        "title": chart.title,
        "spec": json.loads(json.dumps(spec, default=str)),
        "config": {"light": theme_config("light"), "dark": theme_config("dark")},
        "locale": {"number": format_locale(chart.currency), "time": time_locale(chart.lang)},
        "table": chart.table,
        **({"type": chart_type, "variants": variants} if chart_type and variants else {}),
    }
