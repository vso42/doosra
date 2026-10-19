#!/usr/bin/env python3
"""Save liqind's chain list and every pair it lists, then write data/pairs.json for build.py.

Public read-only liqind API: /api/chains, then /api/overview paged at its 2000-row limit. Each response is kept under
data/raw/ with its request, fetch time and HTTP status. pairs.json keeps the pairs whose liqind status is in
INCLUDE_STATUSES ("active": liqind routes them; delisted pairs and pairs liqind has no curve for, such as PTs, RWAs and
stock tokens, are left out) and the chains that have at least one of them. Standard library only.
Runs from the IDE Run button.
"""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://liqind-n3txfo-91eea3-92-113-27-239.sslip.io"
RAW = ROOT / "data" / "raw"
OUTPUT = ROOT / "data" / "pairs.json"
INCLUDE_STATUSES = {"active"}
PAGE = 2000  # /api/overview's maximum limit
# liqind chain slug -> display name; a slug not listed falls back to its title case and is reported.
DISPLAY_NAMES = {
    "ethereum": "Ethereum", "arbitrum": "Arbitrum", "base": "Base", "optimism": "Optimism", "polygon": "Polygon",
    "avalanche": "Avalanche", "bsc": "BNB Chain", "gnosis": "Gnosis", "linea": "Linea", "scroll": "Scroll",
    "zksync": "ZKsync", "mantle": "Mantle", "megaeth": "MegaETH", "monad": "Monad", "plasma": "Plasma", "ink": "Ink",
    "sonic": "Sonic", "celo": "Celo", "metis": "Metis", "soneium": "Soneium", "unichain": "Unichain",
    "hyperevm": "HyperEVM", "katana": "Katana", "xlayer": "X Layer", "arc": "Arc",
}
PAIR_FIELDS = ("pair_id", "chain_id", "chain", "collateral", "debt", "collateral_addr", "debt_addr", "tier", "status",
               "collateral_supply_usd", "run_set")


def fetch(path, name, **params):
    """GET path?params, saved as data/raw/<name>; returns the response body. Raises unless HTTP 200."""
    query = urllib.parse.urlencode(params)
    url = BASE + path + ("?" + query if query else "")
    for attempt in range(3):
        fetched = datetime.now(timezone.utc).isoformat()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "doosra-site/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=60) as response:
                status, text = response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            status, text = error.code, error.read().decode()
        except (urllib.error.URLError, TimeoutError) as error:
            status, text = None, str(error)
        if status not in (None, 429, 500, 502, 503, 504):
            break
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        body = text
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / name).write_text(json.dumps({"request": {"path": path, "params": params, "url": url},
                                        "fetched_at_utc": fetched, "http_status": status, "response": body}, indent=1))
    if status != 200:
        raise RuntimeError(f"{url}: HTTP {status}: {str(body)[:300]}")
    return body


def main():
    chains = fetch("/api/chains", "chains.json")
    chain_ids = {chain["name"]: chain["chain_id"] for chain in chains}
    rows, total, refreshed = [], None, None
    while total is None or len(rows) < total:
        page = fetch("/api/overview", f"overview-{len(rows):06d}.json", sort="pair_id", order="asc", limit=PAGE,
                     offset=len(rows))
        total, refreshed = page["total"], page.get("refreshed_at")
        if not page["rows"]:
            break
        rows.extend(page["rows"])
    ids = [row["pair_id"] for row in rows]
    if len(rows) != total or len(set(ids)) != len(ids):
        raise RuntimeError(f"overview returned {len(rows)} rows ({len(set(ids))} distinct) for total {total}")

    kept = [{field: row.get(field) for field in PAIR_FIELDS} for row in rows if row["status"] in INCLUDE_STATUSES]
    for pair in kept:
        if chain_ids.get(pair["chain"], pair["chain_id"]) != pair["chain_id"]:
            raise RuntimeError(f"pair {pair['pair_id']}: chain {pair['chain']} id {pair['chain_id']} differs from "
                               f"/api/chains ({chain_ids[pair['chain']]})")
    per_chain = Counter(pair["chain"] for pair in kept)
    unnamed = sorted(slug for slug in per_chain if slug not in DISPLAY_NAMES)
    names = {slug: DISPLAY_NAMES.get(slug, slug.title()) for slug in per_chain}
    order = sorted(per_chain, key=lambda slug: (-per_chain[slug], names[slug]))
    output = {
        "source": BASE + "/api/overview",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "liqind_refreshed_at": refreshed,
        "include_statuses": sorted(INCLUDE_STATUSES),
        "chains": [{"slug": slug, "chain_id": next(p["chain_id"] for p in kept if p["chain"] == slug),
                    "name": names[slug], "pairs": per_chain[slug]} for slug in order],
        "pairs": kept,
    }
    OUTPUT.write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n")

    listed = Counter(row["chain"] for row in rows)
    print(f"liqind lists {len(rows)} pairs on {len(listed)} chains (overview refreshed {refreshed}); "
          f"kept {len(kept)} with status in {sorted(INCLUDE_STATUSES)} on {len(per_chain)} chains -> {OUTPUT}")
    for slug in sorted(listed, key=lambda s: (-per_chain.get(s, 0), s)):
        statuses = Counter(row["status"] for row in rows if row["chain"] == slug)
        left_out = ", ".join(f"{status} {n}" for status, n in sorted(statuses.items()) if status not in INCLUDE_STATUSES)
        print(f"  {names.get(slug, slug):<12} kept {per_chain.get(slug, 0):>4} of {listed[slug]:>4}"
              + (f"   left out: {left_out}" if left_out else ""))
    not_listed = sorted(chain["name"] for chain in chains if chain["name"] not in listed)
    if not_listed:
        print(f"  chains in /api/chains without pairs: {', '.join(not_listed)}")
    if unnamed:
        print(f"  no display name for: {', '.join(unnamed)} (title case used; add them to DISPLAY_NAMES)")


if __name__ == "__main__":
    main()
