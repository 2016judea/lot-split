// GET /api/check?q=<address> -> the free slice for ONE lot: the rule check and the two numbers
// that decide it, never owner, value or sale. Exact match first, then up to 6 suggestions.
// Reads api/_full/index.json.gz (every lot in the universe, free fields only; scripts/build.py).
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { open } = require("./_lib");

const DIR = process.env.FULL_DIR || path.join(__dirname, "_full");
let INDEX = null, KEYS = null;

const norm = (s) => String(s || "").toUpperCase().replace(/[.,#]/g, " ").replace(/\s+/g, " ").trim()
  .replace(/\b(STREET)\b/g, "ST").replace(/\b(AVENUE)\b/g, "AVE").replace(/\b(SOUTH)\b/g, "S").replace(/\b(NORTH)\b/g, "N")
  .replace(/\b(EAST)\b/g, "E").replace(/\b(WEST)\b/g, "W").replace(/\b(NORTHEAST)\b/g, "NE").replace(/\b(SOUTHEAST)\b/g, "SE")
  .replace(/\b(BOULEVARD)\b/g, "BLVD").replace(/\b(PARKWAY)\b/g, "PKWY").replace(/\b(ROAD)\b/g, "RD").replace(/\b(DRIVE)\b/g, "DR")
  .replace(/\b(LANE)\b/g, "LN").replace(/\b(PLACE)\b/g, "PL").replace(/\b(TERRACE)\b/g, "TER").replace(/\b(CIRCLE)\b/g, "CIR")
  .replace(/\s*,?\s*MINNEAPOLIS.*$/, "").replace(/\s+MN\b.*$/, "").trim();

function load() {
  if (!INDEX) {
    INDEX = JSON.parse(zlib.gunzipSync(open(fs.readFileSync(path.join(DIR, "index.json.gz")))));
    KEYS = Object.keys(INDEX).map((k) => [norm(k), k]);
  }
}

module.exports = async (req, res) => {
  const q = norm(req.query.q);
  res.setHeader("Cache-Control", "public, max-age=3600");
  if (q.length < 3) return res.status(400).json({ error: "Type a Minneapolis street address." });
  load();
  const exact = KEYS.find(([n]) => n === q);
  if (exact) return res.status(200).json({ lot: INDEX[exact[1]], suggestions: [] });
  const starts = KEYS.filter(([n]) => n.startsWith(q)).slice(0, 6).map(([, k]) => k);
  if (starts.length === 1) return res.status(200).json({ lot: INDEX[starts[0]], suggestions: [] });
  if (starts.length) return res.status(200).json({ lot: null, suggestions: starts });
  const num = q.split(" ")[0];
  const loose = KEYS.filter(([n]) => n.startsWith(num + " ") && q.split(" ").slice(1).every((t) => n.includes(t))).slice(0, 6).map(([, k]) => k);
  if (loose.length === 1) return res.status(200).json({ lot: INDEX[loose[0]], suggestions: [] });
  res.status(200).json({ lot: null, suggestions: loose, miss: loose.length === 0 });
};
