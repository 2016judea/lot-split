#!/usr/bin/env python3
"""Deploy site/ to Vercel production over the REST API (project: the "product" in site/offer.json).

Not the CLI. `vercel deploy --prod` has returned BLOCKED on this account with no
error and no build log, while the same files posted to /v13/deployments went
READY in seconds. A BLOCKED deploy looks exactly like a successful one from the
terminal, so this script polls readyState and exits non-zero on anything but
READY — and you should still curl the live URL for a string only the new build
contains.

Needs VERCEL_TOKEN (bricks/.env has one).
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "site"
TEAM = "team_XnhPzBEcaSfEmZFo9M2isLFY"
PROJECT = json.loads((Path(__file__).resolve().parent.parent / "site" / "public" / "offer.json").read_text())["product"]
SKIP_DIRS = {".git", "node_modules", "out", ".vercel", "__pycache__"}
SKIP_FILES = {".env", ".DS_Store"}
POLL_SECONDS = 3
POLL_LIMIT = 80


def request(url, token, data=None, headers=None):
    head = {"Authorization": f"Bearer {token}"}
    head.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=head)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


BUNDLE = ROOT.parent / "private" / "bundle"  # the paid table: uploaded as api/_full/, read by the functions only


def collect(key):
    """site/public/ is the only static tree (outputDirectory "public"); site/api/ are the functions;
    private/bundle/ goes up SEALED as api/_full/ under a fresh key (scripts/seal.py says why).
    2026-10-19: the first deploy served the root, and /api/%5Ffull/full.json.gz returned the paid list."""
    assert (BUNDLE / "full.json.gz").exists(), "run scripts/build.py: private/bundle/ is what the paywall serves"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from seal import seal
    sealed = Path(tempfile.mkdtemp(prefix="lot-split-sealed-"))
    for path in sorted(BUNDLE.rglob("*")):
        if path.is_file():
            out = sealed / path.relative_to(BUNDLE)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(seal(path.read_bytes(), key))
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.name in SKIP_FILES or "_full" in rel.parts:
            continue
        yield rel, path
    for path in sorted(sealed.rglob("*")):
        if path.is_file():
            yield Path("api/_full") / path.relative_to(sealed), path


def main():
    token = os.environ.get("VERCEL_TOKEN")
    if not token:
        sys.exit("VERCEL_TOKEN is not set.")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from seal import new_key
    key = new_key()
    code, out = request(f"https://api.vercel.com/v10/projects/{PROJECT}/env?teamId={TEAM}&upsert=true", token,
                        data=json.dumps({"key": "BUNDLE_KEY", "value": key.hex(), "type": "encrypted",
                                         "target": ["production", "preview"]}).encode(),
                        headers={"Content-Type": "application/json"})
    if code >= 400:
        sys.exit(f"could not set BUNDLE_KEY: {code} {out}")
    files = []
    total = 0
    for rel, path in collect(key):
        body = path.read_bytes()
        sha = hashlib.sha1(body).hexdigest()
        code, out = request(
            "https://api.vercel.com/v2/files", token, data=body,
            headers={"Content-Type": "application/octet-stream",
                     "x-vercel-digest": sha, "x-vercel-team-id": TEAM},
        )
        if code >= 400:
            sys.exit(f"upload {rel} failed: {code} {out}")
        files.append({"file": str(rel), "sha": sha, "size": len(body)})
        total += len(body)
    print(f"  {len(files)} files, {total:,} bytes")

    payload = json.dumps({
        "name": PROJECT, "project": PROJECT, "target": "production",
        "files": files,
        "projectSettings": {"framework": None, "buildCommand": "echo build", "outputDirectory": "public", "installCommand": "echo skip"},
    }).encode()
    code, out = request(
        f"https://api.vercel.com/v13/deployments?teamId={TEAM}&skipAutoDetectionConfirmation=1",
        token, data=payload, headers={"Content-Type": "application/json"},
    )
    if code >= 400 or out.get("error"):
        sys.exit(f"create failed: {code} {json.dumps(out.get('error'))}")

    url = out["url"]
    print(f"  deploying https://{url}")
    for _ in range(POLL_LIMIT):
        time.sleep(POLL_SECONDS)
        _, d = request(f"https://api.vercel.com/v13/deployments/{url}?teamId={TEAM}", token)
        state = d.get("readyState")
        if state in ("READY", "ERROR", "BLOCKED", "CANCELED"):
            print(f"  {state} {d.get('errorMessage') or ''}")
            _, prj = request(f"https://api.vercel.com/v9/projects/{PROJECT}?teamId={TEAM}", token)
            if not (prj.get("webAnalytics") or {}).get("enabledAt"):
                print("  analytics", request(f"https://api.vercel.com/web/insights/toggle?projectId={prj['id']}&teamId={TEAM}", token,
                                             data=b'{"value":true}', headers={"Content-Type": "application/json"}))
            sys.exit(0 if state == "READY" else 1)
    sys.exit("timed out waiting for the deployment to settle")


if __name__ == "__main__":
    main()
