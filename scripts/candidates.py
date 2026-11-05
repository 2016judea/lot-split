#!/usr/bin/env python3
"""Round 1 distribution: 50+ named recipients, each opening on a lot of their own, drafted not sent.

Segments (brief 2026-10-18):
  builders  applicants on 3+ City of Minneapolis permits for a new 1-3 unit house since 2022
            (CCS_Permits, live), plus contractors whose own published business address is a
            1-3 unit lot. Their own record: their newest permit, the lot it sits on.
  adu       applicants on Minneapolis permits whose comments name an ADU / accessory dwelling.
  designers architects and interior/ADU designers whose published address is a 1-3 unit lot.
  agents    residential agents whose published office is a 1-3 unit lot; plus the agents
            already written to on 10/13 (private/agent_candidates.json) as a SECOND TOUCH,
            held, because none has a lot of their own on our list.

Emails: MN DLI licence export (secure.doli.state.mn.us, curled 2026-10-17 by busy-contractors)
or Overture places 2026-08-19.0 (bricks closed_system overture_places). Each email's domain must
answer an MX lookup. Deduped against ~/Desktop/workspace/outreach-ledger/outreach.duckdb `contacted`.
A/B alternates within each segment. Writes outreach/round1/ledger.csv and drafts/<token>.txt
(both gitignored). Nothing is sent.
"""
import csv, datetime as dt, hashlib, json, re, subprocess, sys, urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outreach" / "round1"
CACHE = ROOT / "data" / "cache"
SITE = "https://lot-split.vercel.app"
SUBSTACK = "https://randomaidan.substack.com/p/business-prototypes"
DLI = Path.home() / "Desktop/workspace/busy-contractors/pipeline/cache/dli_res.csv"
DLI_DATE = "2026-10-17"
OVERTURE_DATE = "2026-08-19"
PERMITS = "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services/CCS_Permits/FeatureServer/0/query"
TODAY = dt.date.today().isoformat()
OFFER = json.loads((ROOT / "site/public/offer.json").read_text())
STATS = json.loads((ROOT / "site/public/data/stats.json").read_text())

SUFFIX = re.compile(r"\b(LLC|L L C|INC|INCORPORATED|CO|COMPANY|CORP|CORPORATION|LTD|THE|OF|MN|MINNESOTA)\b")
norm = lambda s: re.sub(r"\s+", " ", SUFFIX.sub(" ", re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper().replace("&", " AND ")))).strip()


def permits(where, name):
    f = CACHE / f"permits_{name}_{TODAY}.json"
    if f.exists():
        return json.loads(f.read_text())
    rows, off = [], 0
    while True:
        q = urllib.parse.urlencode({"where": where, "outFields": "applicantName,Display,issueDate,APN,permitNumber,workType,occupancyType,comments",
                                    "orderByFields": "OBJECTID", "resultOffset": off, "resultRecordCount": 2000,
                                    "returnGeometry": "false", "f": "json"})
        d = json.load(urllib.request.urlopen(f"{PERMITS}?{q}", timeout=120))
        fs = [x["attributes"] for x in d.get("features", [])]
        rows += fs
        if not d.get("exceededTransferLimit") or not fs:
            break
        off += len(fs)
    f.write_text(json.dumps(rows))
    return rows


