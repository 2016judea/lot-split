#!/usr/bin/env python3
"""Write site/public/index.html from site/template.html, site/public/data/stats.json and site/public/data/sample.json.
Every number on the page is substituted here from the build's output; nothing is typed.
Also writes site/public/data/for/<token>.json for each recipient in outreach/round1/ledger.csv
(the /for/<token>/ page opens on their own lot and carries the A/B variant off the URL)."""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SNIPPET = Path.home() / ".claude/skills/site-analytics/posthog_snippet.html"
LEDGER = ROOT / "outreach/round1/ledger.csv"


def money_short(v):
    return f"${v/1000:.0f}k" if v and v < 1e6 else (f"${v/1e6:.2f}M" if v else "")


def build(stats=None, sample=None, template=None, posthog=None):
    stats = stats or json.loads((SITE / "public/data/stats.json").read_text())
    sample = sample or json.loads((SITE / "public/data/sample.json").read_text())
    template = template or (SITE / "template.html").read_text()
    posthog = posthog if posthog is not None else SNIPPET.read_text().replace("__SITE__", "lot-split")
    n = lambda v: f"{v:,}"
    subs = {
        "__DESC__": f"{n(stats['qualifying'])} Minneapolis 1-3 unit lots pass the city's split check (two lots of {n(stats['min_area'])} sq ft and {stats['min_width']} ft). Type an address to check yours.",
        "__POSTHOG__": posthog,
        "__BUILT__": stats["built"],
        "__MIN_AREA__": n(stats["min_area"]), "__MIN_WIDTH__": str(stats["min_width"]),
        "__NEED_AREA__": n(2 * stats["min_area"]), "__NEED_WIDTH__": str(2 * stats["min_width"]),
        "__QUALIFYING__": n(stats["qualifying"]),
        "__SOLD_MONTH__": n(stats["sold_complete_month"]), "__MONTH__": stats["complete_month_label"],
        "__SOLD_12__": n(stats["sold_last_12"]), "__MEDIAN__": money_short(stats["median_price_last_12"]),
        "__HOMESTEAD__": n(stats["qualifying_homestead"]), "__CLOSE__": n(stats["close"]),
        "__OPEN_N__": str(len(sample["open"])),
        "__BIGLOT__": n(stats["big_lot_blocks"]),
        "__BF_EDITED__": stats["built_form_edited"], "__SALES_THROUGH__": stats["sales_through"],
        "__PUBLIC__": n(stats["qualifying_public_excluded"]), "__OVER_ACRE__": n(stats["over_acre"]),
        "__STATS_JSON__": json.dumps({k: v for k, v in stats.items() if k != "by_neighborhood"}),
        "__SAMPLE_JSON__": json.dumps(sample),
    }
    html = template
    for k, v in subs.items():
        html = html.replace(k, v)
    left = re.findall(r"__[A-Z_0-9]+__", html)
    assert not left, f"unfilled placeholders: {sorted(set(left))}"
    return html


def for_pages():
    out = SITE / "public/data/for"
    out.mkdir(parents=True, exist_ok=True)
    if not LEDGER.exists():
        return 0
    k = 0
    for r in csv.DictReader(LEDGER.open()):
        if not r.get("token") or not r.get("own_record"):
            continue
        (out / f"{r['token']}.json").write_text(json.dumps({
            "address": r["own_record"], "variant": r.get("variant", ""), "who": r.get("who") or "your lot"}))
        k += 1
    return k


if __name__ == "__main__":
    (SITE / "public/index.html").write_text(build())
    print("site/public/index.html", (SITE / "public/index.html").stat().st_size, "bytes;", for_pages(), "/for/ pages")
