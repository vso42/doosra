#!/usr/bin/env python3
"""Build the static site into docs/ for GitHub Pages (Settings > Pages > Deploy from a branch > main, /docs).

docs/index.html is the whole page in one file: every liqind pair of data/pairs.json (scripts/fetch_liqind_pairs.py) as a
pre-rendered row, the published execution amounts of data/bands.json in the band columns, src/style.css and src/app.js
inlined. Each chain shows PAGE_SIZE pairs per page: the first page is visible in the HTML with its pager, app.js turns
the pages. The fonts listed in fonts/fonts.json (scripts/fetch_fonts.py) are copied to docs/fonts/.
data/ stays local: besides the page, docs/ gets only data/figures.json, the numbers the page shows.
bands.json is checked strictly (known bands and kinds, finite non-negative figures, amounts that never fall as the band
widens); a pair id liqind no longer lists is reported and left out. Standard library only. Runs from the IDE Run button.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
SRC, DATA, FONTS, OUT = ROOT / "src", ROOT / "data", ROOT / "fonts", ROOT / "docs"
BANDS = [1, 2, 3, 5, 10]  # slippage bands (percent): one chip and one column each
DEFAULT_BAND = 2
PAGE_SIZE = 10  # pairs per page within a chain
# rows a filter brings back: this many in the same frame, then this many per frame. Measured in Firefox on 2026-10-18
# (953 rows): 60 + 100 kept every frame near 9 ms; all at once took 58-66 ms. With pages, a filter shows at most
# PAGE_SIZE rows per chain (about 160), so the first frame usually takes them all.
REVEAL_NOW, REVEAL_PER_FRAME = 60, 100
# bands.json "kind" -> (tooltip, prefix of the figures)
KINDS = {
    "measured": ("Largest verified size inside the band", ""),
    "interpolated": ("Interpolated between two adjacent verified sizes", ""),
    "at_least": ("Band not reached at the largest verified size", "≥ "),
    "below_min": ("The smallest verified size already exceeds the band", "< "),
    "modeled": ("Largest tested full-input model size inside the band; contract execution unverified", ""),
}
LEGEND = " Hover a figure for how it was measured; ≥ marks a band not reached at the largest size tested."
MODEL_LEGEND = (" Figures are the largest passing full-input model sizes tested at each recorded block."
                " Contract execution remains unverified. Hover a figure for its block and timestamp.")
# <style id="sel">: the default band's column tint for the moment before app.js runs; app.js then swaps it for one
# bar behind the selected column
SELECT_DEFAULT = ".b{band}{{background-color:var(--soft)}}#hwrap .b{band}{{color:var(--accent-fg)}}"
CHEVRON = ('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
           'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>')
SUFFIXES = ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K"))


def esc(text):
    return html.escape(str(text), quote=True)


def norm(text):
    """Search form of a name: lower case, ₮ read as t (USD₮0 is found by usdt0). app.js normalizes queries alike."""
    return text.lower().replace("₮", "t")


def initial(symbol):
    """Badge letter as in the design: the first letter, skipping a wrapper W (WETH -> E, WBTC -> B)."""
    return re.sub(r"^W(?=[A-Z]{3})", "", symbol)[:1].upper()


def plural(n, word):
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def significant(value, digits):
    """value to `digits` significant digits in fixed notation, trailing zeros dropped."""
    if value == 0:
        return "0"
    decimals = max(0, digits - 1 - math.floor(math.log10(abs(value))))
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def compact(value, digits):
    """1,234,567 -> 1.23M at 3 digits; plain below 1,000. Rounded first, so 999,700 reads 1M, not 1000K."""
    rounded = float(f"{value:.{digits}g}")
    for scale, suffix in SUFFIXES:
        if rounded >= scale:
            return significant(rounded / scale, digits) + suffix
    return significant(rounded, digits)


def usd(value):
    return "$" + compact(value, 3)


def token_amount(value):
    """Native units, 4 significant digits: grouped below 10,000 (1,733), compact above (12.77K, 31.06M)."""
    if value >= 1e4:
        return compact(value, 4)
    whole, _, fraction = significant(value, 4).partition(".")
    return f"{int(whole):,}" + ("." + fraction if fraction else "")


def number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{where}: needs a finite non-negative number, got {value!r}")
    return float(value)


def snapshot_details(entry, where):
    """Validate optional exact-block metadata without inferring missing state."""
    block, block_hash = entry.get("block"), entry.get("block_hash")
    timestamp = entry.get("block_timestamp_utc")
    if block_hash is not None and (not isinstance(block_hash, str)
            or re.fullmatch(r"0x[0-9a-fA-F]{64}", block_hash) is None):
        raise ValueError(f"{where}: block_hash must be a 32-byte hexadecimal hash")
    if block is None and (block_hash is not None or timestamp is not None):
        raise ValueError(f"{where}: block metadata requires a block number")
    if block is not None and (type(block) is not int or block <= 0):
        raise ValueError(f"{where}: block must be a positive integer, got {block!r}")
    when = None
    if timestamp is not None:
        try:
            when = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
            raise ValueError(f"{where}: block_timestamp_utc must be an ISO 8601 time with a UTC offset") from None
        if when.tzinfo is None:
            raise ValueError(f"{where}: block_timestamp_utc needs a UTC offset")
        when = when.astimezone(timezone.utc)
        epoch = entry.get("block_timestamp")
        if epoch is not None and (type(epoch) is not int or epoch <= 0 or when.timestamp() != epoch):
            raise ValueError(f"{where}: block timestamp differs from its recorded Unix timestamp")
    return block, block_hash, when


def load_chain_snapshots(path=None):
    """Optional recorded heads; an absent file preserves older publications."""
    path = Path(path) if path is not None else DATA / "chain-snapshots.json"
    if not path.exists():
        return {}
    document = json.loads(path.read_text())
    records = {}
    for entry in document["chains"]:
        chain_id = entry.get("chain_id")
        if type(chain_id) is not int or chain_id <= 0 or chain_id in records:
            raise ValueError("chain-snapshots.json: each chain needs a unique positive chain_id")
        if entry.get("status") == "pinned":
            block, block_hash, when = snapshot_details(entry, f"chain-snapshots.json chain {chain_id}")
            if block is None or block_hash is None or when is None:
                raise ValueError(f"chain-snapshots.json chain {chain_id}: pinned heads need block, hash and timestamp")
        records[chain_id] = entry
    return records


def snapshot_title(entry):
    block, _, when = snapshot_details(entry, "snapshot")
    return (f" · block {block:,}" if block else "") + (f" · {when:%Y-%m-%d %H:%M:%S} UTC" if when else "")


def load_pairs():
    listing = json.loads((DATA / "pairs.json").read_text())
    chains = listing["chains"]
    slugs = {chain["slug"] for chain in chains}
    pairs = {}
    for pair in listing["pairs"]:
        if pair["pair_id"] in pairs:
            raise ValueError(f"pairs.json lists pair {pair['pair_id']} twice")
        if pair["chain"] not in slugs:
            raise ValueError(f"pair {pair['pair_id']}: chain {pair['chain']} is not in pairs.json chains")
        pairs[pair["pair_id"]] = pair
    return listing, chains, pairs


def load_bands(pairs, path, chain_snapshots=None):
    """bands.json -> (updated, {pair_id: {band: (main, sub, title)}}, unknown pair ids, {pair_id: the same figures as
    plain numbers for docs/data/figures.json})."""
    document = json.loads(Path(path).read_text())
    updated = document.get("updated")
    if updated is not None:
        updated = datetime.fromisoformat(updated)
        if updated.tzinfo is None:
            raise ValueError("bands.json: 'updated' needs a UTC offset, e.g. 2026-10-18T08:00:00Z")
    figures, unknown, published = {}, [], {}
    allowed = ", ".join(map(str, BANDS[:-1])) + f" or {BANDS[-1]}"
    for key, entry in document.get("pairs", {}).items():
        if not re.fullmatch(r"\d+", key):
            raise ValueError(f"bands.json: pair key {key!r} is not a liqind pair id")
        pair_id = int(key)
        if pair_id not in pairs:
            unknown.append(pair_id)
            continue
        snapshot = dict(entry)
        block, _, _ = snapshot_details(snapshot, f"bands.json pair {pair_id}")
        head = (chain_snapshots or {}).get(pairs[pair_id]["chain_id"])
        # A different historical block is legitimate; never attach another block's time.
        if head and head.get("block") == block:
            for field in ("block_hash", "block_timestamp_utc", "block_timestamp"):
                if snapshot.get(field) is not None and head.get(field) is not None and snapshot[field] != head[field]:
                    raise ValueError(f"bands.json pair {pair_id}: {field} differs from the recorded chain snapshot")
                if snapshot.get(field) is None and head.get(field) is not None:
                    snapshot[field] = head[field]
        metadata = snapshot_title(snapshot)
        symbol, rows, values, previous = pairs[pair_id]["collateral"], {}, {}, None
        for band_key in sorted(entry.get("bands", {}), key=lambda k: int(k) if k.isdigit() else -1):
            where = f"bands.json pair {pair_id} band {band_key}"
            if not band_key.isdigit() or int(band_key) not in BANDS:
                raise ValueError(f"{where}: bands are {allowed} percent")
            figure = entry["bands"][band_key]
            if figure.get("kind") not in KINDS:
                raise ValueError(f"{where}: kind must be one of {sorted(KINDS)}, got {figure.get('kind')!r}")
            amount, value = number(figure.get("amount"), where + " amount"), number(figure.get("usd"), where + " usd")
            if previous and (amount < previous[0] or value < previous[1]):
                raise ValueError(f"{where}: amount {amount} / usd {value} below the narrower band's {previous}")
            previous = (amount, value)
            label, prefix = KINDS[figure["kind"]]
            if figure.get("validation_level") == "per_pool_native_quotes_and_shared_raw_prefix":
                label += " · Per-pool contract quotes and token balances checked; transaction and gas validation pending"
            rows[int(band_key)] = (prefix + usd(value), f"{prefix}{token_amount(amount)} {symbol}",
                                   label + metadata)
            values[band_key] = {"amount": amount, "usd": value, "kind": figure["kind"]}
        if rows:
            figures[pair_id] = rows
            published[pair_id] = {"chain": pairs[pair_id]["chain"], "collateral": symbol, "debt": pairs[pair_id]["debt"],
                                  "block": block, "block_timestamp_utc": snapshot.get("block_timestamp_utc"),
                                  "bands": values}
    return updated, figures, unknown, published


def font_faces():
    """@font-face rules and preload links for fonts/fonts.json, checked against its sha256; files to copy."""
    faces = json.loads((FONTS / "fonts.json").read_text())["faces"]
    rules, preloads, files = [], [], []
    for face in faces:
        data = (FONTS / face["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != face["sha256"]:
            raise ValueError(f"fonts/{face['file']} differs from fonts.json; rerun scripts/fetch_fonts.py")
        url = f"fonts/{face['file']}?v={face['sha256'][:8]}"
        rules.append(f'@font-face{{font-family:"{face["family"]}";font-style:normal;font-weight:{face["weight"]};'
                     f'font-display:swap;src:url({url}) format("woff2");unicode-range:{face["unicode_range"]}}}')
        if face["preload"]:
            preloads.append(f'<link rel="preload" href="{url}" as="font" type="font/woff2" crossorigin>')
        files.append(face["file"])
    return "".join(rules), "\n".join(preloads), files


def cell(css_class, figure):
    """A band cell: USD on top, the sold token's amount below; few elements per row keep restyles cheap."""
    if figure is None:
        return f'<div class="c {css_class} na" role="cell">—</div>'
    main, sub, title = figure
    return f'<div class="c {css_class}" role="cell" title="{esc(title)}">{esc(main)}<small>{esc(sub)}</small></div>'