def mx_ok(email, memo={}):
    dom = email.split("@")[-1].lower()
    if dom not in memo:
        try:
            out = subprocess.run(["dig", "+short", "MX", dom], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            out = ""
        memo[dom] = bool(out)
    return memo[dom]


# Overture's "contractor" holds painters and pavers; the trades below never split a lot or build an ADU.
TRADE = re.compile(r"PLUMB|MECHANICAL|ELECTRIC|HEATING|HVAC|SEWER|PAINT|BRUSH|DRYWALL|TILE|ASPHALT|CONCRETE|LANDSCAP|STONE|COUNTERTOP|"
                   r"WOOD|FOUNDATION|FLOOR|INSPECT|ROOF|GUTTER|WINDOW|SIDING|MASONRY|GOLF|INTERIORS?$|KITCHEN|BINGS|IRRIGATION|TREE", re.I)
WANTS = {"builders": re.compile(r"BUILD|CONSTRUCT|REMODEL|RENOVAT|HOMES|RESTORATION|CONTRACTING|DEVELOP", re.I),
         "agents": re.compile(r"REALT|REAL ESTATE|BROKER|HOMES|PROPERTIES|GROUP|LIFESTYLES|COLDWELL|EDINA|KELLER|RE/MAX|REMAX", re.I)}


def main():
    rows = json.loads((ROOT / "private/rows.json").read_text())["rows"]
    by_pin = {r["pin"]: r for r in rows}

    # emails: DLI by licensee name and DBA; Overture by name
    dli = {}
    for r in csv.DictReader(DLI.open(encoding="utf-8", errors="replace")):
        e = (r["Email_Address"] or "").strip().lower()
        if "@" in e and r["Status"] == "Issued":
            for n in (r["Name"], r["DBA_Name"]):
                if n:
                    dli.setdefault(norm(n), (e, r["Name"].title()))
    cs = duckdb.connect(str(Path.home() / "Desktop/workspace/bricks/data/closed_system.duckdb"), read_only=True)
    places = []
    for key, a in cs.execute("select parcel_key, attrs from record where layer='overture_places' and attrs like '%@%'").fetchall():
        a = json.loads(a)
        if a.get("emails"):
            places.append((key.split(":")[-1] if key else None, a))
    cs.close()
    ov_by_name = {norm(a["name"]): a for _, a in places if a.get("name")}

    led = duckdb.connect(str(Path.home() / "Desktop/workspace/outreach-ledger/outreach.duckdb"), read_only=True)
    contacted = {k for (k,) in led.execute("select recipient_key from contacted").fetchall() if k}
    contacted_orgs = {norm(o) for (o,) in led.execute("select org from contacted where org is not null").fetchall()}
    led.close()

    cands = []  # dicts: segment, company, name, email, email_source, email_source_date, own_record, lot

    def email_for(company):
        k = norm(company)
        if k in dli:
            return dli[k][0], "MN DLI residential contractor licence export", DLI_DATE
        if k in ov_by_name:
            return ov_by_name[k]["emails"][0].lower(), "Overture places (their published listing)", OVERTURE_DATE
        return None, None, None

    def from_permits(prows, segment, min_n, what):
        by = defaultdict(list)
        for p in prows:
            if p.get("applicantName"):
                by[norm(p["applicantName"])].append(p)
        for k, ps in by.items():
            if len(ps) < min_n:
                continue
            ps.sort(key=lambda p: p["issueDate"] or 0, reverse=True)
            mine = next((p for p in ps if (p.get("APN") or "").strip() in by_pin), None)
            company = ps[0]["applicantName"].strip()
            e, src, sd = email_for(company)
            lot = by_pin.get((mine or {}).get("APN", "").strip()) if mine else None
            when = dt.datetime.fromtimestamp((mine or ps[0])["issueDate"] / 1000).strftime("%B %Y") if (mine or ps[0])["issueDate"] else ""
            n = len(ps)
            rec = (f"Your {when} permit for {what} at {title((mine or ps[0])['Display'])}"
                   + (f", one of {n} you've pulled in Minneapolis since 2022." if n > 1 else "."))
            cands.append(dict(segment=segment, company=company.title() if company.isupper() else company, name="", email=e,
                              email_source=src, email_source_date=sd, own_record=rec, lot=lot,
                              hold=None if lot else "their permit lots are not 1-3 unit lots on our list"))

    since = "issueDate >= DATE '2022-01-01'"
    new = permits(f"workType='New' AND occupancyType IN ('SFD','TFD','3to4') AND {since}", "new_homes")
    from_permits(new, "builders", 3, "a new house")
    adu = permits(f"(comments LIKE '%ADU%' OR comments LIKE '%ccessory dwelling%') AND {since}", "adu")
    seen_builders = {norm(c["company"]) for c in cands}
    from_permits([p for p in adu if norm(p.get("applicantName")) not in seen_builders and not TRADE.search(p.get("applicantName") or "")],
                 "adu", 1, "an accessory dwelling unit")

    seg_of = {"contractor": "builders", "construction_services": "builders", "home_developer": "builders", "builders": "builders",
              "architectural_designer": "designers", "architect": "designers", "interior_design": "designers",
              "real_estate_agent": "agents", "real_estate_service": "agents", "real_estate": "agents"}
    for pin, a in places:
        seg = seg_of.get(a.get("category") or "")
        if not seg or pin not in by_pin or TRADE.search(a["name"]) or (seg in WANTS and not WANTS[seg].search(a["name"])):
            continue
        lot = by_pin[pin]
        cands.append(dict(segment=seg, company=a["name"], name="", email=a["emails"][0].lower(),
                          email_source=f"Overture places (their published listing{', ' + a['websites'][0] if a.get('websites') else ''})",
                          email_source_date=OVERTURE_DATE,
                          own_record=f"Your listing puts {a['name']} at {title(lot['address'])}.", lot=lot, hold=None))

    for row in json.loads((ROOT / "private/agent_candidates.json").read_text()):
        name, org, email, src, post = row[0], row[1], row[2], row[3], row[4]
        cands.append(dict(segment="agents", company=org, name=name, email=(email or "").lower(), email_source=src,
                          email_source_date=row[7][:10] if len(row) > 7 and row[7] else "", own_record=post, lot=None,
                          hold="second touch (written 10/13 for another product); no lot of their own on our list", second=True))

    # one row per email and per org; dedupe against the ledger; verify domains
    final, emails, orgs = [], set(), set()
    for c in cands:
        e = c["email"]
        if not e or "@" not in e:
            c["hold"] = c["hold"] or "no published email"
        elif e in emails or norm(c["company"]) in orgs:
            continue
        elif (e in contacted or norm(c["company"]) in contacted_orgs) and not c.get("second"):
            continue
        elif not mx_ok(e):
            c["hold"] = c["hold"] or f"{e.split('@')[1]} has no mail server (MX)"
        if e:
            emails.add(e)
        orgs.add(norm(c["company"]))
        final.append(c)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "drafts").mkdir(exist_ok=True)
    for old in (OUT / "drafts").glob("*.txt"):  # this script's own output from an earlier run
        old.unlink()
    flip = defaultdict(int)
    cols = ["token", "variant", "segment", "company", "name", "email", "email_source", "email_source_date", "own_record",
            "status", "hold_reason", "drafted_on", "sent_on", "reply_kind", "reply_on", "lot_address", "page_url"]
    out = []
    for c in final:
        tok = hashlib.sha256(f"lot-split|{c['email']}|{c['company']}".encode()).hexdigest()[:10]
        status = "hold" if c["hold"] else "draft"
        v = ""
        if status == "draft":
            v = "AB"[flip[c["segment"]] % 2]
            flip[c["segment"]] += 1
        r = dict(token=tok, variant=v, segment=c["segment"], company=c["company"], name=c["name"], email=c["email"] or "",
                 email_source=c["email_source"] or "", email_source_date=c["email_source_date"] or "", own_record=c["own_record"],
                 status=status, hold_reason=c["hold"] or "", drafted_on=TODAY, sent_on="", reply_kind="", reply_on="",
                 lot_address=c["lot"]["address"] if c["lot"] else "", page_url=f"{SITE}/for/{tok}/" if status == "draft" else "")
        out.append(r)
        if status == "draft":
            (OUT / "drafts" / f"{tok}.txt").write_text(draft(r, c["lot"]))
    with (OUT / "ledger.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    seg = defaultdict(lambda: defaultdict(int))
    for r in out:
        seg[r["segment"]][r["status"] + (r["variant"] and "-" + r["variant"])] += 1
    print(json.dumps(seg, indent=1))
    print("holds:", defaultdict(int, {h: sum(1 for r in out if r["hold_reason"] == h) for h in {r["hold_reason"] for r in out if r["hold_reason"]}}))


def title(s):
    return " ".join(w if re.fullmatch(r"(N|S|NE|SE|NW|SW|E|W)", w) else w.capitalize() for w in (s or "").split())


def verdict(lot):
    a, s = f"{lot['area']:,}", f"{lot['street_side']:.0f}"
    if lot["listed"]:
        return (f"That lot is {a} sq ft with {s} ft along the street, so it could be split in two under the city's "
                f"Chapter 540 rules (each new lot needs 5,000 sq ft and 40 ft).")
    if lot["can_split"]:
        return f"That lot is {a} sq ft with {s} ft along the street. It is big enough to split, but {lot['off_list']}."
    return (f"That lot is {a} sq ft with {s} ft along the street, so it holds one house, not two: a split needs "
            f"{lot['need_area']:,} sq ft and {lot['need_width']} ft (Chapter 540).")


def short_name(c):
    return re.sub(r",?\s+(Inc|Llc|LLC|L\.L\.C\.|Co\.|Company|Corp)\.?$", "", c.strip()).rstrip(".")


def draft(r, lot):
    n = STATS["qualifying"]
    lines = [f"To: {r['email']}", f"Subject: bricks / {short_name(r['company'])}", "", "Hello,", "", r["own_record"], "",
             f"{verdict(lot)} {n:,} Minneapolis 1-3 unit lots do pass, and {STATS['sold_last_12']} of them sold in the 12 months to {STATS['complete_month_label']}.", ""]
    link = f"Yours and ten of them are open to poke at, no login: {r['page_url']}"
    if r["variant"] == "A":
        link += f" The full list, with owner, county value and last sale, is ${OFFER['price_usd']}, once."
    lines += [link, "", f"How this gets built: {SUBSTACK}", "", "Aidan", "Brick & Mortar", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
