#!/usr/bin/env python3
"""Minnesota Secretary of State lookups for round-2 recipients (an entity that owns a passing lot,
or owns/applies on a Minneapolis new-construction permit). Public MBLS search, no login, 1 req/s,
every page cached under data/cache/sos/. Returns the filing: number, date, registered agent,
registered office, principal office, manager/CEO."""
import hashlib, html, json, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data/cache/sos"
BASE = "https://mblsportal.sos.mn.gov"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/126 Safari/537.36"
STOP = {"INC", "LLC", "L L C", "CO", "CORP", "CORPORATION", "COMPANY", "LTD", "THE", "PLLC", "PA", "P A", "LLP", "LC", "LP"}
_last = [0.0]


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if f.exists():
        return f.read_text()
    w = 1.0 - (time.time() - _last[0])
    if w > 0:
        time.sleep(w)
    body = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read().decode("utf-8", "ignore")
    _last[0] = time.time()
    f.write_text(body)
    return body


def key(s):
    t = [x for x in re.split(r"[^A-Z0-9]+", (s or "").upper().replace("&", " AND ")) if x]
    while t and t[-1] in STOP:
        t.pop()
    return " ".join(t[1:] if t and t[0] == "THE" else t)


def lines_of(body):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", body, flags=re.S)
    return [l.strip() for l in html.unescape(re.sub(r"<[^>]+>", "\n", t)).split("\n") if l.strip()]


def lookup(name):
    q = urllib.parse.urlencode({"BusinessName": key(name)[:60], "IncludePriorNames": "False", "Status": "All", "Type": "BeginsWith"})
    body = fetch(f"{BASE}/Business/BusinessSearch?{q}")
    for tr in body.split("<tr")[1:]:
        m = re.search(r'href="(/Business/SearchDetails\?filingGuid=[^"]+)"', tr)
        if not m:
            continue
        url = BASE + html.unescape(m.group(1))
        L = lines_of(fetch(url))
        after = lambda lab: L[L.index(lab) + 1] if lab in L and L.index(lab) + 1 < len(L) else ""
        bn = after("Minnesota Business Name") or after("Business Name")
        if key(bn) != key(name) or "Assumed" in after("Business Type"):
            continue
        blk = lambda lab: " ".join(L[L.index(lab) + 1:L.index(lab) + 4]) if lab in L else ""
        people = [(lab, L[i + 1]) for i, x in enumerate(L) for lab in ("Manager", "Chief Executive Officer", "Registered Agent(s)") if x == lab and i + 1 < len(L)]
        return dict(entity=bn, type=after("Business Type"), file_number=after("File Number"), filed=after("Filing Date"),
                    status=after("Status"), agent=after("Registered Agent(s)"), office=blk("Registered Office Address"),
                    principal=blk("Principal Executive Office Address"), people=people, url=url)
    return None
