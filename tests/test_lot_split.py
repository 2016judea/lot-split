"""The suite: the rule check, the build's outputs (free slice never carries a paid field), the
API handlers driven in-process (401 bare, free check serves no paid field), and the page build.
Run: .venv/bin/python -m pytest -q | tee tests/last_run.log"""
import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rules  # noqa: E402
import build  # noqa: E402
import build_site  # noqa: E402

PAID = set(build.PAID) | {"owner", "emv_total", "last_sale_price", "sales", "public_owner"}


# ---- rules ----------------------------------------------------------------------------
def test_split_needs_twice_both_minimums():
    r = rules.check(10000, 80, "Interior 2", "Urban Neighborhood 2", 6000)
    assert r["can_split"] and r["need_area"] == 10000 and r["need_width"] == 80
    assert not rules.check(9999, 80, "Interior 2", "Urban Neighborhood 2", 6000)["can_split"]
    assert not rules.check(10000, 79.9, "Interior 2", "Urban Neighborhood 2", 6000)["can_split"]


def test_big_lot_block_raises_the_minimum_only_in_interior_1_and_2():
    r = rules.check(19000, 100, "Interior 1", "Urban Neighborhood 1", 9500)
    assert r["min_area"] == 9500 and r["need_area"] == 19000 and r["max_area"] == 12350 and r["rule_note"]
    assert not rules.check(18999, 100, "Interior 1", "Urban Neighborhood 1", 9500)["can_split"]
    r3 = rules.check(10000, 80, "Interior 3", "Urban Neighborhood 3", 9500)
    assert r3["min_area"] == 5000 and r3["can_split"] and not r3["rule_note"]


def test_non_residential_zoning_never_passes():
    assert not rules.check(50000, 300, "Corridor 4", "Community Mixed Use", None)["can_split"]
    assert rules.is_residential_zoning("Urban Neighborhood 1") and not rules.is_residential_zoning("Downtown Center")


def test_close_flags_within_ten_percent():
    r = rules.check(9200, 75, "Interior 2", "Urban Neighborhood 2", None)
    assert r["area_close"] and r["width_close"] and not r["can_split"]
    assert not rules.check(8000, 60, "Interior 2", "Urban Neighborhood 2", None)["area_close"]


def test_fourplus_dimensions_follow_table_540_16():
    assert rules.check(9000, 50, "Interior 1", "Urban Neighborhood 1", None)["meets_4plus_dims"]
    assert not rules.check(8999, 50, "Interior 1", "Urban Neighborhood 1", None)["meets_4plus_dims"]
    assert rules.check(7500, 50, "Interior 2", "Urban Neighborhood 2", None)["meets_4plus_dims"]
    assert rules.check(5000, 40, "Interior 3", "Urban Neighborhood 3", None)["meets_4plus_dims"]


# ---- build outputs --------------------------------------------------------------------
@pytest.fixture(scope="module")
def outputs():
    need = [ROOT / "private/rows.json", ROOT / "private/bundle/full.json.gz", ROOT / "private/bundle/index.json.gz",
            ROOT / "site/public/data/stats.json", ROOT / "site/public/data/sample.json"]
    if not all(p.exists() for p in need):
        pytest.skip("run scripts/build.py first")
    return {
        "stats": json.loads((ROOT / "site/public/data/stats.json").read_text()),
        "sample": json.loads((ROOT / "site/public/data/sample.json").read_text()),
        "full": json.load(gzip.open(ROOT / "private/bundle/full.json.gz", "rt")),
        "index": json.load(gzip.open(ROOT / "private/bundle/index.json.gz", "rt")),
    }


def test_free_slice_carries_no_paid_field(outputs):
    for r in outputs["sample"]["open"] + [outputs["sample"]["example"]]:
        assert not (set(r) & PAID), set(r) & PAID
    for r in list(outputs["index"].values())[:5000]:
        assert not (set(r) & PAID), set(r) & PAID


def test_paid_list_is_every_passing_lot_and_only_those(outputs):
    rows = outputs["full"]["rows"]
    assert len(rows) == outputs["stats"]["qualifying"] > 0
    assert all(r["can_split"] for r in rows)
    assert all("owner" in r and "emv_land" in r for r in rows)
    every = json.load(open(ROOT / "private/rows.json"))["rows"]
    assert sum(1 for r in every if r["can_split"]) == len(rows) + outputs["stats"]["qualifying_public_excluded"]
    assert all(outputs["index"][r["address"]]["can_split"] for r in rows)  # a shared address answers with the passing lot


