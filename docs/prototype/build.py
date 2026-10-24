"""Builds the UI/UX prototype screens (static HTML, sample figures) into this folder."""

from pathlib import Path

HERE = Path(__file__).parent

PATHS = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16v4z"/>',
    "pin": '<path d="M9 4h6l-1 6 4 3H6l4-3-1-6zM12 13v7"/>',
    "file": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "send": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "up": '<path d="M7 10v10H4V10zM7 10l4-7c2 0 3 1 3 3v3h5c1 0 2 1 2 2l-2 7c0 1-1 2-2 2H7"/>',
    "down": '<path d="M7 14V4H4v10zM7 14l4 7c2 0 3-1 3-3v-3h5c1 0 2-1 2-2l-2-7c0-1-1-2-2-2H7"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "xls": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m9 9 6 6M15 9l-6 6"/>',
    "pdf": '<path d="M7 3h7l5 5v13H7z"/><path d="M10 14h4M10 17h4"/>',
    "save": '<path d="M6 3h12v18l-6-4-6 4z"/>',
    "cal": '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    "expand": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "chev": '<path d="m9 6 6 6-6 6"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "bulb": '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10c1 1 1 2 1 3h6c0-1 0-2 1-3a6 6 0 0 0-4-10z"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2 6M20 5v6h-6"/>',
    "bars": '<path d="M5 20V10M12 20V4M19 20v-7"/>',
    "line": '<path d="m3 17 6-6 4 4 8-8"/>',
    "table": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M9 10v9"/>',
    "share": '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="m8 11 8-4M8 13l8 4"/>',
}


