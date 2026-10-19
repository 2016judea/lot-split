#!/usr/bin/env python3
"""Pull the two City of Minneapolis ArcGIS layers this product reads, paged to exhaustion
and cached raw under data/cache/ (a page file per request; re-running reads the cache).

  Planning_Zoning_Built_Form            791 polygons, the city-edited built-form overlay
  Assessing_Department_Parcel_Data_2026 132k rows, the assessor's current parcel table

Paging rules follow bricks/scripts/arcgis_pull.py: the page size is the layer's own
maxRecordCount (asking for more is clamped silently), rows are ordered by the OID field,
and the pull is not complete until a page comes back without exceededTransferLimit.
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
BASE = "https://services.arcgis.com/afSMGVsC7QlRK1kZ/arcgis/rest/services"
LAYERS = {
    "built_form": (f"{BASE}/Planning_Zoning_Built_Form/FeatureServer/0", True),
    "assessor_2026": (f"{BASE}/Assessing_Department_Parcel_Data_2026/FeatureServer/0", False),
}
# Hennepin County's live parcel layer carries each parcel's LAST recorded sale (month grain),
# current to the month before last; bricks' sale table stops 2026-07-01. Re-pulled into a
# dated folder so a rebuild a week later reads new sales (2026-10-19).
HENNEPIN = "https://gis.hennepin.us/arcgis/rest/services/HennepinData/LAND_PROPERTY/MapServer/1"
WHERE = {"hennepin_sales": "MUNIC_CD='01'"}
FIELDS = {"hennepin_sales": "OBJECTID,PID,SALE_DATE,SALE_PRICE,SALE_CODE,SALE_CODE_NAME"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(url, params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))


def pull(name, url, geometry, folder=None):
    out = CACHE / (folder or name)
    out.mkdir(parents=True, exist_ok=True)
    meta = get(url, {"f": "json"})
    (out / "layer.json").write_text(json.dumps(meta, indent=1))
    page = meta["maxRecordCount"]
    oid = next(f["name"] for f in meta["fields"] if f["type"] == "esriFieldTypeOID")
    offset, n = 0, 0
    while True:
        f = out / f"page_{offset:07d}.json"
        if f.exists():
            d = json.loads(f.read_text())
        else:
            p = {"where": WHERE.get(name, "1=1"), "outFields": FIELDS.get(name, "*"), "orderByFields": oid, "resultOffset": offset,
                 "resultRecordCount": page, "f": "json", "returnGeometry": "true" if geometry else "false"}
            if geometry:
                p["outSR"] = 26915
            d = get(f"{url}/query", p)
            if "error" in d:
                sys.exit(f"{name} offset {offset}: {d['error']}")
            f.write_text(json.dumps(d))
        got = len(d.get("features", []))
        n += got
        if not d.get("exceededTransferLimit") or got == 0:
            break
        offset += page
    cnt = get(f"{url}/query", {"where": WHERE.get(name, "1=1"), "returnCountOnly": "true", "f": "json"}).get("count", "?")
    print(f"{name}: {n} rows in {len(list(out.glob('page_*.json')))} pages; server count {cnt}", flush=True)
    return n


def pull_sales():
    import datetime as dt
    return pull("hennepin_sales", HENNEPIN, False, folder=f"hennepin_sales/{dt.date.today():%Y-%m-%d}")


if __name__ == "__main__":
    if sys.argv[1:] == ["sales"]:
        pull_sales()
    else:
        for name, (url, geometry) in LAYERS.items():
            pull(name, url, geometry)
        pull_sales()