def test_stats_are_derived_from_the_rows(outputs):
    s, rows = outputs["stats"], outputs["full"]["rows"]
    assert s["qualifying_homestead"] == sum(r["homestead"] for r in rows)
    assert s["qualifying_vacant"] == sum(r["units"] == 0 for r in rows)
    assert sorted(x[1] for x in s["by_district"]) and sum(x[1] for x in s["by_district"]) == len(rows)
    assert s["complete_month_label"] in ("June 2026", "July 2026", "August 2026", "September 2026", "October 2026") or s["complete_month"] < s["sales_through"]


def test_example_and_open_rows_pass_and_draw(outputs):
    ex = outputs["sample"]["example"]
    assert ex["can_split"] and ex["ring"] and ex["area"] >= ex["need_area"] and ex["street_side"] >= ex["need_width"]
    assert len(outputs["sample"]["open"]) == 10 and all(r["can_split"] and r["ring"] for r in outputs["sample"]["open"])


# ---- API handlers, in-process ----------------------------------------------------------
NODE = """
process.env.FULL_DIR = %r; process.env.ACCESS_SECRET = "test-secret"; process.env.STRIPE_SECRET_KEY = "sk_test_x";
global.fetch = async () => { throw new Error("no network in the suite"); };
const h = require(%r);
const req = { headers: %s, query: %s, method: "GET" };
let out = { status: 200, headers: {} };
const res = { status(c){ out.status = c; return res; }, setHeader(k,v){ out.headers[k]=v; return res; },
  json(o){ out.body = o; done(); return res; }, end(b){ out.body = b ? b.length : null; done(); return res; } };
function done(){ console.log(JSON.stringify(out)); }
Promise.resolve(h(req, res)).catch(e => { out.status = 599; out.body = e.message; done(); });
"""


