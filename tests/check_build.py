#!/usr/bin/env python3
"""Check build.py on published figures: the number formats, the band cells and the per-chain pages rendered from the
synthetic tests/fixtures/bands.sample.json (built into .preview/sample-docs/, never docs/), and that bands.json mistakes
stop the build with a clear message. Expected strings are written out by hand, not computed with build.py's own functions.
Standard library only. Runs from the IDE Run button; exit status 1 if a check fails.
"""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build  # noqa: E402

PREVIEW = ROOT / ".preview"
SAMPLE = ROOT / "tests" / "fixtures" / "bands.sample.json"
failures = 0


def check(name, ok, detail=""):
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


# number formats: USD to 3 significant digits with K/M/B/T; token amounts to 4, grouped below 10,000
for value, expected in [(2400000, "$2.4M"), (12000000, "$12M"), (120000000, "$120M"), (999600, "$1M"), (999.6, "$1K"),
                        (1234.5, "$1.23K"), (950, "$950"), (0, "$0"), (1.5e12, "$1.5T"), (4212345, "$4.21M")]:
    check(f"usd({value})", build.usd(value) == expected, f"{build.usd(value)!r}, expected {expected!r}")
for value, expected in [(1000, "1,000"), (1733.2, "1,733"), (9999.4, "9,999"), (50000, "50K"), (31063952, "31.06M"),
                        (0.5, "0.5"), (1.25, "1.25"), (0.012346, "0.01235"), (12.5, "12.5"), (99999.5, "100K")]:
    check(f"token_amount({value})", build.token_amount(value) == expected,
          f"{build.token_amount(value)!r}, expected {expected!r}")

# the synthetic publication rendered
built = build.build(SAMPLE, PREVIEW / "sample-docs")
page = built["page"]
check("summary: updated time and published count", "Updated 2026-10-18 08:00 UTC" in page and built["published"] == 3,
      f"{built['when']}; {built['published']} pairs")
check("unknown pair id left out and reported", built["unknown"] == [999999], str(built["unknown"]))
check("legend shown once figures are published", build.LEGEND.strip() in page)
check("every liqind pair still listed", page.count('<div class="r" role="row"') == built["pairs"] == 953,
      f"{page.count('<div class=\"r\" role=\"row\"')} rows")
check("bands 1, 2, 3, 5 and 10 only, no More menu or more.json",
      re.findall(r'data-band="(\d+)"', page) == ["1", "2", "3", "5", "10"] and "band-more" not in page
      and not (PREVIEW / "sample-docs" / "more.json").exists(), str(re.findall(r'data-band="(\d+)"', page)))

# pages: 10 pairs per chain shown, the rest of each chain's rows hidden until paged to
per_chain = {}
for pair in json.loads((ROOT / "data" / "pairs.json").read_text())["pairs"]:
    per_chain[pair["chain"]] = per_chain.get(pair["chain"], 0) + 1
first_pages = sum(min(10, n) for n in per_chain.values())
hidden_rows = len(re.findall(r'<div class="r" role="row" data-id="\d+" data-q="[^"]*" hidden>', page))
check("first page of every chain visible, other rows hidden", hidden_rows == 953 - first_pages,
      f"{953 - hidden_rows} visible ({first_pages} expected), {hidden_rows} hidden")
for current, total, expected in [(1, 45, [1, 2, 3, 4, 5, 0, 45]), (4, 45, [1, 2, 3, 4, 5, 0, 45]),
                                 (5, 45, [1, 0, 4, 5, 6, 0, 45]), (23, 45, [1, 0, 22, 23, 24, 0, 45]),
                                 (42, 45, [1, 0, 41, 42, 43, 44, 45]), (45, 45, [1, 0, 41, 42, 43, 44, 45]),
                                 (3, 7, [1, 2, 3, 4, 5, 6, 7]), (1, 2, [1, 2])]:
    got = build.page_window(current, total)
    check(f"page_window({current}, {total})", got == expected, f"{got}, expected {expected}")
ethereum_pager = re.search(r'<div class="pg" role="cell" aria-label="Ethereum pages">(.*?)</div>', page).group(1)
expected_pager = ('<button type="button" class="pb" data-to="prev" aria-label="Previous page" disabled>‹</button>'
                  '<button type="button" class="pb" data-to="1" aria-label="Page 1" aria-current="page">1</button>'
                  '<button type="button" class="pb" data-to="2" aria-label="Page 2">2</button>'
                  '<button type="button" class="pb" data-to="3" aria-label="Page 3">3</button>'
                  '<button type="button" class="pb" data-to="4" aria-label="Page 4">4</button>'
                  '<button type="button" class="pb" data-to="5" aria-label="Page 5">5</button>'
                  '<span class="gap" aria-hidden="true">…</span>'
                  '<button type="button" class="pb" data-to="45" aria-label="Page 45">45</button>'
                  '<button type="button" class="pb" data-to="next" aria-label="Next page">›</button>'
                  '<span class="pr">1–10 of 446</span>')
