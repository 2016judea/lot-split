#!/usr/bin/env python3
"""Join the assessor table, the built-form overlay, the county parcel polygons and the
recorded sales into one row per Minneapolis 1-3 unit lot, run the Chapter 540 rule check
on each (scripts/rules.py), and write:

  private/rows.json             every lot in the universe, every field (gitignored)
  private/bundle/full.json.gz   the paid list: every lot that passes, with owner, value, last sale
  private/bundle/index.json.gz  the free address check: every lot, free fields only
  site/public/data/stats.json          the numbers the free page prints (all derived here)
  site/public/data/sample.json         the open rows (free fields) and the worked example

Reads bricks' hennepin_gis.duckdb (parcel polygons, EPSG:26915) and closed_system.duckdb
(recorded sales) read-only. Every number on the page comes out of this script.
"""
import datetime as dt
import glob
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
from shapely import STRtree
from shapely.geometry import Point, Polygon, shape
from shapely.wkb import loads as wkb_loads

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
PRIVATE = ROOT / "private"
BUNDLE = PRIVATE / "bundle"
SITE = ROOT / "site" / "public"
BRICKS = Path.home() / "Desktop" / "bricks" / "data"
FT = 3.28084  # metres to feet (EPSG:26915 is metric)
import re
# public bodies: their lots pass the rule but are not for sale, so they leave the paid list (counted in stats)
PUBLIC = re.compile(r"MPLS PARK|PARK (&|AND) REC|CITY OF MINNEAPOLIS|MPHA|PUBLIC HOUSING|STATE OF MINNESOTA|HENNEPIN COUNTY|HENNEPIN FORFEITED|MINNEAPOLIS PUBLIC SCHOOLS|SPECIAL SCHOOL DIST", re.I)

UNIVERSE = {"RESIDENTIAL 1 UNIT": 1, "RESIDENTIAL 2 UNITS": 2, "RESIDENTIAL 3 UNITS": 3, "VACANT LAND - RESIDENTIAL": 0}
PAID = ["owner", "homestead", "emv_land", "emv_bldg", "emv_total", "land_per_sqft", "last_sale_date", "last_sale_price",
        "meets_4plus_dims", "too_big_for_1_3", "year_built", "fin_sqft", "stories", "bedrooms"]
FREE = ["pin", "address", "zip", "neighborhood", "area", "width", "depth", "street_side", "corner", "district", "zoning", "listed",
        "units", "building_use", "can_split", "area_ok", "width_ok", "area_close", "width_close", "need_area", "need_width",
        "min_area", "min_width", "rule_note", "height_1_3", "lon", "lat", "ring"]


def load_assessor():
    rows = {}
    for p in sorted(glob.glob(str(CACHE / "assessor_2026" / "page_*.json"))):
        for f in json.load(open(p))["features"]:
            a = f["attributes"]
            pin = (a["F_No_column_name_"] or "").lstrip("p")
            if pin:
                rows[pin] = a
    return rows


def load_built_form():
    feats = []
    for p in sorted(glob.glob(str(CACHE / "built_form" / "page_*.json"))):
        d = json.load(open(p))
        assert d["spatialReference"]["wkid"] == 26915, d["spatialReference"]
        for f in d["features"]:
            rings = f["geometry"]["rings"]
            poly = Polygon(rings[0], rings[1:]) if rings else None
            if poly is not None and not poly.is_valid:
                poly = poly.buffer(0)
            feats.append((f["attributes"]["Built_Form"], poly))
    meta = json.load(open(CACHE / "built_form" / "layer.json"))
    edited = dt.datetime.fromtimestamp(meta["editingInfo"]["dataLastEditDate"] / 1000, dt.UTC).date().isoformat()
    return feats, edited


def oriented_sides(poly):
    """Short and long side of the minimum rotated rectangle, in feet."""
    r = poly.minimum_rotated_rectangle
    xs, ys = r.exterior.coords.xy
    a = math.dist((xs[0], ys[0]), (xs[1], ys[1])) * FT
    b = math.dist((xs[1], ys[1]), (xs[2], ys[2])) * FT
    return min(a, b), max(a, b)


