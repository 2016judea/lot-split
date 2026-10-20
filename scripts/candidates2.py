#!/usr/bin/env python3
"""Round 2 distribution (brief 2026-10-20): three segments round 1 did not reach, each opening on the
reader's own public record, then the split-worth line for a lot that passes.

  developers  builders and developers on City of Minneapolis new-construction permits since 2022
              (CCS_Permits, every occupancy but commercial), applicant or owner, not in round 1.
              Record: their newest permit. Lot: that permit's lot if it passes, else the nearest
              passing lot to it.
  owners      LLCs and other entities that own a passing lot, reached through the email on the
              city's own rental licence filing for that lot (Active_Rental_Licenses, pulled
              2026-10-20); business domains only, never a person's personal address.
  surveyors   Twin Cities land surveyors; record: the line on their own site about the work.
              Lot: a passing lot that sold in the last 12 complete months, one per surveyor.

Who and which address live in outreach/round2/recipients.json (gitignored; each email was read off
the firm's own site or the licence filing). Every number in a draft is read here from the build
(private/rows.json, stats.json), the permit cache or the licence cache. Deduped against
~/Desktop/outreach-ledger/outreach.duckdb `touch` (any status), ~/Desktop/paid-round2/queue.json and
round 1's ledger, by address and by non-webmail domain; every domain must answer an MX lookup.
Writes outreach/round2/ledger.csv and drafts/<token>.txt. Nothing is sent.
"""
import csv, datetime as dt, hashlib, json, math, re, subprocess, sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from candidates import mx_ok, norm, short_name, title  # noqa: E402

OUT = ROOT / "outreach" / "round2"
SITE = "https://lot-split.vercel.app"
SUBSTACK = "https://randomaidan.substack.com/p/business-prototypes"
PERMITS = ROOT / "data/cache/permits_new_all_2026-10-20.json"
LICENCES = ROOT / "data/cache/rental_licenses_2026-10-20.json"
OFFER = json.loads((ROOT / "site/public/offer.json").read_text())
STATS = json.loads((ROOT / "site/public/data/stats.json").read_text())
TODAY = dt.date.today().isoformat()
H = Path.home() / "Desktop"
WEBMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "comcast.net", "icloud.com", "msn.com",
           "live.com", "me.com", "q.com", "optonline.net", "earthlink.net", "frontiernet.net", "charter.net", "centurylink.net"}


def utm15(lat, lon):
    """WGS84 -> UTM zone 15N metres (EPSG:26915 to well under a metre here), to sit permits on the lots' grid."""
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    phi, lam, lam0 = math.radians(lat), math.radians(lon), math.radians(-93)
    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2); t = math.tan(phi) ** 2; c = ep2 * math.cos(phi) ** 2
    A = math.cos(phi) * (lam - lam0)
    m = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi) - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = k0 * n * (A + (1 - t + c) * A ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * A ** 5 / 120) + 500000
    y = k0 * (m + n * math.tan(phi) * (A * A / 2 + (5 - t + 9 * c + 4 * c * c) * A ** 4 / 24 + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * A ** 6 / 720))
    return x, y


def entity(name):
    """BOTRYS PROPERTIES LLC -> Botrys Properties LLC; keeps KK, DKW, II, LLC, LP as written."""
    keep = lambda w: w in {"LLC", "LP", "LLP", "INC"} or re.fullmatch(r"[IVX]+", w) or not re.search(r"[AEIOUY]", w) or (len(w) <= 3 and w.isalpha() and w not in {"AVE", "ST", "THE", "OF"})
    return " ".join(w if keep(w) else w.capitalize() for w in name.split()).replace("INC", "Inc")


money = lambda v: f"${round(v, -3):,.0f}"
month = lambda ms: dt.datetime.fromtimestamp(ms / 1000).strftime("%B %Y")


def kind(p):
    u = p.get("dwellingUnitsNew") or 0
    o = p["occupancyType"]
    if o == "SFD":
        return "a new house"
    if o == "TFD":
        return "a new two-family home"
    if o == "TH":
        return "new townhomes"
    if o == "3to4":
        return f"a new {u}-unit building" if u else "a new three- or four-unit building"
    if o == "MFD":
        return f"a new {u}-unit apartment building" if u else "a new apartment building"
    if o == "Mixed":
        return f"a new mixed-use building with {u} homes" if u else "a new mixed-use building"
    return "a new building"