check("Ethereum pager: pages 1-5 … 45, range 1-10 of 446", ethereum_pager == expected_pager, ethereum_pager[:200])
check("a chain of 10 or fewer pairs has no pager (Ink, 8)",
      re.search(r'data-chain="ink".*?<div class="pgr" role="row" hidden>', page) is not None)


def cells(pair_id):
    row = re.search(rf'<div class="r" role="row" data-id="{pair_id}" [^>]*>.*?</div></div>', page)
    return {m.group(1): (m.group(2), m.group(3)) for m in
            re.finditer(r'<div class="c b(\d+)(?: na)?" role="cell"(?: title="([^"]*)")?>(.*?)</div>', row.group(0))}


INTERPOLATED = "Interpolated between two adjacent verified sizes"
expected_cells = {
    6: {"1": (f"{INTERPOLATED} · block 26,211,593", "$2.4M<small>1,000 WETH</small>"),
        "2": (f"{INTERPOLATED} · block 26,211,593", "$4.8M<small>2,000 WETH</small>"),
        "3": ("Largest verified size inside the band · block 26,211,593", "$7.2M<small>3,000 WETH</small>"),
        "5": (f"{INTERPOLATED} · block 26,211,593", "$12M<small>5,000 WETH</small>"),
        "10": ("Band not reached at the largest verified size · block 26,211,593", "≥ $120M<small>≥ 50K WETH</small>")},
    810: {"1": ("The smallest verified size already exceeds the band", "&lt; $50K<small>&lt; 0.5 BTC.b</small>"),
          "2": (INTERPOLATED, "$125K<small>1.25 BTC.b</small>"), "3": (None, "—"),
          "5": (INTERPOLATED, "$1.25M<small>12.5 BTC.b</small>"), "10": (None, "—")},
    681: {"1": (None, "—"), "2": (INTERPOLATED, "$1.23K<small>0.01235 WBTC</small>"), "3": (None, "—"),
          "5": (None, "—"), "10": (None, "—")},
    685: {"1": (None, "—"), "2": (None, "—"), "3": (None, "—"), "5": (None, "—"), "10": (None, "—")},
}
for pair_id, expected in expected_cells.items():
    got = cells(pair_id)
    check(f"pair {pair_id}: band cells", got == expected, "" if got == expected else f"got {got}, expected {expected}")

# mistakes in a bands file stop the build, naming the problem
base = {"updated": "2026-10-18T08:00:00Z", "pairs": {"6": {"bands": {
    "1": {"amount": 1, "usd": 2400, "kind": "interpolated"}, "2": {"amount": 2, "usd": 4800, "kind": "interpolated"}}}}}
cases = [
    ("a wider band with a smaller amount", ("pairs", "6", "bands", "2", "amount"), 0.5, "below the narrower band"),
    ("an unknown kind", ("pairs", "6", "bands", "2", "kind"), "guess", "kind must be one of"),
    ("a negative amount", ("pairs", "6", "bands", "1", "amount"), -1, "finite non-negative"),
    ("a NaN usd", ("pairs", "6", "bands", "1", "usd"), float("nan"), "finite non-negative"),
    ("a band of 4%", ("pairs", "6", "bands", "4"), {"amount": 3, "usd": 9600, "kind": "measured"},
     "bands are 1, 2, 3, 5 or 10 percent"),
    ("a band of 16%", ("pairs", "6", "bands", "16"), {"amount": 3, "usd": 9600, "kind": "measured"},
     "bands are 1, 2, 3, 5 or 10 percent"),
    ("an update time without offset", ("updated",), "2026-10-18T08:00:00", "needs a UTC offset"),
    ("a pair key that is not an id", ("pairs", "WETH"), {"bands": {}}, "is not a liqind pair id"),
    ("a negative block", ("pairs", "6", "block"), -5, "block must be a positive integer"),
]
for name, path, value, message in cases:
    data = json.loads(json.dumps(base))
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    bad = PREVIEW / "bad-bands.json"
    bad.write_text(json.dumps(data))
    try:
        build.build(bad, PREVIEW / "bad-docs")
        check(f"refuses {name}", False, "the build went through")
    except ValueError as error:
        check(f"refuses {name}", message in str(error), str(error))

print(f"sample site in {PREVIEW / 'sample-docs'}")
sys.exit(1 if failures else 0)
