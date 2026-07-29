"""Seed / reset the Tallowa Plant Knowledge Box.

  ../../.venv/bin/python scripts/seed_kb.py            # upload corpus (idempotent)
  ../../.venv/bin/python scripts/seed_kb.py --purge    # delete every resource
  ../../.venv/bin/python scripts/seed_kb.py --status   # counters + per-resource status

Uploads every file in data/corpus via POST /kb/{kb}/upload and records rid-per-file
in data/kb-manifest.json; the app uses that manifest to hard-scope every retrieval
to this demo's own resources.
"""
import argparse
import json
import mimetypes
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "kb-manifest.json"
CORPUS = ROOT / "data" / "corpus"


def env():
    e = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            e[k.strip()] = v.strip()
    return e


def hdr(e):
    return {"X-NUCLIA-SERVICEACCOUNT": f"Bearer {e['KB_TOKEN']}"}


def upload(e, path):
    ctype = mimetypes.guess_type(path.name)[0] or "text/markdown"
    r = requests.post(f"{e['ARAG_HOST']}/api/v1/kb/{e['KB_ID']}/upload",
                      headers={**hdr(e), "X-Filename": path.name, "Content-Type": ctype},
                      data=path.read_bytes(), timeout=300)
    r.raise_for_status()
    return r.json()["uuid"]


def list_resources(e):
    out, page = [], 0
    while True:
        r = requests.get(f"{e['ARAG_HOST']}/api/v1/kb/{e['KB_ID']}/resources",
                         params={"page": page, "size": 100}, headers=hdr(e), timeout=60)
        r.raise_for_status()
        d = r.json()
        out += d.get("resources", [])
        if not d.get("pagination", {}).get("more", False) and len(d.get("resources", [])) < 100:
            break
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--purge", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    e = env()

    if args.status:
        c = requests.get(f"{e['ARAG_HOST']}/api/v1/kb/{e['KB_ID']}/counters",
                         headers=hdr(e), timeout=60).json()
        print(f"counters: {c}")
        res = list_resources(e)
        from collections import Counter
        states = Counter((r.get("metadata") or {}).get("status", "?") for r in res)
        print(f"{len(res)} resources: {dict(states)}")
        for r in res:
            st = (r.get("metadata") or {}).get("status", "?")
            if st != "PROCESSED":
                print(f"  {st:10s} {r.get('title')}")
        return

    if args.purge:
        res = list_resources(e)
        for r in res:
            requests.delete(f"{e['ARAG_HOST']}/api/v1/kb/{e['KB_ID']}/resource/{r['id']}",
                            headers=hdr(e), timeout=60)
        print(f"deleted {len(res)} resources")
        if MANIFEST.exists():
            MANIFEST.unlink()
        return

    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    for path in sorted(CORPUS.glob("*.md")):
        if path.name in manifest:
            continue
        rid = upload(e, path)
        manifest[path.name] = rid
        print(f"uploaded {path.name} -> {rid}")
        MANIFEST.write_text(json.dumps(manifest, indent=1))
    print(f"manifest: {len(manifest)} resources")


if __name__ == "__main__":
    main()