def row(pair, figures, hidden):
    collateral, debt = pair["collateral"], pair["debt"]
    return (f'<div class="r" role="row" data-id="{pair["pair_id"]}" data-q="{esc(norm(collateral + " " + debt))}"'
            f'{" hidden" if hidden else ""}><div class="c p" role="rowheader"><i aria-hidden="true">'
            f'{esc(initial(collateral))}</i><i aria-hidden="true">{esc(initial(debt))}</i>{esc(collateral)} <b>→</b> '
            f'{esc(debt)}</div>' + "".join(cell(f"b{band}", figures.get(band)) for band in BANDS) + "</div>")


def page_window(current, total):
    """Page numbers shown in a pager, 0 for an ellipsis; always 7 slots once there are more than 7 pages, so the pager
    keeps its width while paging. app.js has the same function."""
    if total <= 7:
        return list(range(1, total + 1))
    if current <= 4:
        return [1, 2, 3, 4, 5, 0, total]
    if current >= total - 3:
        return [1, 0] + list(range(total - 4, total + 1))
    return [1, 0, current - 1, current, current + 1, 0, total]


def pager(page, count):
    """The pager's buttons and range for `count` matching pairs; app.js builds the same markup when paging."""
    pages = math.ceil(count / PAGE_SIZE)
    parts = [f'<button type="button" class="pb" data-to="prev" aria-label="Previous page"'
             f'{" disabled" if page == 1 else ""}>‹</button>']
    for shown in page_window(page, pages):
        current = ' aria-current="page"' if shown == page else ""
        parts.append(f'<button type="button" class="pb" data-to="{shown}" aria-label="Page {shown}"{current}>{shown}</button>'
                     if shown else '<span class="gap" aria-hidden="true">…</span>')
    parts.append(f'<button type="button" class="pb" data-to="next" aria-label="Next page"'
                 f'{" disabled" if page == pages else ""}>›</button>')
    first, last = (page - 1) * PAGE_SIZE + 1, min(page * PAGE_SIZE, count)
    parts.append(f'<span class="pr">{first}–{last} of {count:,}</span>')
    return "".join(parts)