def ic(name, size=16, cls="ic"):
    return (f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>')


def spark(values, color="#2563eb", w=120, h=26):
    lo, hi = min(values), max(values)
    pts = " ".join(f"{i * w / (len(values) - 1):.1f},{h - 2 - (v - lo) / (hi - lo or 1) * (h - 4):.1f}"
                   for i, v in enumerate(values))
    return (f'<svg width="100%" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linejoin="round" '
            f'vector-effect="non-scaling-stroke"/></svg>')


def page(title, body, width=None):
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="proto.css">
{f'<style>body{{width:{width}px}}</style>' if width else ''}</head><body>{body}</body></html>"""


KPIS = [
    ("Ocupación hoy", "78.4%", "+6.1 pp vs 2025", "up", [61, 64, 70, 66, 72, 75, 71, 78]),
    ("Llegadas · Salidas", "14 · 9", "3 grupos hoy", "up", [9, 12, 8, 15, 11, 10, 13, 14]),
    ("ADR del mes", "COP 412k", "+8.2% vs 2025", "up", [380, 386, 392, 389, 401, 405, 409, 412]),
    ("RevPAR del mes", "COP 319k", "+12.5% vs 2025", "up", [270, 279, 284, 290, 301, 306, 312, 319]),
    ("Ingresos del mes", "COP 186 M", "84% de la meta", "up", [20, 44, 63, 85, 110, 132, 160, 186]),
    ("Reservado 30 días", "61.2%", "−4.3 pp vs 2025", "down", [70, 68, 66, 65, 64, 63, 62, 61]),
]

RECS = [
    ("Sube la tarifa de puente festivo (3–5 nov)", "money", "+COP 9.8 M estimados",
     "Ya estás al 92% para el puente y el pickup de los últimos 7 días es 2.3× el del año pasado. "
     "Sube la tarifa flexible un 12% en habitaciones dobles."),
    ("Reduce la dependencia de Booking.com", "risk", "Comisiones: COP 14.2 M/mes",
     "Booking.com trae el 58% de las noches y cancela el 27%. Activa una tarifa directa −8% con desayuno "
     "y empújala en la web y WhatsApp."),
    ("Llena los martes y miércoles de diciembre", "risk", "−18 pp vs 2025",
     "Entre semana en diciembre estás al 41%. Abre un paquete corporativo de 2 noches y una "
     "promoción para agencias locales."),
]


def kpi_strip(cols=6):
    out = [f'<div class="kpis" style="grid-template-columns:repeat({cols},1fr)">']
    for label, value, delta, kind, series in KPIS:
        color = "#15803d" if kind == "up" else "#b91c1c"
        out.append(f'<button class="kpi"><span class="l">{label}</span><span class="v">{value}</span>'
                   f'<span class="delta {kind}">{delta}</span>{spark(series, color)}</button>')
    out.append("</div>")
    return "".join(out)


def recs(compact=False, done_first=False):
    out = ['<div class="card">']
    for i, (title, kind, impact, detail) in enumerate(RECS, 1):
        out.append(f"""<div class="rec"><span class="num">{i}</span><div style="flex:1;min-width:0">
<div style="display:flex;gap:8px;align-items:baseline;flex-wrap:wrap"><b style="font-size:14.5px">{title}</b>
<span class="tag {kind}">{impact}</span></div>
<p style="font-size:13.5px;color:var(--ink2);margin-top:3px">{detail}</p>
<div class="ra"><button class="mini acc">{ic('chev', 13)}Ver el análisis</button>
{'' if compact else f'<button class="mini">{ic("check", 13)}Hecho</button>'}
<span class="sp"></span><button class="mini" title="Útil">{ic('up', 13)}</button>
<button class="mini" title="No útil">{ic('down', 13)}</button></div></div></div>""")
    out.append("</div>")
    return "".join(out)


def sidebar(new_user=False):
    if new_user:
        convs = f"""<div class="guide"><b>{ic('bulb', 15)} Qué puedo hacer por ti</b><ul>
<li>📊 Gráficos de ocupación, tarifas y canales</li><li>📈 Pronóstico de lo reservado</li>
<li>📗 Exportar a Excel, PowerPoint o PDF</li><li>⏰ Enviarte un reporte cada semana</li></ul></div>"""
    else:
        convs = f"""<div><div class="sec">Fijadas</div>
<div class="conv">{ic('pin', 14)}<span class="t">Pace de diciembre</span></div></div>
<div><div class="sec">Hoy</div>
<div class="conv cur"><span class="t">Ocupación y ADR vs año pasado</span><span class="m">09:12</span></div>
<div class="conv"><span class="t">Canales con más cancelaciones</span><span class="m">08:40</span></div></div>
<div><div class="sec">Ayer</div>
<div class="conv"><span class="t">Reporte semanal para gerencia</span></div>
<div class="conv"><span class="t">Tarifa promedio por tipo de habitación</span></div></div>
<div><div class="sec">Esta semana</div>
<div class="conv"><span class="t">Huéspedes que más repiten</span></div>
<div class="conv"><span class="t">Ingresos de alimentos y bebidas</span></div></div>"""
    return f"""<aside class="side">
<button class="primary" style="justify-content:center">{ic('plus', 15)}Nuevo chat</button>
<div class="search">{ic('search', 15)}Buscar conversaciones</div>
{convs}<div class="sp"></div>
<div><div class="sec">Reportes guardados</div>
<div class="conv">{ic('cal', 14)}<span class="t">KPI semanales · lunes 7:00</span></div>
<div class="conv">{ic('file', 14)}<span class="t">Producción por canal</span></div></div></aside>"""


def header():
    return f"""<header class="hdr"><div class="logo">HS</div><div class="brand">Hotel Super Intelligence</div>
<span style="width:10px"></span>
<button class="pill">🏨 Fragata <span class="car">▼</span></button>
<button class="pill">{ic('cal', 14)} Este mes <span class="car">▼</span></button>
<span class="sp"></span>
<button class="iconbtn" title="Alertas" style="position:relative">{ic('bell', 16)}
<span style="position:absolute;top:6px;right:7px;width:7px;height:7px;border-radius:50%;background:#ef4444"></span></button>
<button class="pill" style="padding:3px 10px 3px 3px"><span class="avatar">MC</span>Manuel <span class="car">▼</span></button>
</header>"""


def composer(mobile=False):
    hint = "" if mobile else (f'<div class="hint"><span><span class="kbd">Enter</span> enviar · '
                              f'<span class="kbd">Shift</span>+<span class="kbd">Enter</span> nueva línea</span>'
                              f'<span>Puedo crear gráficos, Excel, PowerPoint y PDF</span></div>')
    return f"""<div class="composer"><div class="box"><span class="ph">Pregunta sobre Fragata… p. ej. “¿cómo va diciembre?”</span>
<button class="iconbtn" style="border:0" title="Dictar">{ic('mic', 18)}</button>
<button class="send" title="Enviar">{ic('send', 18)}</button></div>{hint}</div>"""


QUESTIONS = [
    ("📈 Ocupación", "¿Cómo se comparan la ocupación, el ADR y el RevPAR de octubre con el año pasado?"),
    ("🌐 Canales", "¿Qué canales traen más ingresos y cuáles cancelan más?"),
    ("🔮 Pronóstico", "¿Qué tengo reservado para los próximos 30 días y cómo va el pickup?"),
    ("📊 Gráfico", "Gráfico de barras de la ocupación mensual con línea de tendencia"),
    ("📗 Excel", "Exporta a Excel la producción diaria de octubre por canal"),
    ("📑 Presentación", "Prepara una presentación de resultados del mes para la gerencia"),
]


def home(new_user=False):
    qs = "".join(f'<button class="q"><span class="k">{k}</span>{q}</button>' for k, q in QUESTIONS)
    cats = "".join(f'<button class="chip{" on" if i == 0 else ""}">{c}</button>' for i, c in
                   enumerate(["Todo", "Ocupación", "Tarifas", "Canales", "Reservas", "Pronóstico", "Documentos"]))
    body = f"""<div class="app">{sidebar(new_user)}<div class="main">{header()}<div class="scroll"><div class="wrap" style="display:flex;flex-direction:column;gap:22px">
<div style="display:flex;align-items:flex-end;gap:12px"><div><h1>Buenos días, Manuel</h1>
<p style="color:var(--mute);margin-top:2px">Así va Fragata hoy, viernes 24 de octubre.</p></div><span class="sp"></span>
<span class="fresh"><span class="dot"></span>Datos de FNS Rooms al 24 oct, 03:00</span></div>
{kpi_strip()}
<section><div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">{ic('spark', 17)}<h2>Recomendaciones del día</h2>
<span class="badge">IA</span><span class="sp"></span><span class="fresh">Actualizadas a las 03:15</span></div>{recs()}</section>
<section><div style="display:flex;align-items:center;gap:10px;margin-bottom:10px"><h2>¿Qué te gustaría saber?</h2></div>
<div class="chips" style="margin-bottom:10px">{cats}</div><div class="qgrid">{qs}</div></section>
</div></div>{composer()}</div></div>"""
    return page("Inicio", body, 1440)


CHART_OCC = [71, 66, 69, 58, 63, 72, 80, 83, 86, 88, 87, 78]
CHART_ADR = [352, 331, 338, 319, 327, 349, 371, 382, 398, 409, 405, 412]
MONTHS = ["nov", "dic", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct"]


def chart_svg(w=760, h=270):
    left, right, top, bottom = 44, 52, 14, 34
    pw, ph = w - left - right, h - top - bottom
    bw = pw / len(CHART_OCC)
    parts = [f'<svg width="100%" viewBox="0 0 {w} {h}" style="display:block">']
    for i in range(6):
        y = top + ph - i * ph / 5
        parts.append(f'<line x1="{left}" x2="{w - right}" y1="{y}" y2="{y}" stroke="#eeedeb"/>'
                     f'<text x="{left - 8}" y="{y + 4}" font-size="11" fill="#78716c" text-anchor="end">{i * 20}%</text>'
                     f'<text x="{w - right + 8}" y="{y + 4}" font-size="11" fill="#78716c">{i * 100}k</text>')
    pts = []
    for i, (o, a) in enumerate(zip(CHART_OCC, CHART_ADR)):
        x = left + i * bw + bw * 0.14
        bh = o / 100 * ph
        parts.append(f'<rect x="{x:.1f}" y="{top + ph - bh:.1f}" width="{bw * 0.72:.1f}" height="{bh:.1f}" rx="3" '
                     f'fill="{"#1d4ed8" if i == 11 else "#3b82f6"}"/>')
        parts.append(f'<text x="{x + bw * 0.36:.1f}" y="{h - 14}" font-size="11" fill="#78716c" text-anchor="middle">{MONTHS[i]}</text>')
        pts.append((left + i * bw + bw / 2, top + ph - a / 500 * ph))
    parts.append('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
                 + '" fill="none" stroke="#f97316" stroke-width="2.2"/>')
    parts += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#f97316"/>' for x, y in pts]
    y0, y1 = top + ph - 66 / 100 * ph, top + ph - 86 / 100 * ph
    parts.append(f'<line x1="{left + bw / 2}" y1="{y0}" x2="{w - right - bw / 2}" y2="{y1}" stroke="#78716c" '
                 'stroke-width="1.6" stroke-dasharray="5 4"/>')
    # Tooltip on October.
    tx = left + 11 * bw - 150
    parts.append(f'<g><rect x="{tx}" y="{top + 8}" width="150" height="62" rx="8" fill="#1c1917"/>'
                 f'<text x="{tx + 10}" y="{top + 26}" font-size="11.5" fill="#fff" font-weight="600">octubre 2026</text>'
                 f'<text x="{tx + 10}" y="{top + 44}" font-size="11.5" fill="#d6d3d1">Ocupación  78.4%</text>'
                 f'<text x="{tx + 10}" y="{top + 60}" font-size="11.5" fill="#d6d3d1">ADR  COP 412,300</text></g>')
    parts.append("</svg>")
    return "".join(parts)


def answer_block(mobile=False):
    rows = [("Ocupación", "78.4%", "72.3%", "+6.1 pp"), ("ADR", "COP 412,300", "COP 381,100", "+8.2%"),
            ("RevPAR", "COP 323,200", "COP 275,500", "+17.3%"), ("Ingresos habitaciones", "COP 186.4 M", "COP 158.9 M", "+17.3%")]
    trs = "".join(f'<tr><td>{a}</td><td>{b}</td><td>{c}</td><td style="color:var(--up);font-weight:600">{d}</td></tr>'
                  for a, b, c, d in rows)
    return f"""<div style="display:flex;flex-direction:column;gap:14px">
<p><b>Octubre va mejor que el año pasado en todo:</b> más ocupación (+6.1 pp) y una tarifa más alta (+8.2%), así que el RevPAR sube un 17%.</p>
<div class="card" style="padding:4px 6px"><table><thead><tr><th>Indicador</th><th>Oct 2026</th><th>Oct 2025</th><th>Variación</th></tr></thead><tbody>{trs}</tbody></table></div>
<p>El crecimiento viene sobre todo de los fines de semana (89% de ocupación). Entre semana sigues en 64%: ahí está la oportunidad.</p>
<div class="card" style="overflow:hidden"><div style="display:flex;align-items:flex-start;gap:10px;padding:12px 14px 0">
<div><b style="font-size:14.5px">Ocupación y ADR, últimos 12 meses</b><div style="font-size:12.5px;color:var(--mute)">Fragata · nov 2025 – oct 2026 · línea punteada: tendencia</div></div>
<span class="sp"></span><div class="seg"><span class="on">{ic('bars', 13)}</span><span>{ic('line', 13)}</span><span>{ic('table', 13)}</span></div>
<button class="iconbtn" style="width:28px;height:28px" title="Pantalla completa">{ic('expand', 14)}</button></div>
<div style="padding:4px 8px 0">{chart_svg()}</div>
<div style="display:flex;gap:14px;padding:6px 14px 10px;font-size:12px;color:var(--mute)">
<span><span style="display:inline-block;width:10px;height:10px;background:#3b82f6;border-radius:2px"></span> Ocupación</span>
<span><span style="display:inline-block;width:12px;height:2px;background:#f97316;vertical-align:3px"></span> ADR (eje derecho)</span>
<span class="sp"></span><span>Ver datos</span><span>Descargar PNG</span></div></div>
<button class="how">{ic('chev', 13)}Ver cómo lo calculé · 2 consultas a los datos de FNS</button>
<div class="actions"><button class="ab">{ic('copy', 14)}Copiar</button><button class="ab">{ic('xls', 14)}Excel</button>
<button class="ab">{ic('pdf', 14)}PDF</button><button class="ab">{ic('share', 14)}Compartir</button>
<button class="ab">{ic('save', 14)}Guardar como reporte</button><button class="ab">{ic('cal', 14)}Enviarme cada lunes</button>
<span class="sp"></span><button class="ab" title="Útil">{ic('up', 14)}</button><button class="ab" title="No útil">{ic('down', 14)}</button></div>
<div><div style="font-size:12.5px;color:var(--mute);font-weight:600;margin-bottom:6px">Sigue explorando</div><div class="next">
<button class="chip">Ver solo entre semana</button><button class="chip">Desglosar por canal</button>
<button class="chip">¿Qué tarifa me recomiendas para noviembre?</button><button class="chip">Compararlo con 2024</button></div></div></div>"""


def answer():
    body = f"""<div class="app">{sidebar()}<div class="main">{header()}<div class="scroll"><div class="wrap" style="display:flex;flex-direction:column;gap:18px">
<div class="user">¿Cómo se comparan la ocupación, el ADR y el RevPAR de octubre con el año pasado?</div>
{answer_block()}</div></div>{composer()}</div></div>"""
    return page("Respuesta", body, 1440)


def working():
    body = f"""<div class="app">{sidebar()}<div class="main">{header()}<div class="scroll"><div class="wrap" style="display:flex;flex-direction:column;gap:18px">
<div class="user">Prepara una presentación de resultados del mes para la gerencia</div>
<div class="card" style="padding:16px 18px;display:flex;flex-direction:column;gap:12px">
<div style="display:flex;align-items:center;gap:10px"><span class="spin"></span><b>Preparando tu presentación…</b>
<span class="sp"></span><span class="fresh">unos 40 segundos</span></div>
<div style="height:6px;background:#eef2ff;border-radius:99px;overflow:hidden"><div style="width:62%;height:100%;background:var(--accent);border-radius:99px"></div></div>
<div class="steps">
<div class="step"><span class="ok">{ic('check', 15)}</span>Revisé los KPI de octubre y de octubre de 2025</div>
<div class="step"><span class="ok">{ic('check', 15)}</span>Analicé la producción por canal y segmento</div>
<div class="step"><span class="spin" style="width:13px;height:13px"></span>Creando los gráficos de ocupación y RevPAR…</div>
<div class="step" style="color:#a8a29e"><span style="width:15px;text-align:center">○</span>Armando las diapositivas</div></div>
<div style="display:flex;gap:8px"><button class="ab">{ic('x', 14)}Detener</button></div></div>
</div></div>{composer()}</div></div>"""
    return page("Trabajando", body, 1440)


def mobile():
    kp = "".join(
        f'<div class="kpi" style="min-width:150px"><span class="l">{l}</span><span class="v" style="font-size:19px">{v}</span>'
        f'<span class="delta {k}">{d}</span>{spark(s, "#15803d" if k == "up" else "#b91c1c")}</div>'
        for l, v, d, k, s in KPIS)
    body = f"""<div style="height:100vh;display:flex;flex-direction:column">
<header class="hdr" style="padding:0 12px;gap:8px"><button class="iconbtn" style="border:0">{ic('menu', 20)}</button>
<div class="logo" style="width:30px;height:30px;font-size:13px">HS</div>
<button class="pill" style="padding:5px 9px">🏨 Fragata <span class="car">▼</span></button><span class="sp"></span>
<button class="iconbtn" title="Nuevo chat">{ic('edit', 17)}</button><span class="avatar">MC</span></header>
<div class="scroll"><div style="padding:16px;display:flex;flex-direction:column;gap:16px">
<div><h1 style="font-size:21px">Buenos días, Manuel</h1><span class="fresh"><span class="dot"></span>Datos al 24 oct, 03:00</span></div>
<div style="display:flex;gap:10px;overflow:hidden;margin-right:-16px">{kp}</div>
<section><div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">{ic('spark', 16)}<h2>Recomendaciones del día</h2></div>{recs(compact=True)}</section>
<section><h2 style="margin-bottom:8px">¿Qué te gustaría saber?</h2><div class="chips">
<button class="chip">📈 Ocupación vs 2025</button><button class="chip">🔮 Próximos 30 días</button><button class="chip">🌐 Canales</button><button class="chip">📗 Exportar a Excel</button></div></section>
</div></div>{composer(mobile=True)}</div>"""
    return page("Móvil", body, 390)


def email():
    kp = "".join(f'<td style="padding:6px;border:0"><div class="kpi"><span class="l">{l}</span><span class="v" style="font-size:18px">{v}</span>'
                 f'<span class="delta {k}">{d}</span></div></td>' for l, v, d, k, _ in KPIS[:3])
    kp2 = "".join(f'<td style="padding:6px;border:0"><div class="kpi"><span class="l">{l}</span><span class="v" style="font-size:18px">{v}</span>'
                  f'<span class="delta {k}">{d}</span></div></td>' for l, v, d, k, _ in KPIS[3:])
    items = "".join(f'<div style="display:flex;gap:10px;padding:10px 0;border-top:1px solid var(--line2)"><span class="num">{i}</span>'
                    f'<div><b>{t}</b> <span class="tag {k}">{m}</span><p style="font-size:13.5px;color:var(--ink2)">{d}</p></div></div>'
                    for i, (t, k, m, d) in enumerate(RECS, 1))
    body = f"""<div style="background:#eceae7;padding:28px 0;min-height:100vh"><div style="width:640px;margin:0 auto">
<div style="font-size:12.5px;color:var(--mute);margin-bottom:8px">De: Hotel Super Intelligence · Para: Manuel · 07:00<br>
<b style="color:var(--ink);font-size:14px">☀️ Fragata hoy: 78% de ocupación y 3 recomendaciones</b></div>
<div class="card" style="padding:24px 26px">
<div style="display:flex;align-items:center;gap:10px;margin-bottom:16px"><div class="logo">HS</div><b>Hotel Super Intelligence</b></div>
<h1 style="font-size:21px">Buenos días, Manuel</h1><p style="color:var(--mute);margin:2px 0 12px">Resumen de Fragata para el viernes 24 de octubre.</p>
<table style="margin:0 -6px;width:calc(100% + 12px);table-layout:fixed"><tr>{kp}</tr><tr>{kp2}</tr></table>
<div style="margin:16px 0 6px;padding:10px 12px;background:var(--down-soft);border-radius:10px;font-size:13.5px;color:#7f1d1d">
{ic('bell', 15)} <b>Alerta:</b> el pickup de diciembre bajó 20% esta semana frente a la anterior.</div>
<h2 style="margin:18px 0 4px">Recomendaciones del día</h2>{items}
<div style="text-align:center;margin-top:18px"><span class="primary" style="padding:11px 20px">Abrir Hotel Super Intelligence</span></div>
<p style="font-size:11.5px;color:var(--mute);text-align:center;margin-top:16px">Recibes este correo cada mañana · Cambiar frecuencia · Dejar de recibirlo</p>
</div></div></div>"""
    return page("Correo diario", body, 760)


if __name__ == "__main__":
    for name, html in {"01-inicio": home(), "02-respuesta": answer(), "03-trabajando": working(),
                       "04-movil": mobile(), "05-correo-diario": email(), "06-usuario-nuevo": home(new_user=True)}.items():
        (HERE / f"{name}.html").write_text(html)