def lot_line(lot, own=True):
    a, s = f"{lot['area']:,}", f"{lot['street_side']:.0f}"
    rule = f"each new lot needs {lot['min_area']:,} sq ft and {lot['min_width']} ft"
    if own:
        return f"That lot is {a} sq ft with {s} ft along the street, so it could be split in two under the city's Chapter 540 rules ({rule})."
    return (f"The nearest lot to it that could be split in two under the city's Chapter 540 rules is {title(lot['address'])}: "
            f"{a} sq ft with {s} ft along the street, where {rule}.")


def worth(lot):
    return (f"On the county's own land values, the two halves would be worth about {money(lot['split_land_value'])}, "
            f"{money(lot['split_uplift'])} more than the lot is today.")


MARKET = f"{STATS['qualifying']:,} Minneapolis 1-3 unit lots pass that check, and {STATS['sold_last_12']} of them sold in the 12 months to {STATS['complete_month_label']}."


def draft(r, body):
    link = (f"{'Yours' if r['segment'] == 'owners' else 'That lot'} and ten more are open to poke at, no login: {r['page_url']} "
            f"The full list, with owner, county value and last sale, is ${OFFER['price_usd']}, once.")
    lines = [f"To: {r['email']}", f"Subject: bricks / {short_name(r['company'])}", "", "Hello,", "", r["own_record"], ""] + body + \
            ["", link, "", f"How this gets built: {SUBSTACK}", "", "Aidan", "Brick & Mortar", ""]
    return "\n".join(lines)