def group(chain, pairs, figures, snapshot=None):
    """One chain: its fold header, its rows (largest collateral market first, then tier and symbols; the first page
    visible) and its pager row, hidden when the chain fits on one page."""
    rows = sorted(pairs, key=lambda p: (-(p["collateral_supply_usd"] or 0), p["collateral"].lower(), p["tier"],
                                        p["debt"].lower()))
    name, slug = chain["name"], chain["slug"]
    searchable = norm(name) if norm(name).replace(" ", "") == slug else norm(f"{name} {slug}")
    paged = len(rows) > PAGE_SIZE
    title = f' title="{esc("Recorded pool state" + snapshot_title(snapshot))}"' if snapshot and snapshot.get("block") else ""
    note = ('<span class="chain-note">Still struggling on bin counting; will provide soon.</span>'
            if slug == "avalanche" else "")
    return (f'<div class="g" role="rowgroup" data-chain="{esc(slug)}" data-name="{esc(searchable)}" data-n="{len(rows)}">'
            f'<div class="gh" role="row"><div role="rowheader"><button class="fold" type="button" aria-expanded="true"{title}>'
            f'<span>{CHEVRON}<span class="ini" aria-hidden="true">{esc(name[:1])}</span>{esc(name)}'
            f'<span class="gn">{plural(len(rows), "pair")}</span>{note}</span></button></div></div>'
            f'<div class="rows">' + "".join(row(p, figures.get(p["pair_id"], {}), k >= PAGE_SIZE)
                                             for k, p in enumerate(rows)) + "</div>"
            f'<div class="pgr" role="row"{"" if paged else " hidden"}><div class="pg" role="cell" '
            f'aria-label="{esc(name)} pages">{pager(1, len(rows)) if paged else ""}</div></div></div>')


