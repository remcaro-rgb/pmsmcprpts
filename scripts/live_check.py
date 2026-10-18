"""Ask the agent a fixed set of questions in English and Spanish, against the real Claude API, and
report each answer's tool calls, files and token usage with its cost.

Run it against a running stack (docker compose up -d, with ANTHROPIC_API_KEY in .env):

    python scripts/live_check.py                     # the agent's model (PMS_CLAUDE_MODEL)
    python scripts/live_check.py --langs es --only kpis,followup

To compare models, restart the agent with another model and run it again:

    PMS_CLAUDE_MODEL=claude-sonnet-5-5 docker compose up -d agent

Standard library only. Answers, tool calls, usage and generated files go to --out
(default live-check/<model>-<time>/); summary.md there has the table.
"""

import argparse
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# The second message of each pair is sent in the same conversation as the first.
QUESTIONS = {
    "en": [
        ("kpis", "How did occupancy, ADR and RevPAR compare across the three hotels last quarter?"),
        ("followup", "And how did that compare with the same quarter last year?"),
        ("channels", "Which booking channels have the highest cancellation rates over the last 12 months?"),
        ("chart", "Chart monthly occupancy by hotel for the last 12 months."),
        ("xlsx", "Make a KPI spreadsheet with monthly occupancy, ADR, RevPAR and total revenue by hotel "
                 "for the last 12 months."),
        ("deck", "Build a short PowerPoint deck on Q3 2026 performance across the three hotels."),
        ("pdf", "Write a PDF report on Q3 2026 performance by hotel, with a chart and a KPI table."),
    ],
    "es": [
        ("kpis", "¿Cómo se compararon la ocupación, la ADR y el RevPAR de los tres hoteles el trimestre pasado?"),
        ("followup", "¿Y cómo se compara eso con el mismo trimestre del año anterior?"),
        ("channels", "¿Qué canales de reserva tienen las tasas de cancelación más altas en los últimos 12 meses?"),
        ("chart", "Haz un gráfico de la ocupación mensual por hotel de los últimos 12 meses."),
        ("xlsx", "Crea una hoja de cálculo de KPI con la ocupación, la ADR, el RevPAR y los ingresos totales "
                 "mensuales por hotel de los últimos 12 meses."),
        ("deck", "Prepara una presentación de PowerPoint breve sobre el desempeño del T3 2026 de los tres hoteles."),
        ("pdf", "Escribe un informe en PDF sobre el desempeño del T3 2026 por hotel, con un gráfico y una tabla de KPI."),
    ],
}
FOLLOWS = {"followup": "kpis"}

# USD per million tokens: input, output, cache read, cache write (5-minute TTL, 1.25x input).
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
}


def cost(model: str, u: dict) -> float | None:
    p = PRICES.get(re.sub(r"-\d{8}$", "", model or ""))
    if not p:
        return None
    return (u["input_tokens"] * p[0] + u["output_tokens"] * p[1]
            + (u.get("cache_read_input_tokens") or 0) * p[2]
            + (u.get("cache_creation_input_tokens") or 0) * p[3]) / 1e6


def fmt_cost(c: float | None) -> str:
    return "" if c is None else f"{c:.4f}"


def ask(base: str, message: str, lang: str, conversation_id: str | None) -> dict:
    body = {"message": message, "language": lang}
    if conversation_id:
        body["conversation_id"] = conversation_id
    req = urllib.request.Request(f"{base}/api/chat", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    out = {"text": "", "tools": [], "files": [], "events": []}
    started = time.monotonic()
    new_block = False
    with urllib.request.urlopen(req, timeout=900) as resp:
        event = None
        for raw in resp:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event:
                data = json.loads(line[6:])
                if event == "tool_start":
                    new_block = True
                if event not in ("text", "thinking", "tool_start"):
                    out["events"].append({"event": event, "data": data})
                if event == "conversation":
                    out["conversation_id"] = data["id"]
                elif event == "text":
                    # Text from separate steps (before and after a tool call) is separate blocks.
                    if out["text"] and new_block:
                        out["text"] += "\n\n"
                    out["text"] += data["text"]
                    new_block = False
                elif event == "tool_call":
                    out["tools"].append({"name": data["name"], "input": data["input"]})
                elif event == "tool_result":
                    result = data.get("result")
                    if isinstance(result, dict) and result.get("file"):
                        out["files"].append(result["file"])
                    if data.get("is_error"):
                        out["tools"].append({"name": data["name"], "error": result})
                elif event in ("done", "error", "refusal"):
                    out[event] = data
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", default="http://localhost:7001", help="Agent API base URL")
    ap.add_argument("--langs", default="en,es")
    ap.add_argument("--only", help="Comma-separated question keys (default: all)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    health = json.load(urllib.request.urlopen(f"{args.agent}/api/health"))
    model = health.get("model", "unknown")
    out = args.out or Path("live-check") / f"{model}-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None

    rows = []
    for lang in args.langs.split(","):
        conversations: dict[str, str] = {}
        for key, message in QUESTIONS[lang]:
            if only and key not in only:
                continue
            conv = conversations.get(FOLLOWS.get(key, ""))
            print(f"[{lang}] {key}: {message}", flush=True)
            try:
                r = ask(args.agent, message, lang, conv)
            except Exception as e:  # keep going; the row records the failure
                r = {"error": {"message": f"{type(e).__name__}: {e}"}, "tools": [], "files": [], "text": ""}
            conversations[key] = r.get("conversation_id")
            for f in r["files"]:
                name = f"{lang}-{key}-{f['filename']}"
                urllib.request.urlretrieve(f"{args.agent}/files/{f['file_id']}", out / name)
                f["saved_as"] = name
            (out / f"{lang}-{key}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
            (out / f"{lang}-{key}.md").write_text(f"# {message}\n\n{r['text']}\n")
            done = r.get("done") or {}
            usage = done.get("usage") or {}
            row = {"lang": lang, "key": key, "model": done.get("model", model), "requests": done.get("requests"),
                   "seconds": r.get("seconds"), "tools": " ".join(t["name"] for t in r["tools"] if "input" in t),
                   "files": len(r["files"]), **usage,
                   "cost": cost(done.get("model", model), usage) if usage else None,
                   "problem": (r.get("error") or r.get("refusal") or {}).get("message")}
            rows.append(row)
            status = row["problem"] or f"{row['requests']} requests, ${row['cost'] or 0:.4f}, {row['seconds']}s"
            print(f"    -> {status}", flush=True)

    head = ("| lang | question | model | requests | input | cache read | cache write | output | cost (USD) "
            "| seconds | files | tools / problem |\n|" + "---|" * 12)
    lines = [head]
    for r in rows:
        lines.append(f"| {r['lang']} | {r['key']} | {r['model']} | {r['requests'] or ''} "
                     f"| {r.get('input_tokens', '')} | {r.get('cache_read_input_tokens', '')} "
                     f"| {r.get('cache_creation_input_tokens', '')} | {r.get('output_tokens', '')} "
                     f"| {fmt_cost(r['cost'])} | {r['seconds'] or ''} | {r['files']} "
                     f"| {r['problem'] or r['tools']} |")
    total = sum(r["cost"] or 0 for r in rows)
    lines.append(f"\nTotal: ${total:.4f} over {len(rows)} questions.")
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    (out / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print("\n".join(lines))
    print(f"\nSaved to {out}/")


if __name__ == "__main__":
    main()
