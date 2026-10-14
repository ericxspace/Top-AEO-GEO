#!/usr/bin/env python3
"""run_scan.py: the monthly full-site GEO scan as one sequential pipeline (used by routine aeo-geo-scan).

Phases (run them one at a time; each stays under ~10 minutes; NEVER run two in parallel,
Shopify answers a doubled request rate with HTTP 429):
  python -I run_scan.py --phase botview   [--scan-dir DIR]   ~7 min: ~60 URLs x 10 bots -> bot_view.json
  python -I run_scan.py --phase lint      [--scan-dir DIR]   ~10 min: every product/collection/article -> passages/
  python -I run_scan.py --phase scorecard [--scan-dir DIR]   scorecard.json/.md + delta vs previous scan
Inputs it reads from the scan root (default 18-aeo-geo/geo-scans/):
  ai-landing.txt   product handles engines send traffic to (one per line; refreshed from the citation log)
  targets.json     {"<handle>": "<prompt-bank phrase the page must own>"} for --target lint checks
entity.json is filled by the routine/human from references/entity-template.json before the scorecard phase.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rrgeo_common import fetch  # noqa: E402

PROJECT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
DEFAULT_ROOT = os.path.join(PROJECT, "18-aeo-geo", "geo-scans")


def locs(url):
    r = fetch(url)
    time.sleep(0.3)
    return [u.replace("&amp;", "&") for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r["body"])] if r["status"] == 200 else []


def sitemap(base):
    out = {"products": [], "collections": [], "articles": [], "pages": []}
    for child in locs(base + "/sitemap.xml"):
        for kind in out:
            if f"sitemap_{kind}" in child:
                out[kind] += locs(child)
    out["products"] = [u for u in out["products"] if "/products/" in u]
    out["collections"] = [u for u in out["collections"] if "/collections/" in u]
    out["articles"] = [u for u in out["articles"] if u.count("/") >= 5]
    return out


def read_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def run(cmd):
    print("$", " ".join(cmd[2:4]), "...", flush=True)
    return subprocess.run([sys.executable, "-I"] + cmd[1:], capture_output=True, text=True, encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", required=True, choices=["botview", "lint", "scorecard"])
    ap.add_argument("--base", default="https://retroradius.com")
    ap.add_argument("--scan-root", default=DEFAULT_ROOT)
    ap.add_argument("--scan-dir", help="default: <scan-root>/<today>")
    ap.add_argument("--delay", type=float, default=0.35)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = a.base.rstrip("/")
    scan_dir = a.scan_dir or os.path.join(a.scan_root, dt.date.today().isoformat())
    os.makedirs(os.path.join(scan_dir, "passages"), exist_ok=True)

    if a.phase == "botview":
        sm = sitemap(base)
        landing = [base + "/products/" + h for h in read_lines(os.path.join(a.scan_root, "ai-landing.txt"))]
        urls = ([base + "/"] + sm["pages"]
                + [f"{base}/policies/{p}" for p in ("shipping-policy", "refund-policy", "privacy-policy", "terms-of-service")]
                + landing + [u for u in sm["products"] if u not in landing][:5]
                + sm["collections"] + sm["articles"][:8])
        urls = list(dict.fromkeys(urls))
        uf = os.path.join(scan_dir, "botview-urls.txt")
        with open(uf, "w", encoding="utf-8") as f:
            f.write("\n".join(urls) + "\n")
        r = run(["", os.path.join(HERE, "bot_view.py"), "--urls-file", uf, "--delay", str(a.delay),
                 "--out", os.path.join(scan_dir, "bot_view.json")])
        print(r.stdout[-3000:], r.stderr[-1500:])
        sys.exit(r.returncode)

    if a.phase == "lint":
        sm = sitemap(base)
        targets = {}
        tp = os.path.join(a.scan_root, "targets.json")
        if os.path.exists(tp):
            targets = json.load(open(tp, encoding="utf-8"))
        jobs = ([(u, "col") for u in sm["collections"]] + [(u, "blog") for u in sm["articles"]]
                + [(u, "pdp") for u in sm["products"]])
        ok, failed = 0, []
        for u, pre in jobs:
            h = u.rstrip("/").split("/")[-1].split("?")[0]
            cmd = ["", os.path.join(HERE, "passage_lint.py"), u, "--out", os.path.join(scan_dir, "passages", f"{pre}-{h}.json")]
            if h in targets:
                cmd += ["--target", targets[h]]
            r = run(cmd)
            if r.returncode == 0:
                ok += 1
            else:
                failed.append(u)
            time.sleep(a.delay)
        print(f"lint: {ok}/{len(jobs)} pages ok; failed: {failed[:20]}")
        sys.exit(0 if not failed else 1)

    if a.phase == "scorecard":
        r = run(["", os.path.join(HERE, "scorecard.py"), "--scan-dir", scan_dir])
        print(r.stdout[-6000:], r.stderr[-1500:])
        sys.exit(r.returncode)


if __name__ == "__main__":
    main()