def stylesheet(faces):
    css = (SRC / "style.css").read_text()
    css += (f".r{{grid-template-columns:var(--pw) repeat({len(BANDS)},var(--bw))}}"
            f".inner{{min-width:calc(var(--pmin) + {len(BANDS)} * var(--bmin))}}")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s*([{};])\s*", r"\1", re.sub(r"\s+", " ", css)).strip()
    return faces + css


def fill(template, values):
    used = set(re.findall(r"\{\{(\w+)\}\}", template))
    if used != set(values):
        raise ValueError(f"template placeholders {sorted(used)} differ from the values {sorted(values)}")
    return re.sub(r"\{\{(\w+)\}\}", lambda match: values[match.group(1)], template)


def validate_newer_publication(bands_path, results_path):
    """Keep older numerical outputs out of the active newer-only publication."""
    bands = json.loads(Path(bands_path).read_bytes())
    results = json.loads(Path(results_path).read_bytes())
    if results.get("publication_policy") != "confirmed_newer_only":
        raise ValueError("Website publication requires confirmed newer solver results only")
    expected_pairs = set()
    for pair_id, pair in results["pairs"].items():
        points = {}
        for point in pair["cases"]:
            provenance = point.get("provenance", {})
            if not (provenance.get("new_numerical_solve") is True
                    or point.get("validation_level") == "integer_budget_and_fresh_model_forward_replay"):
                raise ValueError(f"Pair {pair_id}: older or imported solver input cannot be published")
            points[(point["amount_in_raw"], point["modeled_amount_out_raw"])] = point
        selected = {band: point for band, point in pair["model_bands"].items() if point is not None}
        if selected:
            expected_pairs.add(pair_id)
        displayed = bands["pairs"].get(pair_id, {}).get("bands", {})
        if set(displayed) != set(selected):
            raise ValueError(f"Pair {pair_id}: selected newer bands differ from website inputs")
        for band, point in selected.items():
            if points.get((point["amount_in_raw"], point["modeled_amount_out_raw"])) != point:
                raise ValueError(f"Pair {pair_id}: band {band} is not a confirmed newer case")
            figure = displayed[band]
            if (figure["amount_in_raw"], figure["amount_out_raw"], figure["slippage_bps"]) != (
                    point["amount_in_raw"], point["modeled_amount_out_raw"], point["model_slippage_bps"]):
                raise ValueError(f"Pair {pair_id}: displayed band {band} differs from the newer result")
            if (figure["amount"], figure["usd"]) != (float(point["amount_in"]), float(point["amount_in_usd"])):
                raise ValueError(f"Pair {pair_id}: displayed amounts differ from the newer result")
    if set(bands["pairs"]) != expected_pairs:
        raise ValueError("Website bands contain pairs without confirmed newer results")


