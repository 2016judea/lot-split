// GET /api/data -> the full table (private/bundle/full.json.gz), gzipped JSON.
// Password in the x-password header (or ?pw=). The data is bundled with this function
// (api/_full/, uploaded by scripts/deploy.py from private/bundle/), never in public site/.
const fs = require("fs");
const path = require("path");
const { checkPassword, nonceIsPaid, open } = require("./_lib");

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
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("X-Access", ok.kind);
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Content-Encoding", "gzip");
  res.status(200).end(FULL_GZ);
};