def main():
    # rows already scheduled in Zoho keep their status, message id and draft (the draft is what went to Zoho)
    done = {r["token"]: r for r in csv.DictReader((OUT / "ledger.csv").open()) if r["status"] == "scheduled"} if (OUT / "ledger.csv").exists() else {}
    for old in (OUT / "drafts").glob("*.txt"):  # this script's own output from an earlier run
        if old.stem not in done:
            old.unlink()
    rec = json.loads((OUT / "recipients.json").read_text())
    rows = json.loads((ROOT / "private/rows.json").read_text())["rows"]
    by_pin = {r["pin"]: r for r in rows}
    passing = [r for r in rows if r["listed"] and r.get("split_land_value")]
    pass_pin = {r["pin"] for r in passing}

    # dedupe sets
    led = duckdb.connect(str(H / "outreach-ledger/outreach.duckdb"), read_only=True)
    touched = {k.lower() for (k,) in led.execute("select recipient_key from touch where recipient_key like '%@%'").fetchall()}
    led.close()
    queued = {x["to"].lower() for x in json.loads((H / "paid-round2/queue.json").read_text())}
    r1 = list(csv.DictReader((ROOT / "outreach/round1/ledger.csv").open()))
    r1_orgs = {norm(r["company"]) for r in r1}
    taken = touched | queued | {r["email"].lower() for r in r1 if r["email"]}
    taken_domains = {e.split("@")[1] for e in taken if "@" in e} - WEBMAIL

    out, skipped, used_lots, emails = [], [], set(), set()

    def add(seg, org, email, src, record, lot, body, extra=""):
        e = email.lower()
        d = e.split("@")[1]
        why = ("already touched or queued" if e in taken else "domain already touched or queued" if d in taken_domains
               else "round 1 org" if norm(org) in r1_orgs else "duplicate in round 2" if e in emails
               else f"{d} has no MX" if not mx_ok(e) else None)
        if why:
            skipped.append((seg, org, e, why))
            return
        emails.add(e)
        used_lots.add(lot["pin"])
        tok = hashlib.sha256(f"lot-split-r2|{e}|{org}".encode()).hexdigest()[:10]
        r = dict(token=tok, variant="A", segment=seg, company=org, name="", email=e, email_source=src, email_source_date=TODAY,
                 own_record=record, status="draft", hold_reason="", drafted_on=TODAY, sent_on="", reply_kind="", reply_on="",
                 lot_address=lot["address"], page_url=f"{SITE}/for/{tok}/", message_id="", scheduled_for="", record_detail=extra)
        if tok in done:
            out.append(done[tok]); return
        out.append(r)
        (OUT / "drafts").mkdir(parents=True, exist_ok=True)
        (OUT / "drafts" / f"{tok}.txt").write_text(draft(r, body))

    # developers
    permits = [p for p in json.loads(PERMITS.read_text()) if p["occupancyType"] != "Comm"]
    for d in rec["developers"]:
        keys = {norm(m) for m in d["match"]}
        ps = sorted([p for p in permits if norm(p.get("applicantName")) in keys or norm(p.get("fullName")) in keys],
                    key=lambda p: p["issueDate"] or 0, reverse=True)
        if not ps:
            skipped.append(("developers", d["org"], d["email"], "no permit found")); continue
        p = ps[0]
        n = len(ps)
        rec_line = (f"Your {month(p['issueDate'])} permit for {kind(p)} at {title(p['Display'])}"
                    + (f", one of {n} new-construction permits in Minneapolis with your name on them since 2022." if n > 1 else "."))
        apn = (p.get("APN") or "").strip()
        if apn in pass_pin and apn not in used_lots:
            lot, own = by_pin[apn], True
        else:
            x, y = (by_pin[apn]["cx"], by_pin[apn]["cy"]) if apn in by_pin else utm15(p["Latitude"], p["Longitude"])
            lot = min((r for r in passing if r["pin"] not in used_lots), key=lambda r: (r["cx"] - x) ** 2 + (r["cy"] - y) ** 2)
            own = False
        add("developers", d["org"], d["email"], d["src"], rec_line, lot, [f"{lot_line(lot, own)} {worth(lot)} {MARKET}"],
            extra=p["permitNumber"])

    # owners, through the city's rental licence on their lot
    lic = json.loads(LICENCES.read_text())
    for o in rec["owners"]:
        mine = [r for r in passing if (r["owner"] or "").strip() == o["owner"]]
        hit = None
        for lot in mine:
            for L in lic:
                if (L["apn"] or "").strip() == lot["pin"] and o["email"] in {(L["ownerEmail"] or "").lower(), (L["applicantEmail"] or "").lower()}:
                    hit = (lot, L); break
            if hit:
                break
        if not hit:
            skipped.append(("owners", o["org"], o["email"], "email not on a licence for a passing lot they own")); continue
        lot, L = hit
        rec_line = (f"Your city rental licence for {title(lot['address'])} ({L['licenseNumber']}), "
                    f"the lot Hennepin County lists under {entity(o['owner'])}.")
        add("owners", o["org"], o["email"], f"City of Minneapolis rental licence {L['licenseNumber']} (Active_Rental_Licenses)", rec_line, lot,
            [f"{lot_line(lot)} {worth(lot)} {MARKET}"], extra=L["licenseNumber"])

    # surveyors: a passing lot that sold in the 12 complete months, newest first, one each
    end = dt.date.fromisoformat(STATS["complete_month"])
    start = (end.replace(day=1) - dt.timedelta(days=330)).replace(day=1)
    sold = sorted([r for r in passing if r.get("last_sale_date") and start.isoformat() <= r["last_sale_date"] < (end + dt.timedelta(days=31)).replace(day=1).isoformat()
                   and r.get("last_sale_price")], key=lambda r: r["last_sale_date"], reverse=True)
    for s in rec["surveyors"]:
        lot = next(r for r in sold if r["pin"] not in used_lots)
        sale = dt.date.fromisoformat(lot["last_sale_date"]).strftime("%B %Y")
        market = MARKET.replace("pass that check", "pass the city's Chapter 540 split check")
        body = [f"Every Minneapolis lot split starts with a survey. {market} One sold in {sale} for {money(lot['last_sale_price'])}: "
                f"{title(lot['address'])}, {lot['area']:,} sq ft with {lot['street_side']:.0f} ft along the street. {worth(lot)}"]
        add("surveyors", s["org"], s["email"], s["src"], s["record"], lot, body)

    cols = ["token", "variant", "segment", "company", "name", "email", "email_source", "email_source_date", "own_record", "status",
            "hold_reason", "drafted_on", "sent_on", "reply_kind", "reply_on", "lot_address", "page_url", "message_id", "scheduled_for", "record_detail"]
    with (OUT / "ledger.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print("drafted", len(out), dict(Counter(r["segment"] for r in out)))
    for s in skipped:
        print("skip", *s)


if __name__ == "__main__":
    sys.exit(main())
