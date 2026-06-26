#!/usr/bin/env python3
"""Sync the canonical label taxonomy (labels.yml) to every repo in the org.

Idempotent: creates missing labels, updates colour/description drift, and (only
with PRUNE=1) deletes labels not in the manifest. Never prunes by default so a
repo's bespoke labels survive. All access via `gh`; needs Issues:write +
Metadata:read across the org.

Env:
  ORG       org login (default: SecondMouseAU)
  PRUNE     "1" to delete labels absent from labels.yml
  DRY_RUN   "1" to log intended changes without mutating
"""
import json
import os
import subprocess
import sys
from urllib.parse import quote

import yaml

ORG = os.environ.get("ORG", "SecondMouseAU")
PRUNE = os.environ.get("PRUNE") == "1"
DRY = os.environ.get("DRY_RUN") == "1"
HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "..", "labels.yml")


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0 and check:
        sys.stderr.write(f"gh {' '.join(args)} failed:\n{r.stderr}\n")
        raise SystemExit(1)
    return r.stdout.strip(), r.returncode


def gh_json(*args):
    out, rc = gh(*args)
    return json.loads(out) if (rc == 0 and out) else None


def load_manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    out = {}
    for e in data:
        out[e["name"]] = {"color": str(e["color"]).lstrip("#"),
                          "description": e.get("description", "")}
    return out


def repos():
    rs = gh_json("api", "--paginate", f"orgs/{ORG}/repos?per_page=100&type=all") or []
    return [r["name"] for r in rs if not r.get("archived")]


def existing_labels(repo):
    ls = gh_json("api", "--paginate", f"repos/{ORG}/{repo}/labels?per_page=100") or []
    return {l["name"]: {"color": (l.get("color") or "").lstrip("#"),
                        "description": l.get("description") or ""} for l in ls}


def create(repo, name, spec):
    gh("api", "-X", "POST", f"repos/{ORG}/{repo}/labels",
       "-f", f"name={name}", "-f", f"color={spec['color']}",
       "-f", f"description={spec['description']}", check=False)


def update(repo, name, spec):
    # the existing label name goes in the path and must be URL-encoded (spaces, :)
    gh("api", "-X", "PATCH", f"repos/{ORG}/{repo}/labels/{quote(name, safe='')}",
       "-f", f"new_name={name}", "-f", f"color={spec['color']}",
       "-f", f"description={spec['description']}", check=False)


def delete(repo, name):
    gh("api", "-X", "DELETE", f"repos/{ORG}/{repo}/labels/{quote(name, safe='')}", check=False)


def main():
    desired = load_manifest()
    print(f"{len(desired)} canonical labels; org {ORG}")
    created = updated = pruned = 0
    for repo in repos():
        have = existing_labels(repo)
        for name, spec in desired.items():
            cur = have.get(name)
            if cur is None:
                print(f"  [{repo}] + {name}")
                if not DRY:
                    create(repo, name, spec)
                created += 1
            elif cur["color"] != spec["color"] or cur["description"] != spec["description"]:
                print(f"  [{repo}] ~ {name}")
                if not DRY:
                    update(repo, name, spec)
                updated += 1
        if PRUNE:
            for name in have:
                if name not in desired:
                    print(f"  [{repo}] - {name}")
                    if not DRY:
                        delete(repo, name)
                    pruned += 1
    print(f"Done — created {created}, updated {updated}, pruned {pruned}"
          + (" [dry-run]" if DRY else ""))


if __name__ == "__main__":
    main()