def node(handler, headers=None, query=None):
    bundle = str(ROOT / "private/bundle")
    if not (ROOT / "private/bundle/index.json.gz").exists():
        pytest.skip("run scripts/build.py first")
    js = NODE % (bundle, str(ROOT / "site/api" / handler), json.dumps(headers or {}), json.dumps(query or {}))
    p = subprocess.run(["node", "-e", js], capture_output=True, text=True, cwd=ROOT / "site", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_data_is_401_without_a_password():
    assert node("data.js")["status"] == 401
    assert node("data.js", headers={"x-password": "AAAA-BBBB-CCCC"})["status"] == 401


def test_data_opens_to_a_comp_password_minted_under_the_secret():
    import hashlib, hmac
    alpha = "23456789BCDFGHJKMNPQRSTVWXYZ"
    chars = lambda b, n: "".join(alpha[x % len(alpha)] for x in b[:n])
    nonce = "QQQQQ"
    tail = chars(hmac.new(b"test-secret", ("comp:" + nonce).encode(), hashlib.sha256).digest(), 7)
    out = node("data.js", headers={"x-password": nonce + tail})
    assert out["status"] == 200 and out["headers"]["X-Access"] == "comp" and out["body"] > 1000


def test_check_serves_the_free_slice_only(outputs):
    ex = outputs["sample"]["example"]
    out = node("check.js", query={"q": ex["address"].title()})
    assert out["status"] == 200 and out["body"]["lot"]["address"] == ex["address"]
    assert not (set(out["body"]["lot"]) & PAID)
    assert node("check.js", query={"q": "zz"})["status"] == 400
    miss = node("check.js", query={"q": "99999 Nowhere Blvd"})
    assert miss["status"] == 200 and miss["body"]["lot"] is None and miss["body"].get("miss")


def test_check_suggests_on_a_partial_address(outputs):
    ex = outputs["sample"]["example"]
    out = node("check.js", query={"q": ex["address"].split()[0] + " " + ex["address"].split()[1][:3]})
    body = out["body"]
    assert body["lot"] is not None or body["suggestions"]


# ---- page build -----------------------------------------------------------------------
def test_page_builds_with_every_number_filled(outputs):
    html = build_site.build(posthog="<!-- ph -->")
    s = outputs["stats"]
    assert f"{s['qualifying']:,}" in html and s["complete_month_label"] in html
    assert "/_vercel/insights/script.js" in html and "paywall.js" in html
    assert "__" not in html.replace("__proto__", "")
    assert json.dumps(outputs["sample"]["example"]["address"]) in html


def test_shipped_page_matches_the_build(outputs):
    page = ROOT / "site/public/index.html"
    if not page.exists():
        pytest.skip("run scripts/build_site.py")
    assert page.read_text() == build_site.build()


def test_esri_rings_keep_every_outer_part_and_punch_only_real_holes():
    # two clockwise squares (two parts) and one counter-clockwise ring inside the first (a hole)
    a = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]
    b = [[20, 0], [20, 10], [30, 10], [30, 0], [20, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    g = build.esri_polygon([a, b, hole])
    assert g.geom_type == "MultiPolygon" and abs(g.area - 196) < 1e-9
    from shapely.geometry import Point
    assert g.contains(Point(25, 5)) and not g.contains(Point(5, 5))


def test_every_lot_found_its_built_form_district(outputs):
    rows = json.loads((ROOT / "private/rows.json").read_text())["rows"]
    assert sum(r["district"] is None for r in rows) == 0


def test_unlock_merges_new_county_sales_into_the_paid_list(tmp_path):
    """data.js asks Hennepin's live layer for sales since the build and folds them in."""
    import hashlib, hmac
    if not (ROOT / "private/bundle/full.json.gz").exists():
        pytest.skip("run scripts/build.py first")
    full = json.loads(gzip.open(ROOT / "private/bundle/full.json.gz").read())
    pin = full["rows"][0]["pin"]
    alpha = "23456789BCDFGHJKMNPQRSTVWXYZ"
    chars = lambda b, n: "".join(alpha[x % len(alpha)] for x in b[:n])
    pw = "QQQQQ" + chars(hmac.new(b"test-secret", b"comp:QQQQQ", hashlib.sha256).digest(), 7)
    js = f"""
process.env.FULL_DIR = {json.dumps(str(ROOT / "private/bundle"))}; process.env.ACCESS_SECRET = "test-secret";
let asked = "";
global.fetch = async (u) => {{ asked = String(u); return {{ json: async () => ({{ features: [{{ attributes: {{ PID: "{pin}", SALE_DATE: "209901", SALE_PRICE: 123 }} }}] }}) }}; }};
const zlib = require("zlib");
const h = require({json.dumps(str(ROOT / "site/api/data.js"))});
const res = {{ s: 0, status(c){{ this.s = c; return this; }}, setHeader(){{ return this; }}, json(o){{ console.log(JSON.stringify(o)); }},
  end(b){{ const j = JSON.parse(zlib.gunzipSync(b)); const r = j.rows.find(x => x.pin === "{pin}");
    console.log(JSON.stringify({{ s: this.s, asked, r, added: j.stats.new_sales_since_build }})); }} }};
h({{ headers: {{ "x-password": "{pw}" }}, query: {{}} }}, res);
"""
    p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])
    assert out["s"] == 200 and out["added"] == 1
    assert out["r"]["last_sale_date"] == "2099-01-01" and out["r"]["last_sale_price"] == 123 and out["r"]["new_sale"]
    assert "SALE_DATE%3E%3D%27" + full["stats"]["sales_through_ym"] in out["asked"]


def test_split_worth_derives_from_a_fitted_stable_land_curve(outputs):
    s = outputs["stats"]
    assert 0 < s["beta"] < 1 and abs(s["beta_halves"][0] - s["beta_halves"][1]) <= 0.03 and s["beta_n"] > 1000
    assert abs(s["split_multiple"] - 2 ** (1 - s["beta"])) < 0.002
    for r in outputs["full"]["rows"]:
        if r["emv_land"]:
            assert abs(r["split_land_value"] - r["emv_land"] * s["split_multiple"]) <= 1000
            assert abs(r["split_uplift"] - (r["split_land_value"] - r["emv_land"])) <= 1000
    # the free check carries the worth for a passing lot, and nothing for one that fails
    idx = outputs["index"]
    passing = [r for r in idx.values() if r["can_split"]][:50]
    assert passing and all(r["split_uplift"] for r in passing if r.get("split_land_value"))
    assert all(r["split_uplift"] is None for r in list(idx.values())[:2000] if not r["can_split"])