def build(bands_path=None, out=OUT):
    """Write the site for the bands file into `out`; returns what main() reports. tests/check_build.py calls it with
    a synthetic bands file and an output folder under .preview/."""
    if DEFAULT_BAND not in BANDS:
        raise ValueError("DEFAULT_BAND must be one of BANDS")
    if bands_path is None:
        bands_path = DATA / "bands.json"
    bands_path = Path(bands_path)
    canonical_publication = bands_path.resolve() == (DATA / "bands.json").resolve()
    publication_manifest = DATA / "solver-publication-manifest.json"
    source_names = {"bands.json": bands_path.name,
        "solver-results.json": "solver-results.json",
        "chain-snapshots.json": "chain-snapshots.json"}
    if canonical_publication and publication_manifest.exists():
        manifest = json.loads(publication_manifest.read_bytes())
        source_names.update(manifest.get("source_names", {}))
        if (DATA / source_names["bands.json"]).resolve() != bands_path.resolve():
            raise ValueError("The publication manifest maps bands.json to another input file")
        for name in ("bands.json", "solver-results.json", "chain-snapshots.json"):
            raw = (DATA / source_names[name]).read_bytes()
            recorded = manifest["files"][name]
            if hashlib.sha256(raw).hexdigest() != recorded["sha256"] or len(raw) != recorded["bytes"]:
                raise ValueError(f"{name}: differs from the complete solver publication manifest; rerun the exporter")
    policy_path = DATA / "solver-publication-policy.json"
    if canonical_publication and policy_path.exists():
        policy = json.loads(policy_path.read_bytes())
        if policy.get("publication_policy") != "confirmed_newer_only":
            raise ValueError("Unknown website solver publication policy")
        if not publication_manifest.exists() or manifest.get("publication_policy") != "confirmed_newer_only":
            raise ValueError("Older solver publications cannot replace the newer-only website inputs")
        validate_newer_publication(bands_path, DATA / source_names["solver-results.json"])
    listing, chains, pairs = load_pairs()
    snapshots = load_chain_snapshots()
    updated, figures, unknown, published = load_bands(pairs, bands_path, snapshots)
    modeled = any(figure.get("kind") == "modeled" for entry in json.loads(bands_path.read_text()).get("pairs", {}).values()
                  for figure in entry.get("bands", {}).values())
    faces, preloads, font_files = font_faces()
    by_chain = {chain["slug"]: [] for chain in chains}
    for pair in pairs.values():
        by_chain[pair["chain"]].append(pair)
    chains = [chain for chain in chains if by_chain[chain["slug"]]]

    chips = [f'<button class="chip" type="button" data-chain="" aria-pressed="true">All chains '
             f'<span class="n">{len(pairs):,}</span></button>']
    chips += [f'<button class="chip" type="button" data-chain="{esc(chain["slug"])}" aria-pressed="false">'
              f'<span class="ini" aria-hidden="true">{esc(chain["name"][:1])}</span>{esc(chain["name"])} '
              f'<span class="n">{len(by_chain[chain["slug"]]):,}</span></button>' for chain in chains]
    header = ('<div class="r h" role="row"><div class="c p" role="columnheader">Pair</div>'
              + "".join(f'<div class="c b{band}" role="columnheader">{band}%</div>' for band in BANDS) + "</div>")
    when = (f"Updated {updated.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC" if updated
            else "Bands not published yet")
    page = fill((SRC / "index.html").read_text(), {
        "preloads": preloads,
        "css": stylesheet(faces),
        "sel_css": SELECT_DEFAULT.format(band=DEFAULT_BAND),
        "reveal_now": str(REVEAL_NOW),
        "reveal_per_frame": str(REVEAL_PER_FRAME),
        "page_size": str(PAGE_SIZE),
        "chain_chips": "".join(chips),
        "band_chips": "".join(f'<button class="chip bchip" type="button" data-band="{band}" '
                              f'aria-pressed="{str(band == DEFAULT_BAND).lower()}">{band}%</button>' for band in BANDS),
        "counts": f"{plural(len(pairs), 'pair')} · {plural(len(chains), 'chain')}",
        "updated": esc(when),
        "figure_label": "in USD · model estimates" if modeled else "in USD",
        "default_band": str(DEFAULT_BAND),
        "header": header,
        "groups": "".join(group(chain, by_chain[chain["slug"]], figures, snapshots.get(chain["chain_id"])) for chain in chains),
        "legend": (MODEL_LEGEND if modeled else LEGEND) if figures else "",
        "js": (SRC / "app.js").read_text().strip(),
    })

    out = Path(out)
    (out / "fonts").mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(parents=True, exist_ok=True)
    for stale in (out / "data").iterdir():  # earlier builds copied the full inputs here
        if stale.name != "figures.json":
            shutil.rmtree(stale) if stale.is_dir() else stale.unlink()
    (out / "data" / "figures.json").write_text(json.dumps({
        "updated": updated.isoformat() if updated else None,
        "pairs": {str(pair_id): published[pair_id] for pair_id in sorted(published)}},
        ensure_ascii=False, separators=(",", ":")) + "\n")
    for stale in (out / "fonts").iterdir():
        if stale.name not in font_files and stale.name != "OFL.txt":
            stale.unlink()
    for name in font_files + ["OFL.txt"]:
        shutil.copyfile(FONTS / name, out / "fonts" / name)
    (out / "more.json").unlink(missing_ok=True)  # the More menu's data, from before the fixed bands
    (out / "index.html").write_text(page)
    (out / ".nojekyll").write_text("")
    return {"page": page, "pairs": len(pairs), "chains": len(chains), "published": len(figures), "when": when,
            "unknown": sorted(unknown), "fetched": listing["fetched_at_utc"], "out": out}


def main():
    built = build()
    size = lambda text: f"{len(text.encode()):,} bytes, {len(gzip.compress(text.encode(), 9)):,} gzipped"  # noqa: E731
    print(f"built {built['out'] / 'index.html'}: {built['pairs']:,} liqind pairs on {built['chains']} chains "
          f"(liqind list fetched {built['fetched'][:16]}Z); bands published for {built['published']:,} pairs, "
          f"{built['when'][0].lower() + built['when'][1:]}")
    print(f"  index.html {size(built['page'])}")
    if built["unknown"]:
        print(f"  left out of bands.json, not in pairs.json: {built['unknown']}")


if __name__ == "__main__":
    main()