def main():
    asr = load_assessor()
    print(f"assessor rows {len(asr):,}", flush=True)
    bf, bf_edited = load_built_form()
    bf_tree = STRtree([g for _, g in bf])
    bf_names = [n for n, _ in bf]

    g = duckdb.connect(str(BRICKS / "hennepin_gis.duckdb"), read_only=True)
    g.execute("install spatial; load spatial")
    geo = {}
    for pin, wkb, area, pieces in g.execute(
        "select pin, ST_AsWKB(geom), area_sqft, piece_count from parcels where munic='MINNEAPOLIS'").fetchall():
        geo[pin] = (wkb_loads(bytes(wkb)), area, pieces)
    corners = defaultdict(set)
    for pin, road, ft in g.execute(
        "select f.pin, f.road_name, f.frontage_ft from parcel_frontage f join parcels p using(pin) "
        "where p.munic='MINNEAPOLIS' and f.class<>'private' and f.frontage_ft>=30").fetchall():
        corners[pin].add(road)
    g.close()
    print(f"parcel polygons {len(geo):,}", flush=True)

    c = duckdb.connect(str(BRICKS / "closed_system.duckdb"), read_only=True)
    sales = defaultdict(list)
    for key, d, v in c.execute(
        "select parcel_key, sale_date, sale_value from sale where parcel_key like 'hennepin:%' and sale_value>0").fetchall():
        sales[key.split(":", 1)[1]].append((d, v))
    max_sale = c.execute("select max(sale_date) from sale where parcel_key like 'hennepin:%'").fetchone()[0]
    c.close()
    # the latest month the sale table covers in full is the one before the month of its last date
    complete_month = (max_sale.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    print(f"sales to {max_sale}; complete month {complete_month:%B %Y}", flush=True)

    # universe: 1-3 unit homes and residential vacant land on Urban Neighborhood ground, with a polygon
    uni = {}
    for pin, a in asr.items():
        if a["PROPERTYTYPE"] not in UNIVERSE or not rules.is_residential_zoning(a["ZONING"]):
            continue
        if pin not in geo:
            continue
        uni[pin] = a
    print(f"universe {len(uni):,}", flush=True)

    # footnote 1: average 1-3 unit lot area within 350 ft, over the lots' polygons
    small_pins = [p for p, a in uni.items() if UNIVERSE[a["PROPERTYTYPE"]] in (1, 2, 3)]
    small_tree = STRtree([geo[p][0] for p in small_pins])
    small_area = [uni[p]["PARCELAREA"] or geo[p][1] for p in small_pins]
    radius_m = rules.NEIGHBOUR_FT / FT

    out = []
    dist_counter = Counter()
    for pin, a in uni.items():
        poly, garea, pieces = geo[pin]
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        cen = poly.centroid
        hits = bf_tree.query(cen, predicate="within")
        if len(hits):
            district = bf_names[hits[0]]
        else:  # a sliver gap in the city's layer (Audubon Park, 2026-10-19): take the nearest polygon if it is close
            i, dist = bf_tree.query_nearest(cen, return_distance=True, max_distance=60)
            district = bf_names[i[0]] if len(i) else None
        dist_counter[district] += 1
        short, long_ = oriented_sides(poly)
        corner = len(corners.get(pin, ())) >= 2
        street_side = long_ if corner else short
        near = small_tree.query(cen.buffer(radius_m), predicate="intersects")
        avg350 = sum(small_area[i] for i in near) / len(near) if len(near) else None
        area = a["PARCELAREA"] or round(garea)
        chk = rules.check(area, street_side, district, a["ZONING"], avg350)
        public = bool(PUBLIC.search(a["OWNERNAME"] or ""))
        last = max(sales.get(pin, []), default=None)
        ring = [[round(x - cen.x, 2), round(y - cen.y, 2)] for x, y in poly.exterior.coords] if pieces == 1 else None
        lon, lat = None, None
        row = {
            "pin": pin,
            "address": (a["ADDRESSFORMATTED"] or "").strip(),
            "zip": a["ZIP1"], "neighborhood": a["NEIGHBORHOOD"],
            "area": area, "geom_area": round(garea), "width": round(short, 1), "depth": round(long_, 1),
            "street_side": round(street_side, 1), "corner": corner, "pieces": pieces,
            "district": district, "zoning": a["ZONING"], "built_form_edited": bf_edited,
            "units": UNIVERSE[a["PROPERTYTYPE"]], "building_use": a["BUILDINGUSE"] or a["PROPERTYTYPE"].title(),
            "avg_lot_350": round(avg350) if avg350 else None,
            "owner": a["OWNERNAME"], "homestead": a["HOMESTEAD"] == "Y", "public_owner": public,
            "emv_land": a["LANDVALUE"], "emv_bldg": a["BUILDINGVALUE"], "emv_total": a["TOTALVALUE"],
            "land_per_sqft": round(a["LANDVALUE"] / area, 2) if a["LANDVALUE"] and area else None,
            "year_built": a["YEARBUILT"] or None, "fin_sqft": a["ABOVEGROUNDAREA"], "stories": a["STORIES"], "bedrooms": a["TOTALBEDROOMS"],
            "last_sale_date": last[0].isoformat() if last else None, "last_sale_price": last[1] if last else None,
            "sales": [(d.isoformat(), v) for d, v in sorted(sales.get(pin, []))],
            "ring": ring, "cx": round(cen.x, 1), "cy": round(cen.y, 1),
        }
        row.update(chk)
        out.append(row)
    print(f"rows {len(out):,}; districts {dist_counter.most_common()}", flush=True)

    # lon/lat for the few that need a map pin later: not drawn on the page, so left out here
    # the list: passing lots a builder could buy. Public bodies' lots and lots the city maps as
    # Parks or Production built form pass the arithmetic but are not house lots for sale.
    OFF = ("Parks", "Production")
    q = [r for r in out if r["can_split"] and not r["public_owner"] and r["district"] not in OFF]
    stats_public = sum(1 for r in out if r["can_split"] and (r["public_owner"] or r["district"] in OFF))
    for r in out:
        r["listed"] = r["can_split"] and not r["public_owner"] and r["district"] not in OFF
    q.sort(key=lambda r: (r["area"], r["address"]))  # ordinary house lots that just pass come first
    month_sold = [r for r in q for d, v in r["sales"] if d[:7] == complete_month.strftime("%Y-%m")]
    yr_ago = (complete_month - dt.timedelta(days=365)).strftime("%Y-%m")
    yr_prices = sorted(v for r in q for d, v in r["sales"] if yr_ago <= d[:7] <= complete_month.strftime("%Y-%m"))
    median = yr_prices[len(yr_prices) // 2] if yr_prices else None
    by_month = Counter(d[:7] for r in q for d, v in r["sales"] if d[:7] >= yr_ago and d[:7] <= complete_month.strftime("%Y-%m"))

    # the worked example: a homestead that passes with room to spare, mid-list, deterministic
    passing_homes = [r for r in q if r["homestead"] and r["units"] >= 1 and r["ring"] and not r["corner"]]
    example = passing_homes[len(passing_homes) // 2]
    # the open rows: ten passing house lots of ordinary size spread across districts, no owner or value
    open_rows, seen = [], Counter()
    for r in q:
        if r["ring"] and r["units"] >= 1 and 10000 <= r["area"] <= 16000 and seen[r["district"]] < 4 and r is not example:
            open_rows.append(r); seen[r["district"]] += 1
        if len(open_rows) == 10:
            break
    close_rows = [r for r in out if not r["can_split"] and r["residential_zoning"] and (r["area_close"] or r["width_close"])]

    stats = {
        "built": dt.date.today().isoformat(),
        "built_form_edited": bf_edited,
        "assessor_year": 2026,
        "universe": len(out),
        "qualifying": len(q),
        "qualifying_public_excluded": stats_public,
        "over_acre": sum(1 for r in q if r["area"] > 43560),
        "qualifying_homestead": sum(r["homestead"] for r in q),
        "qualifying_vacant": sum(r["units"] == 0 for r in q),
        "close": len(close_rows),
        "by_district": Counter(r["district"] for r in q).most_common(),
        "by_neighborhood": Counter(r["neighborhood"] for r in q).most_common(),
        "big_lot_blocks": sum(1 for r in q if r["rule_note"]),
        "complete_month": complete_month.isoformat(),
        "complete_month_label": complete_month.strftime("%B %Y"),
        "sold_complete_month": len(month_sold),
        "sold_by_month": sorted(by_month.items()),
        "sold_last_12": len(yr_prices),
        "median_price_last_12": median,
        "median_area": sorted(r["area"] for r in q)[len(q) // 2],
        "median_emv_land": sorted(r["emv_land"] for r in q if r["emv_land"])[len(q) // 2],
        "min_area": rules.MIN_AREA_1_3, "min_width": rules.MIN_WIDTH_1_3,
        "sales_through": max_sale.isoformat(),
    }
    PRIVATE.mkdir(exist_ok=True); BUNDLE.mkdir(exist_ok=True); (SITE / "data").mkdir(parents=True, exist_ok=True)
    json.dump({"stats": stats, "rows": out}, open(PRIVATE / "rows.json", "w"))
    free = lambda r: {k: r[k] for k in FREE if k in r}
    with gzip.open(BUNDLE / "full.json.gz", "wt") as f:
        json.dump({"stats": stats, "rows": [{k: r[k] for k in FREE + PAID if k in r} for r in q]}, f)
    with gzip.open(BUNDLE / "index.json.gz", "wt") as f:
        # two parcels can share one address (8 do, 2026-10-19): the passing one answers the lookup
        json.dump({r["address"]: free(r) for r in sorted(out, key=lambda r: r["can_split"]) if r["address"]}, f)
    json.dump(stats, open(SITE / "data" / "stats.json", "w"))
    json.dump({"example": free(example), "open": [free(r) for r in open_rows]}, open(SITE / "data" / "sample.json", "w"))
    print(json.dumps({k: v for k, v in stats.items() if k not in ("by_neighborhood", "sold_by_month")}, indent=1))
    print("example", example["address"], example["area"], example["street_side"], example["district"])


if __name__ == "__main__":
    main()
