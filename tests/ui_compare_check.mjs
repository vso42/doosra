#!/usr/bin/env node
// Browser check of what goes public: docs/ holds the page and data/figures.json only, figures.json carries the numbers
// the page shows, and every aggregator table matches the saved quotes it is built from. The expected values are worked
// out here, independently of build.py, from the local data/bands.json and data/solver-results.json (data/ is not in
// the repo). Same headless Firefox and RAM limits as tests/ui_check.mjs.
// Usage: python3 build.py && node tests/ui_compare_check.mjs   (exit status 1 if any check fails)
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { ROOT, FRAMES, openBrowser } from "./browser.mjs";

let failures = 0;
const check = (name, ok, detail = "") => {
  if (!ok) failures++;
  const shown = ok || detail === "" ? "" : "  — " + (typeof detail === "string" ? detail : JSON.stringify(detail));
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${shown}`);
};
const read = (path) => JSON.parse(readFileSync(join(ROOT, path), "utf8"));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// Python's exact Decimal text of an integer in base units, and f"{value:,.2f}" of it (round half to even)
const exact = (raw, decimals) => {
  const n = BigInt(raw), unit = 10n ** BigInt(decimals);
  const fraction = (n % unit).toString().padStart(decimals, "0").replace(/0+$/, "");
  return `${n / unit}${fraction ? "." + fraction : ""}`;
};
const cents = (raw, decimals) => {
  const n = BigInt(raw), scale = 10n ** BigInt(decimals - 2), twice = 2n * (n % scale);
  let q = n / scale;
  if (twice > scale || (twice === scale && q % 2n === 1n)) q += 1n;
  return `${(q / 100n).toLocaleString("en-US")}.${(q % 100n).toString().padStart(2, "0")}`;
};
// str(round(Decimal(text), places)) and f"{Decimal(text):.{places}f}", both round half to even
const rounded = (text, places) => {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(String(text));
  if (!m) return `unparsed ${text}`;
  const [, sign, whole, fraction = ""] = m, rest = fraction.slice(places);
  let q = BigInt(whole + fraction.slice(0, places).padEnd(places, "0"));
  const first = rest[0] || "0", tail = /[1-9]/.test(rest.slice(1));
  if (first > "5" || (first === "5" && (tail || q % 2n === 1n))) q += 1n;
  const unit = 10n ** BigInt(places);
  return `${sign}${q / unit}.${(q % unit).toString().padStart(places, "0")}`;
};
// build.usd(): "$" and 3 significant digits with a K/M/B/T suffix
const usdLabel = (value) => {
  const r = Number(Number(value).toPrecision(3));
  for (const [scale, suffix] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]])
    if (r >= scale) return "$" + String(Number((r / scale).toPrecision(3))) + suffix;
  return "$" + String(r);
};

const NAMES = [["lifi", "LI.FI"], ["kyberswap", "KyberSwap"], ["velora", "Velora"], ["1inch", "1inch"], ["okx", "OKX"]];
const digits = (v) => typeof v === "string" && /^\d+$/.test(v);
const finite = (v) => v != null && /^-?\d+(\.\d+)?$/.test(String(v));
const liqind = read("data/pairs.json"), chainNames = Object.fromEntries(liqind.chains.map((c) => [c.slug, c.name]));
const listed = new Set(liqind.pairs.map((p) => String(p.pair_id)));
const bands = read("data/bands.json"), results = read("data/solver-results.json").pairs;

// the tables the page should show: pairs with a usable saved quote at the size of one of our full-input quotes
const expected = [];
for (const [id, pair] of Object.entries(results).sort((a, b) => +a[0] - +b[0])) {
  const ours = new Map();
  for (const q of pair.reviewed_quotes || [])
    if (q.quote_scope === "integer_budget_model_replay" && q.status !== "partial_no_full_quote" && digits(q.amount_in_raw)
        && digits(q.amount_out_raw) && finite(q.slippage_pp) && finite(q.requested_input_usd)) ours.set(Number(q.requested_input_usd), q);
  const rows = [];
  for (const ref of pair.aggregator_references || []) {
    const q = ours.get(Number(ref.requested_model_input_usd));
    if (!q) continue;
    const all = Object.fromEntries((ref.aggregators || []).map((a) => [a.aggregator, a]));
    const usable = Object.fromEntries(Object.entries(all).filter(([, a]) => a.usable_saved_reference === true
      && digits(a.amount_in) && digits(a.amount_out) && finite(a.common_reference_slippage_pp)));
    if (Object.keys(usable).length) rows.push({ q, all, usable });
  }
  if (!rows.length) continue;
  const shown = NAMES.filter(([name]) => rows.some((r) => r.usable[name]));
  const [din, dout, base, quote] = [pair.input_decimals, pair.output_decimals, pair.collateral, pair.debt];
  expected.push({
    id, title: `${chainNames[pair.chain] || pair.chain} · ${base} → ${quote}`,
    head: ["Size", "doosra", ...shown.map(([, label]) => label)],
    cells: rows.map(({ q, usable }) => [
      { text: `${cents(q.amount_in_raw, din)} ${base}${usdLabel(q.requested_input_usd)}`, title: `${exact(q.amount_in_raw, din)} ${base}` },
      { text: `${rounded(q.slippage_pp, 2)}%${cents(q.amount_out_raw, dout)} ${quote}`, title: `${exact(q.amount_out_raw, dout)} ${quote}` },
      ...shown.map(([name, label]) => {
        const a = usable[name];
        if (!a) return { text: "—", label };
        const where = Number.isInteger(a.quote_block) ? ` at block ${a.quote_block.toLocaleString("en-US")}` : "";
        return { text: `${rounded(a.common_reference_slippage_pp, 2)}%${cents(a.amount_out, dout)} ${quote}`,
                 title: `for ${exact(a.amount_in, din)} ${base}${where}` };
      })]),
    numbers: rows.map(({ q, usable }) => ({
      size_usd: q.requested_input_usd, amount_in: exact(q.amount_in_raw, din),
      doosra: { amount_out: exact(q.amount_out_raw, dout), slippage_pct: rounded(q.slippage_pp, 4) },
      aggregators: Object.fromEntries(shown.map(([name]) => {
        const a = usable[name];
        return [name, a ? { amount_in: exact(a.amount_in, din), amount_out: exact(a.amount_out, dout),
          slippage_pct: rounded(a.common_reference_slippage_pp, 4), block: Number.isInteger(a.quote_block) ? a.quote_block : null } : null];
      })) })),
  });
}

// what is published
const published = readdirSync(join(ROOT, "docs/data"));
check("docs/data holds figures.json and nothing else", same(published, ["figures.json"]), published);
const text = readFileSync(join(ROOT, "docs/data/figures.json"), "utf8"), figures = JSON.parse(text);
check("figures.json has no local paths, file hashes, block hashes or provenance",
  !/\/home\/|sha256|provenance|0x[0-9a-fA-F]{64}/.test(text), text.match(/\/home\/[^"]{0,40}|sha256|provenance|0x[0-9a-fA-F]{64}/)?.[0]);
check("figures.json keeps only the update time, the bands and the aggregator tables",
  same(Object.keys(figures).sort(), ["aggregator_comparison", "pairs", "updated"]), Object.keys(figures));
const bandIds = Object.keys(bands.pairs).filter((id) => listed.has(id) && Object.keys(bands.pairs[id].bands || {}).length);
check(`figures.json lists every published pair (${bandIds.length})`,
  same(Object.keys(figures.pairs).sort(), [...bandIds].sort()), Object.keys(figures.pairs).length);
const wrong = bandIds.filter((id) => Object.entries(bands.pairs[id].bands).some(([band, f]) => {
  const got = figures.pairs[id]?.bands?.[band];
  return !got || got.amount !== f.amount || got.usd !== f.usd || got.kind !== f.kind;
}));
check("figures.json band amounts, USD values and kinds equal data/bands.json", !wrong.length, wrong.slice(0, 5));
check("figures.json aggregator tables equal the saved quotes", same(figures.aggregator_comparison.map((e) => e.rows),
  expected.map((e) => e.numbers)) && same(figures.aggregator_comparison.map((e) => String(e.pair_id)), expected.map((e) => e.id)),
  figures.aggregator_comparison.map((e) => e.pair_id));

const browser = await openBrowser();
try {
  await browser.viewport(1280, 1520);
  await browser.load();
  const state = await browser.run(`async () => {
    const cell = (c) => ({ text: c.textContent, title: c.querySelector("span[title]")?.title ?? c.getAttribute("title") });
    return {
      pairs: [...document.querySelectorAll(".compare-pair")].map((p) => ({ id: p.dataset.pair, title: p.querySelector("h3").textContent,
        head: [...p.querySelectorAll("thead th")].map((c) => c.textContent),
        cells: [...p.querySelectorAll("tbody tr")].map((r) => [...r.children].map(cell)) })),
      note: document.querySelector(".compare-note")?.textContent || "",
      requests: performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/data/")),
      downloads: document.querySelectorAll('a[download],a[href*="/data/"],a[href$=".json"],a[href$=".csv"]').length,
      header: document.querySelector("#depth-title").textContent,
      modelTitle: document.querySelector(".rows .c[title]")?.title || "",
      hashTitles: [...document.querySelectorAll("[title]")].filter((e) => /hash|0x[0-9a-fA-F]{64}/.test(e.title)).map((e) => e.title).slice(0, 3),
      avalanche: document.querySelector('.g[data-chain="avalanche"] .chain-note')?.textContent,
    };
  }`);
  check(`aggregator tables for pairs ${expected.map((e) => e.id).join(", ")}, in that order`,
    same(state.pairs.map((p) => p.id), expected.map((e) => e.id)), state.pairs.map((p) => p.id));
  for (const want of expected) {
    const got = state.pairs.find((p) => p.id === want.id);
    if (!got) continue;
    check(`pair ${want.id}: heading and columns`, got.title === want.title && same(got.head, want.head),
      { title: got.title, head: got.head });
    const bad = [];
    want.cells.forEach((row, r) => row.forEach((w, c) => {
      const g = got.cells[r]?.[c];
      const ok = g && g.text === w.text && (w.label ? g.title?.startsWith(w.label + " ") : g.title === w.title);
      if (!ok) bad.push({ row: r + 1, column: want.head[c], got: g, want: w });
    }));
    check(`pair ${want.id}: ${want.cells.length} rows, every slippage, amount and tooltip as saved`,
      got.cells.length === want.cells.length && !bad.length, bad.slice(0, 2));
  }
  check("note names the quote blocks and says they are about the same inputs",
    /saved at blocks? [\d,]+(–[\d,]+)?, about \d+ hours after ours, for nearly the same inputs/.test(state.note), state.note);
  check("band figures labeled model estimates", state.header.includes("model estimates")
    && state.modelTitle.includes("contract execution unverified"), { header: state.header, title: state.modelTitle });
  check("no tooltip shows a hash", !state.hashTitles.length, state.hashTitles);
  check("no download links and no data fetched by the page", !state.downloads && !state.requests.length, state.requests);
  check("Avalanche note kept", state.avalanche === "Still struggling on bin counting; will provide soon.", state.avalanche);
  const toSection = `async () => { document.querySelector(".compare")?.scrollIntoView(); await (${FRAMES})(); return true; }`;
  await browser.run(toSection);
  await browser.shot("compare-desktop");

  await browser.viewport(390, 844);
  await browser.load();
  await browser.run(toSection);
  await browser.shot("compare-phone");
  const phone = await browser.run(`async () => { await (${FRAMES})();
    return { page: document.documentElement.scrollWidth, viewport: innerWidth,
      frames: [...document.querySelectorAll(".quote-scroll")].map((e) => ({ client: e.clientWidth, scroll: e.scrollWidth })) }; }`);
  check("phone: no sideways page scroll; wide tables scroll inside their frames", phone.page <= phone.viewport
    && phone.frames.length === expected.length && phone.frames.every((f) => f.client > 0 && f.client <= phone.viewport), phone);
  check("no console errors", browser.consoleErrors.length === 0, browser.consoleErrors);
  console.log(`headless Firefox peak RAM ${browser.peakMb()} MB`);
} catch (error) {
  check("browser harness completes", false, error.stack || String(error));
} finally {
  await browser.close();
}
process.exit(failures ? 1 : 0);
