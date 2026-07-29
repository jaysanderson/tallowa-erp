"""One-time: create the Tallowa Motors demo Knowledge Box + mint its service token.

Reads ARAG_NUA_KEY from the factory .env, creates the KB in the AU zone (the only
zone the key provisions), mints an SOWNER service account + key, and writes the
app's own .env. Token values are never printed.

Run:  ../../.venv/bin/python scripts/provision.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
FACTORY = ROOT.parent.parent

HOST = "https://aws-ap-southeast-2-1.rag.progress.cloud"
ACCOUNT = "86d1adc8-64ef-499b-86d6-72e9fd684ab0"
SLUG = "tallowa-plant"
TITLE = "Tallowa Plant (demo)"


def factory_env():
    e = {}
    for line in (FACTORY / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            e[k.strip()] = v.strip()
    return e


def main():
    if (ROOT / ".env").exists():
        print(".env already exists - KB already provisioned, nothing to do")
        return
    nua = factory_env()["ARAG_NUA_KEY"]
    auth = {"Authorization": f"Bearer {nua}", "Content-Type": "application/json"}

    r = requests.post(f"{HOST}/api/v1/account/{ACCOUNT}/kbs", headers=auth,
                      json={"slug": SLUG, "title": TITLE, "mode": "kb"}, timeout=60)
    if r.status_code == 409:
        print("KB slug already exists; listing to recover id")
        lr = requests.get(f"{HOST}/api/v1/account/{ACCOUNT}/kbs", headers=auth, timeout=60)
        lr.raise_for_status()
        kb_id = next(k["id"] for k in lr.json() if k.get("slug") == SLUG)
    else:
        r.raise_for_status()
        kb_id = r.json()["id"]
    print(f"KB id: {kb_id}")

    r = requests.post(f"{HOST}/api/v1/account/{ACCOUNT}/kb/{kb_id}/service_accounts",
                      headers=auth, json={"title": "tallowa-app", "role": "SOWNER"},
                      timeout=60)
    r.raise_for_status()
    sa_id = r.json()["id"]

    expires = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.post(
        f"{HOST}/api/v1/account/{ACCOUNT}/kb/{kb_id}/service_account/{sa_id}/keys",
        headers=auth, json={"expires": expires}, timeout=60)
    r.raise_for_status()
    token = r.json()["token"]

    c = requests.get(f"{HOST}/api/v1/kb/{kb_id}/counters",
                     headers={"X-NUCLIA-SERVICEACCOUNT": f"Bearer {token}"}, timeout=60)
    c.raise_for_status()
    print(f"token validated: counters = {c.json()}")

    (ROOT / ".env").write_text(
        f"ARAG_HOST={HOST}\nKB_ID={kb_id}\nKB_TOKEN={token}\n"
        f"APP_SECRET=tallowa-demo-signing-secret\n")
    print(".env written (host, kb id, token, app secret)")


if __name__ == "__main__":
    sys.exit(main())
