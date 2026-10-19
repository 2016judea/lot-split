// Local server for driving the site: static files from site/, the /api/* handlers run in-process
// with the paid bundle at private/bundle (FULL_DIR), and /for/<token>/ rewritten to index.html
// as vercel.json does. node scripts/dev_server.js [port]
const http = require("http");
const fs = require("fs");
const path = require("path");
const url = require("url");

const SITE = path.join(__dirname, "..", "site", "public");
const API = path.join(__dirname, "..", "site", "api");
process.env.FULL_DIR = path.join(__dirname, "..", "private", "bundle");
process.env.SITE_URL = process.env.SITE_URL || "http://localhost:" + (process.argv[2] || 8787);
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json", ".css": "text/css", ".webp": "image/webp", ".svg": "image/svg+xml" };

http.createServer(async (req, res) => {
  const u = url.parse(req.url, true);
  let p = u.pathname;
  if (p.startsWith("/api/")) {
    const name = p.slice(5).replace(/\/$/, "");
    if (name.startsWith("_")) { res.writeHead(404); return res.end(); }
    let handler;
    try { handler = require(path.join(API, name + ".js")); } catch (e) { res.writeHead(404); return res.end("no such api"); }
    req.query = u.query;
    if (req.method === "POST" && !handler.config) {
      const chunks = []; for await (const c of req) chunks.push(c);
      try { req.body = JSON.parse(Buffer.concat(chunks).toString() || "{}"); } catch { req.body = {}; }
    }
    const r = {
      status(c) { res.statusCode = c; return r; },
      setHeader(k, v) { res.setHeader(k, v); return r; },
      json(o) { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(o)); return r; },
      end(b) { res.end(b); return r; },
    };
    try { await handler(req, r); } catch (e) { res.statusCode = 500; res.end(String(e.message)); }
    return;
  }
  if (/^\/for\/[a-z0-9]{6,16}\/?$/.test(p)) p = "/index.html";
  if (p === "/") p = "/index.html";
  const f = path.join(SITE, p);
  if (!f.startsWith(SITE) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end("not found"); }
  res.setHeader("Content-Type", TYPES[path.extname(f)] || "application/octet-stream");
  fs.createReadStream(f).pipe(res);
}).listen(Number(process.argv[2] || 8787), () => console.log("dev server on", process.env.SITE_URL));
