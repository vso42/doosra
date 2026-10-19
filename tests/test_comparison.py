"""The aggregator table under the bands: exact token amounts, usable quotes only, escaped text, plain numbers out.
Run: python3 -m pytest -q tests/test_comparison.py"""
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build

CHAINS = {"ethereum": "Ethereum"}


def ours(size, amount_in, amount_out, slippage):
    return {"requested_input_usd": size, "amount_in_raw": amount_in, "amount_out_raw": amount_out, "slippage_pp": slippage,
            "quote_scope": "integer_budget_model_replay", "status": "funded_model_quote",
            "block_timestamp_utc": "2026-10-18T00:56:47+00:00"}


def theirs(name, amount_in, amount_out, slippage, block, at="2026-10-18T08:51:00Z"):
    return {"aggregator": name, "status": "ok", "usable_saved_reference": True, "amount_in": amount_in,
            "amount_out": amount_out, "common_reference_slippage_pp": slippage, "quote_block": block, "quoted_at": at}


def records():
    return {
        "21": {"chain": "ethereum", "collateral": "WETH", "debt": "PYUSD", "input_decimals": 18, "output_decimals": 6,
               "reviewed_quotes": [ours("18800000", "7838199548886600431100", "18475399335810", "1.736912"),
                                   ours("21600000", "9005590971061200495307", "21175553709892", "1.975325")],
               "aggregator_references": [
                   {"requested_model_input_usd": "18800000", "aggregators": [
                       theirs("lifi", "7810478883064658264064", "18508292720776", "1.212555", 26218367),
                       {"aggregator": "velora", "status": "impact_cap", "usable_saved_reference": False},
                       {"aggregator": "okx", "status": "refused", "usable_saved_reference": False}]},
                   {"requested_model_input_usd": "21600000", "aggregators": [
                       theirs("lifi", "8973741695435990368256", "21206323750000", "1.484412", 26218367),
                       theirs("velora", "8973741695435990368256", "20847000000000", "3.456411", 26218345,
                              "2026-10-18T08:47:17Z"),
                       {"aggregator": "okx", "status": "refused", "usable_saved_reference": False}]}]},
        "6": {"chain": "ethereum", "collateral": "WETH", "debt": "USDC", "input_decimals": 18, "output_decimals": 6,
              "reviewed_quotes": [ours("1000000", "416000000000000000000", "998000000000", "0.2")],
              "aggregator_references": [{"requested_model_input_usd": "1000000", "aggregators": [
                  {"aggregator": "lifi", "status": "impact_cap", "usable_saved_reference": False}]}]}}


def test_exact_amounts_behind_rounded_figures():
    page, numbers = build.comparison(records(), CHAINS)
    assert '<span title="7838.1995488866004311 WETH">7,838.20 WETH</span><small>$18.8M</small>' in page
    assert '<td title="18475399.33581 PYUSD">1.74%<small>18,475,399.34 PYUSD</small></td>' in page
    assert ('<td title="for 7810.478883064658264064 WETH at block 26,218,367">1.21%'
            '<small>18,508,292.72 PYUSD</small></td>') in page
    assert numbers[0]["rows"][0] == {
        "size_usd": "18800000", "amount_in": "7838.1995488866004311",
        "doosra": {"amount_out": "18475399.33581", "slippage_pct": "1.7369"},
        "aggregators": {"lifi": {"amount_in": "7810.478883064658264064", "amount_out": "18508292.720776",
                                 "slippage_pct": "1.2126", "block": 26218367}, "velora": None}}


def test_missing_quote_is_a_dash_and_aggregators_that_never_quoted_get_no_column():
    page, numbers = build.comparison(records(), CHAINS)
    assert '<td class="na" title="Velora hit its price-impact cap">—</td>' in page
    assert ">LI.FI</th>" in page and ">Velora</th>" in page and "OKX" not in page
    assert set(numbers[0]["rows"][1]["aggregators"]) == {"lifi", "velora"}


def test_pairs_without_a_usable_quote_are_left_out():
    page, numbers = build.comparison(records(), CHAINS)
    assert 'data-pair="21"' in page and 'data-pair="6"' not in page
    assert [entry["pair_id"] for entry in numbers] == [21]
    only_six = {"6": records()["6"]}
    assert build.comparison(only_six, CHAINS) == ("", [])


def test_only_full_input_quotes_of_ours_are_compared():
    data = records()
    data["21"]["reviewed_quotes"][0]["status"] = "partial_no_full_quote"
    data["21"]["reviewed_quotes"][1]["quote_scope"] = "something_else"
    assert build.comparison(data, CHAINS) == ("", [])


def test_junk_values_are_never_shown_as_prices():
    data = records()
    lifi, velora = data["21"]["aggregator_references"][1]["aggregators"][:2]
    lifi["amount_out"] = "-5"
    velora["common_reference_slippage_pp"] = "NaN"
    page, numbers = build.comparison(data, CHAINS)
    # the $21.6M row has no usable quote left, and Velora quoted nothing else
    assert [row["size_usd"] for row in numbers[0]["rows"]] == ["18800000"]
    assert "Velora" not in page and "nan" not in page.lower()


def test_text_is_escaped_and_the_input_is_left_alone():
    data = records()
    data["21"]["debt"] = '<img src=x onerror="alert(1)">'
    before = deepcopy(data)
    page, _ = build.comparison(data, CHAINS)
    assert "<img" not in page and "&lt;img" in page
    assert data == before


def test_note_names_the_quote_blocks_and_the_gap():
    page, _ = build.comparison(records(), CHAINS)
    assert "saved at blocks 26,218,345–26,218,367, about 8 hours after ours," in page


def test_published_data_is_only_the_figures_file(tmp_path):
    out = tmp_path / "docs"
    (out / "data").mkdir(parents=True)
    (out / "data" / "solver-results.json").write_text("{}")  # left over from an older build
    built = build.build(Path(build.ROOT) / "tests" / "fixtures" / "bands.sample.json", out)
    assert sorted(path.name for path in (out / "data").iterdir()) == ["figures.json"]
    figures = json.loads((out / "data" / "figures.json").read_text())
    assert set(figures) == {"updated", "pairs", "aggregator_comparison"}
    assert len(figures["pairs"]) == built["published"]
    assert figures["pairs"]["6"]["bands"]["3"] == {"amount": 3000, "usd": 7200000, "kind": "measured"}
