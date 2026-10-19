// GET /api/data -> the full table (private/bundle/full.json.gz), gzipped JSON.
// Password in the x-password header (or ?pw=). The data is bundled with this function
// (api/_full/, uploaded by scripts/deploy.py from private/bundle/), never in public site/.
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { checkPassword, nonceIsPaid, open } = require("./_lib");

// The refresh: every unlock merges in the sales Hennepin County has recorded since the build,
// straight from its live parcel layer (last sale per parcel, month grain). Paged to exhaustion:
// the layer caps a page at 2,000 rows and says so only with exceededTransferLimit.
const HENNEPIN = "https://gis.hennepin.us/arcgis/rest/services/HennepinData/LAND_PROPERTY/MapServer/1/query";
const DAY = 12 * 3600 * 1000;
let LIVE = null; // { at, body }
async function liveSales(sinceYm) {
  const out = [];
  for (let offset = 0; offset < 20000; offset += 2000) {
    const q = new URLSearchParams({ where: `MUNIC_CD='01' AND SALE_DATE>='${sinceYm}' AND SALE_PRICE>0 AND SALE_CODE NOT IN ('P','Q')`,
      outFields: "PID,SALE_DATE,SALE_PRICE", orderByFields: "OBJECTID", resultOffset: offset, resultRecordCount: 2000,
      returnGeometry: "false", f: "json" });
    const r = await fetch(`${HENNEPIN}?${q}`, { signal: AbortSignal.timeout(8000) });
    const j = await r.json();
    if (j.error) throw new Error(j.error.message);
    out.push(...j.features.map((f) => f.attributes));
    if (!j.exceededTransferLimit || !j.features.length) break;
  }
  return out;
}
async function refreshed(gz) {
  if (LIVE && Date.now() - LIVE.at < DAY) return LIVE.body;
  const full = JSON.parse(zlib.gunzipSync(gz));
  const since = full.stats.sales_through_ym;
  let added = 0;
  try {
    const byPin = new Map(full.rows.map((r) => [r.pin, r]));
    for (const a of await liveSales(since)) {
      const r = byPin.get(a.PID); if (!r) continue;
      const d = `${a.SALE_DATE.slice(0, 4)}-${a.SALE_DATE.slice(4, 6)}-01`;
      if (!r.last_sale_date || d > r.last_sale_date) { r.last_sale_date = d; r.last_sale_price = a.SALE_PRICE; r.new_sale = true; added++; }
    }
    full.stats.refreshed_at = new Date().toISOString();
    full.stats.new_sales_since_build = added;
  } catch (e) {
    console.error("[data] live sales refresh failed, serving the build:", e.message);
    full.stats.refreshed_at = null;
  }
  LIVE = { at: Date.now(), body: zlib.gzipSync(JSON.stringify(full)) };
  return LIVE.body;
}

const DIR = process.env.FULL_DIR || path.join(__dirname, "_full");
let FULL_GZ = null, PASSES = null;

module.exports = async (req, res) => {
  const pw = req.headers["x-password"] || req.query.pw;
  const ok = checkPassword(pw);
  if (!ok) return res.status(401).json({ error: "That password didn't match. Check the email from Brick & Mortar, or reply to it for help." });
  try {
    if (ok.kind === "paid" && !(await nonceIsPaid(ok.nonce))) return res.status(402).json({ error: "That password's payment hasn't gone through. If you just paid, wait a minute and try again." });
  } catch (e) {
    console.error("[data] paid check:", e.message);
    return res.status(502).json({ error: "Couldn't check the password right now. Try again in a minute." });
  }
  if (ok.kind === "comp") { try { PASSES ??= JSON.parse(open(fs.readFileSync(path.join(DIR, "passes.json"))).toString("utf8")); } catch { PASSES = {}; } }
  console.log(`[unlock] ${ok.kind} ${ok.kind === "comp" ? PASSES[ok.nonce] || "label unknown " + ok.nonce : ok.nonce}`);
  FULL_GZ ??= open(fs.readFileSync(path.join(DIR, "full.json.gz")));
  const body = process.env.NO_LIVE ? FULL_GZ : await refreshed(FULL_GZ);
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("X-Access", ok.kind);
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Content-Encoding", "gzip");
  res.status(200).end(body);
};
