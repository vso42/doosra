#!/usr/bin/env node
// Browser check of the built site (run `python3 build.py` first): works every control of docs/index.html in headless
// Firefox (tests/browser.mjs), checks the results against data/pairs.json, prints load and interaction timings and
// saves screenshots to .preview/. Usage: node tests/ui_check.mjs   (exit status 1 if any check fails)
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { FRAMES, PREVIEW, ROOT, SETTLED, availableMb, openBrowser } from "./browser.mjs";

const PAGE = 10, BANDS = ["1", "2", "3", "5", "10"];
// expected values, from the same data the build used
const listing = JSON.parse(readFileSync(join(ROOT, "data", "pairs.json"), "utf8"));
const norm = (text) => text.toLowerCase().replace(/₮/g, "t");
const chainName = Object.fromEntries(listing.chains.map((c) => [c.slug,
  norm(c.name).replace(/ /g, "") === c.slug ? norm(c.name) : norm(c.name + " " + c.slug)]));
// each chain's rows in page order, as build.py sorts them: largest collateral market first, then collateral, tier, debt
const lower = (text) => text.toLowerCase();
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const ordered = Object.fromEntries(listing.chains.map((c) => [c.slug, listing.pairs.filter((p) => p.chain === c.slug)
  .sort((a, b) => (b.collateral_supply_usd || 0) - (a.collateral_supply_usd || 0) || cmp(lower(a.collateral), lower(b.collateral))
    || a.tier - b.tier || cmp(lower(a.debt), lower(b.debt))).map((p) => p.pair_id)]));
const terms = (query) => norm(query).split(/[^a-z0-9.]+/).map((t) => t.replace(/^\.+|\.+$/g, "")).filter(Boolean);
const matchesPerChain = (query) => Object.fromEntries(listing.chains.map((c) => [c.slug, listing.pairs.filter((p) =>
  p.chain === c.slug && terms(query).every((t) => (norm(p.collateral + " " + p.debt) + " " + chainName[p.chain]).includes(t))).length]));
const firstPages = (perChain) => Object.values(perChain).reduce((sum, n) => sum + Math.min(PAGE, n), 0);
const plural = (n, w) => n.toLocaleString("en-US") + " " + w + (n === 1 ? "" : "s");
const total = listing.pairs.length, chainCount = listing.chains.length;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

let failures = 0;
const check = (name, ok, detail = "") => {
  if (!ok) failures++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const browser = await openBrowser();
const { run, shot, viewport, load, consoleErrors } = browser;
const state = () => run(`async () => {
  await (${SETTLED})();
  await (${FRAMES})();
  const groups = [...document.querySelectorAll(".g")].filter((g) => !g.hidden);
  const rows = (g) => [...g.querySelectorAll(".rows>.r")].filter((r) => !r.hidden);
  return { counts: document.getElementById("counts").textContent, chains: groups.map((g) => g.dataset.chain),
    rows: groups.reduce((sum, g) => sum + rows(g).length, 0),
    hays: groups.flatMap((g) => rows(g).map((r) => r.dataset.q + " " + g.dataset.name)),
    perChain: Object.fromEntries(groups.map((g) => [g.dataset.chain, [rows(g).length, g.querySelector(".gn").textContent]])),
    empty: !document.getElementById("empty").hidden, emptyText: document.getElementById("empty-text").textContent };
}`);
const search = (text) => run(`async () => { const q = document.getElementById("q"); q.value = ${JSON.stringify(text)};
  q.dispatchEvent(new Event("input", { bubbles: true })); return true; }`);
// a chain's pager: button labels, current page, range text, disabled ends, its markup and the ids of the rows shown
const pagerState = (chain) => run(`async () => {
  await (${FRAMES})();
  const g = document.querySelector('.g[data-chain="${chain}"]'), pg = g.querySelector(".pg");
  return { shown: !g.querySelector(".pgr").hidden, html: pg.innerHTML,
    labels: [...pg.children].filter((e) => !e.classList.contains("pr")).map((e) => e.textContent),
    current: (pg.querySelector("[aria-current]") || {}).textContent || null, range: (pg.querySelector(".pr") || {}).textContent || null,
    prevDisabled: !!(pg.querySelector('[data-to="prev"]') || {}).disabled, nextDisabled: !!(pg.querySelector('[data-to="next"]') || {}).disabled,
    ids: [...g.querySelectorAll(".rows>.r")].filter((r) => !r.hidden).map((r) => +r.dataset.id) };
}`);
const turn = (chain, to) => run(`async () => {
  document.querySelector('.g[data-chain="${chain}"] .pb[data-to="${to}"]').click(); return true; }`);
// visible header cells and the first visible row's cells, left to right: labels, positions and widths
const headerOrder = () => run(`async () => {
  await (${FRAMES})();
  const cells = [...document.querySelectorAll("#hwrap .h .c")];
  const row = [...document.querySelectorAll(".rows>.r")].find((r) => !r.hidden && r.offsetParent);
  const left = (c) => Math.round(c.getBoundingClientRect().left * 10) / 10;
  const width = (c) => Math.round(c.getBoundingClientRect().width);
  return { labels: cells.map((c) => c.textContent), header: cells.map(left), row: [...row.children].map(left),
    widths: cells.map(width), rowWidths: [...row.children].map(width) };
}`);
const aligned = (o) => o.header.length === o.row.length && o.header.every((x, i) => Math.abs(x - o.row[i]) < 0.6)
  && o.widths.every((w, i) => Math.abs(w - o.rowWidths[i]) <= 1);
// the selected column: exactly one header cell marked, the tint bar over it, the static pre-script tint gone
const barOver = () => run(`async () => {
  await (${FRAMES})();
  const on = document.querySelectorAll("#hwrap .on"), bar = document.getElementById("hl");
  const box = (el) => { const r = el.getBoundingClientRect(); return [Math.round(r.left * 10) / 10, Math.round(r.width * 10) / 10]; };
  return { n: on.length, label: on.length ? on[0].textContent : null, bar: box(bar), head: on.length ? box(on[0]) : null,
    shown: !bar.hidden, staticTint: getComputedStyle(document.querySelector(".rows .b2")).backgroundColor };
}`);
const barOk = (b, label) => b.n === 1 && b.label === label && b.shown && Math.abs(b.bar[0] - b.head[0]) < 0.6
  && Math.abs(b.bar[1] - b.head[1]) < 0.6 && b.staticTint === "rgba(0, 0, 0, 0)";

try {
  // desktop, dark
  await viewport(1280, 1520);
  await load();
  const timing = await run(`async () => {
    const nav = performance.getEntriesByType("navigation")[0];
    const fcp = performance.getEntriesByType("paint").find((e) => e.name === "first-contentful-paint");
    const lcp = await new Promise((resolve) => {
      try { new PerformanceObserver((list) => { const e = list.getEntries(); resolve(e[e.length - 1].startTime); })
        .observe({ type: "largest-contentful-paint", buffered: true }); } catch (e) { resolve(null); }
      setTimeout(() => resolve(null), 1500);
    });
    return { domInteractive: nav.domInteractive, domContentLoaded: nav.domContentLoadedEventEnd, load: nav.loadEventEnd,
      fcp: fcp ? fcp.startTime : null, lcp, fonts: document.fonts.check('13px Geist') && document.fonts.check('13px "Geist Mono"'),
      pageWidth: document.documentElement.scrollWidth, brand: document.querySelector(".brand").innerHTML,
      icon: document.querySelector('link[rel="icon"]').getAttribute("href"), more: !!document.getElementById("band-more"),
      bands: [...document.querySelectorAll("#bands [data-band]")].map((b) => b.dataset.band) };
  }`);
  console.log(`load (localhost, desktop): domInteractive ${timing.domInteractive.toFixed(0)} ms, DOMContentLoaded `
    + `${timing.domContentLoaded.toFixed(0)} ms, load ${timing.load.toFixed(0)} ms, first contentful paint `
    + `${timing.fcp?.toFixed(0)} ms, largest contentful paint ${timing.lcp?.toFixed(0)} ms`);
  check("Geist and Geist Mono loaded from docs/fonts", timing.fonts);
  check("no logo: plain 'doosra' and an empty favicon", timing.brand === "doosra" && timing.icon === "data:,",
    `${JSON.stringify(timing.brand)}, icon ${timing.icon}`);
  check("bands 1, 2, 3, 5 and 10%, no More menu", same(timing.bands, BANDS) && !timing.more, timing.bands.join());
  let s = await state();
  const all = Object.fromEntries(listing.chains.map((c) => [c.slug, ordered[c.slug].length]));
  check("all pairs and chains counted, each chain on its first page",
    s.counts === `${plural(total, "pair")} · ${plural(chainCount, "chain")}` && s.rows === firstPages(all)
    && s.chains.length === chainCount, `${s.counts}; ${s.rows} rows shown`);
  let order = await headerOrder();
  check("header and row columns align (desktop)", aligned(order) && same(order.labels, ["Pair", ...BANDS.map((b) => b + "%")]),
    JSON.stringify(order.labels));
  let bar = await barOver();
  check("default band 2%: tint bar over its column", barOk(bar, "2%"), JSON.stringify(bar));
  check("no horizontal page overflow (desktop)", timing.pageWidth <= 1280, `${timing.pageWidth}px`);
  await shot("desktop-dark");

  // pages
  const eth = ordered.ethereum, pages = Math.ceil(eth.length / PAGE);
  let pg = await pagerState("ethereum");
  const builtPager = pg.html;
  check(`Ethereum page 1: first ${PAGE} pairs in order, pager 1-5 … ${pages}`, pg.shown && same(pg.ids, eth.slice(0, PAGE))
    && same(pg.labels, ["‹", "1", "2", "3", "4", "5", "…", String(pages), "›"]) && pg.current === "1"
    && pg.range === `1–${PAGE} of ${eth.length}` && pg.prevDisabled && !pg.nextDisabled, JSON.stringify({ ...pg, html: undefined }));
  await turn("ethereum", "2");
  pg = await pagerState("ethereum");
  check("Ethereum page 2: the next 10 pairs", same(pg.ids, eth.slice(10, 20)) && pg.current === "2"
    && pg.range === `11–20 of ${eth.length}` && !pg.prevDisabled, `${pg.ids.join()}; ${pg.range}`);
  await turn("ethereum", String(pages));
  pg = await pagerState("ethereum");
  const lastStart = (pages - 1) * PAGE;
  check(`Ethereum last page (${pages}): the remaining ${eth.length - lastStart} pairs`, same(pg.ids, eth.slice(lastStart))
    && same(pg.labels, ["‹", "1", "…", ...[4, 3, 2, 1, 0].map((k) => String(pages - k)), "›"]) && pg.nextDisabled
    && pg.range === `${lastStart + 1}–${eth.length} of ${eth.length}`, `${pg.labels.join(" ")}; ${pg.range}`);
  await turn("ethereum", "prev");
  pg = await pagerState("ethereum");
  check("Previous: one page back", pg.current === String(pages - 1) && same(pg.ids, eth.slice(lastStart - PAGE, lastStart)),
    `${pg.current}; ${pg.range}`);
  await turn("ethereum", "1");
  pg = await pagerState("ethereum");
  check("back on page 1, app.js rebuilds exactly the pager build.py wrote", pg.html === builtPager && same(pg.ids, eth.slice(0, PAGE)));
  const kept = await run(`async () => {
    const next = document.querySelector('.g[data-chain="ethereum"] .pb[data-to="next"]');
    next.focus(); next.click(); await (${FRAMES})();
    const active = document.activeElement;
    return { to: active.dataset.to, page: document.querySelector('.g[data-chain="ethereum"] .pg [aria-current]').textContent };
  }`);
  check("keyboard focus stays on Next after the pager is rebuilt", kept.to === "next" && kept.page === "2", JSON.stringify(kept));
  const ink = await pagerState("ink");
  check(`a chain of ${ordered.ink.length} pairs has no pager`, !ink.shown && same(ink.ids, ordered.ink));
  await shot("desktop-pages");

  // filters: each chain restarts at page 1 with its matching pairs
  await run(`async () => document.querySelector('#chains [data-chain="ethereum"]').click()`);
  s = await state();
  check("chain chip: Ethereum only, back on its page 1", same(s.chains, ["ethereum"]) && s.rows === PAGE
    && same((await pagerState("ethereum")).ids, eth.slice(0, PAGE)), s.counts);
  await run(`async () => document.querySelector('#chains [data-chain="base"]').click()`);
  s = await state();
  check("chain chips: Ethereum and Base", same(s.chains, ["ethereum", "base"]) && s.rows === PAGE + Math.min(PAGE, all.base)
    && s.counts === `${plural(all.ethereum + all.base, "pair")} · 2 chains`, s.counts);
  await run(`async () => document.querySelector('#chains [data-chain=""]').click()`);
  s = await state();
  check("All chains resets", s.rows === firstPages(all) && s.chains.length === chainCount, s.counts);

  for (const query of ["weth usdc", "usdt0", "btc.b", "eth ethereum", "weth", "bsc", ""]) {
    await search(query);
    s = await state();
    const expected = matchesPerChain(query), sum = Object.values(expected).reduce((a, b) => a + b, 0);
    const perChainOk = Object.entries(expected).filter(([, n]) => n).every(([chain, n]) => s.perChain[chain]
      && s.perChain[chain][0] === Math.min(PAGE, n) && s.perChain[chain][1] === plural(n, "pair"));
    check(`search "${query}"`, s.rows === firstPages(expected) && perChainOk && s.counts.startsWith(plural(sum, "pair"))
      && s.hays.every((h) => terms(query).every((t) => h.includes(t))), `${s.counts}; ${s.rows} rows shown`);
    if (query === "weth") {
      pg = await pagerState("ethereum");
      const n = expected.ethereum;
      check(`search "weth": Ethereum pages over its ${n} matches`, pg.current === "1"
        && pg.range === `1–${PAGE} of ${n}` && pg.labels.includes(String(Math.ceil(n / PAGE))), `${pg.labels.join(" ")}; ${pg.range}`);
    }
    if (query === "bsc") await shot("desktop-search-bsc");
  }
  await search("zzzz");
  s = await state();
  check("empty state", s.empty && s.rows === 0 && s.emptyText === "No pairs match “zzzz”.", s.emptyText);
  await run(`async () => document.getElementById("clear").click()`);
  s = await state();
  check("Clear filters restores every chain's first page", !s.empty && s.rows === firstPages(all)
    && (await run(`async () => document.getElementById("q").value`)) === "", s.counts);

  // bands
  for (const band of ["10", "5", "2"]) {
    await run(`async () => document.querySelector('#bands [data-band="${band}"]').click()`);
    const pressed = await run(`async () => [...document.querySelectorAll("#bands [data-band]")].map((b) => b.getAttribute("aria-pressed")).join()`);
    bar = await barOver();
    check(`band ${band}%: chip pressed, tint bar over its column`, barOk(bar, `${band}%`)
      && pressed === BANDS.map((b) => String(b === band)).join(), `${pressed}; ${JSON.stringify(bar)}`);
  }

  const fold = await run(`async () => {
    const g = document.querySelector('.g[data-chain="ethereum"]'), b = g.querySelector(".fold");
    const shown = (sel) => getComputedStyle(g.querySelector(sel)).display !== "none";
    b.click(); await (${FRAMES})();
    const folded = !shown(".rows") && !shown(".pgr") && b.getAttribute("aria-expanded") === "false";
    b.click(); await (${FRAMES})();
    return { folded, open: shown(".rows") && shown(".pgr") && b.getAttribute("aria-expanded") === "true" };
  }`);
  check("chain fold hides its rows and pager, unfold restores them", fold.folded && fold.open);

  const sticky = await run(`async () => {
    window.scrollTo(0, 1500); await (${FRAMES})();
    return { top: document.getElementById("hwrap").getBoundingClientRect().top };
  }`);
  check("column header sticks to the top while scrolling", Math.abs(sticky.top) < 0.6, `top ${sticky.top}`);
  await shot("desktop-sticky");
  await run(`async () => { window.scrollTo(0, 0); return true; }`);

  const theme = await run(`async () => {
    document.getElementById("theme").click(); await (${FRAMES})();
    let saved = null; try { saved = localStorage.getItem("doosra-theme"); } catch (e) {}
    return { theme: document.documentElement.dataset.theme, saved, label: document.getElementById("theme").getAttribute("aria-label"),
      meta: document.querySelector('meta[name="theme-color"]').content };
  }`);
  check("theme toggles to light and is saved", theme.theme === "light" && theme.saved === "light"
    && theme.label === "Switch to dark theme" && theme.meta === "#f3f1ec", JSON.stringify(theme));
  await run(`async () => { await new Promise((r) => setTimeout(r, 300)); return true; }`); // the .2s colour fade
  await shot("desktop-light");
  await load();
  const kept2 = await run(`async () => document.documentElement.dataset.theme`);
  check("light theme kept after reload", kept2 === "light", kept2);
  await run(`async () => { document.getElementById("theme").click(); return true; }`);

  // interaction cost: per step, the work (script, style and layout, up to a forced layout) of the input's frame and of
  // every later frame until its rows are all shown. The sequence runs COST_RUNS times from the same state; a step
  // passes when its worst frame stayed under 16 ms in at least one run, so one GC pause or a busy machine during one
  // run does not decide, while work that is really too slow fails every run.
  const COST_RUNS = 3;
  const costRun = () => run(`async () => {
    const q = document.getElementById("q"), steps = [];
    const settled = ${SETTLED};
    const frameWork = () => new Promise((resolve) =>
      requestAnimationFrame((frameStart) => { void document.body.offsetHeight; resolve(performance.now() - frameStart); }));
    const finish = async (step) => {
      // later frames until the rows the step brings back are all shown (the settled check counts them)
      const size = +document.getElementById("tbl").dataset.page;
      const pending = () => document.querySelectorAll(".g:not([hidden]) .rows>.r:not([hidden])").length !== [...document
        .querySelectorAll(".g:not([hidden])")].reduce((sum, g) => {
          const n = +g.querySelector(".gn").textContent.replace(/,/g, "").split(" ")[0];
          const c = g.querySelector(".pgr:not([hidden]) [aria-current]"), p = c ? +c.dataset.to : 1;
          return sum + Math.max(0, Math.min(size, n - (p - 1) * size));
        }, 0);
      for (let i = 0; i < 240 && pending(); i++) step.later.push(await frameWork());
      steps.push({ kind: step.kind, label: step.label, input: step.input, worst: Math.max(step.input, ...step.later) });
    };
    const timed = async (kind, label, act) => {
      await new Promise((r) => requestAnimationFrame(r));
      const step = { kind, label, later: [] }, start = performance.now();
      act(); void document.body.offsetHeight;
      step.input = performance.now() - start;
      await finish(step);
    };
    for (const text of ["e", "et", "eth", "eth u", "eth us", "eth usd", "w", "wb", "wbtc", ""]) {
      const step = { kind: "search keystroke", label: JSON.stringify(text), later: [] };
      await new Promise((resolve) => {
        let start = 0;
        requestAnimationFrame(() => { start = performance.now(); });
        q.value = text; q.dispatchEvent(new Event("input", { bubbles: true }));
        requestAnimationFrame(() => { void document.body.offsetHeight; step.input = performance.now() - start; resolve(); });
      });
      await finish(step);
    }
    for (const chain of ["ethereum", "avalanche", "ethereum", "avalanche", ""])
      await timed("chain chip", chain || "All chains", () => document.querySelector('#chains [data-chain="' + chain + '"]').click());
    for (const band of ["1", "3", "5", "10", "2"])
      await timed("band chip", band + "%", () => document.querySelector('#bands [data-band="' + band + '"]').click());
    const pager = (to) => () => document.querySelector('.g[data-chain="ethereum"] .pb[data-to="' + to + '"]').click();
    for (const to of ["next", "next", "next", "45", "prev", "1"]) await timed("page button", to, pager(to));
    await settled();
    return steps;
  }`);
  const costRuns = [];
  for (let i = 0; i < COST_RUNS; i++) costRuns.push(await costRun());
  const best = costRuns[0].map((step, k) => ({ ...step, worst: Math.min(...costRuns.map((steps) => steps[k].worst)),
    input: Math.min(...costRuns.map((steps) => steps[k].input)) }));
  const median = (values) => [...values].sort((a, b) => a - b)[values.length >> 1];
  console.log(`interaction cost per frame (script + style + layout; best of ${COST_RUNS} runs): `
    + [...new Set(best.map((s) => s.kind))].map((kind) => {
      const steps = best.filter((s) => s.kind === kind);
      return `${kind}: input frame median ${median(steps.map((s) => s.input)).toFixed(0)} ms, `
        + `worst frame ${Math.max(...steps.map((s) => s.worst)).toFixed(1)} ms`;
    }).join("; ")
    + `; single worst frame of any run ${Math.max(...costRuns.flat().map((s) => s.worst)).toFixed(1)} ms`);
  const slow = best.filter((s) => s.worst >= 16);
  check(`every interaction's frames under 16 ms (one 60 Hz frame; best of ${COST_RUNS} runs per step)`, !slow.length,
    slow.length ? slow.map((s) => `${s.kind} ${s.label}: ${s.worst.toFixed(1)} ms`).join("; ")
      : `worst ${Math.max(...best.map((s) => s.worst)).toFixed(1)} ms over ${best.length} steps`);

  // phone
  await viewport(390, 844);
  await load();
  const chips = await run(`async () => {
    const box = document.getElementById("chains");
    return { height: Math.round(box.getBoundingClientRect().height), swipes: box.scrollWidth > box.clientWidth,
      tableTop: Math.round(document.getElementById("tbl").getBoundingClientRect().top + scrollY) };
  }`);
  check("phone: chain chips in one row that swipes sideways", chips.height <= 46 && chips.swipes,
    `chips row ${chips.height}px tall; table starts ${chips.tableTop}px down the page`);
  await shot("phone-top");
  const phone = await run(`async () => {
    const scroller = document.getElementById("scroll"), hwrap = document.getElementById("hwrap");
    document.getElementById("tbl").scrollIntoView();
    const width = document.documentElement.scrollWidth, overflow = scroller.scrollWidth - scroller.clientWidth;
    scroller.scrollLeft = 150; scroller.dispatchEvent(new Event("scroll")); await (${FRAMES})();
    const pair = document.querySelector(".rows>.r .c.p").getBoundingClientRect();
    const pg = document.querySelector('.g[data-chain="ethereum"] .pg'), pager = pg.getBoundingClientRect();
    const buttonTops = new Set([...pg.querySelectorAll(".pb")].map((b) => Math.round(b.getBoundingClientRect().top)));
    return { width, overflow, synced: hwrap.scrollLeft, pairLeft: pair.left, scrollerLeft: scroller.getBoundingClientRect().left,
      pagerLeft: pager.left, pagerRight: pager.right, viewport: innerWidth, buttonLines: buttonTops.size };
  }`);
  check("phone: no horizontal page overflow; table scrolls inside", phone.width <= 390 && phone.overflow > 0,
    `page ${phone.width}px, table overflow ${phone.overflow}px`);
  check("phone: header follows the table's horizontal scroll", phone.synced === 150, `header scrollLeft ${phone.synced}`);
  check("phone: pair column sticks on horizontal scroll", Math.abs(phone.pairLeft - phone.scrollerLeft) < 0.6,
    `pair cell at ${phone.pairLeft}, table at ${phone.scrollerLeft}`);
  check("phone: pager stays in view on horizontal scroll, its buttons on one line", Math.abs(phone.pagerLeft - phone.scrollerLeft) < 0.6
    && phone.pagerRight <= phone.viewport && phone.buttonLines === 1,
    `pager ${phone.pagerLeft}-${phone.pagerRight} in a ${phone.viewport}px window, buttons on ${phone.buttonLines} line(s)`);
  order = await headerOrder();
  check("header and row columns align (phone, scrolled)", aligned(order), JSON.stringify({ header: order.header, row: order.row }));
  bar = await barOver();
  check("phone: tint bar stays on its column when scrolled", barOk(bar, "2%"), JSON.stringify(bar));
  await shot("phone-table-sideways");
  await run(`async () => { const s = document.getElementById("scroll"); s.scrollLeft = 0; s.dispatchEvent(new Event("scroll"));
    await (${FRAMES})(); return true; }`);
  await shot("phone-table");
  // rows anywhere in the table are rendered and hit-testable right after a scroll there (the aggregator tables sit below
  // it, so the table's end is not the page's end)
  for (const [label, y] of [["middle of the page", "document.body.scrollHeight / 2"],
    ["end of the table", 'document.getElementById("tbl").getBoundingClientRect().bottom + scrollY - innerHeight']]) {
    const probe = await run(`async () => {
      window.scrollTo(0, ${y}); await (${FRAMES})();
      const top = Math.max(0, document.getElementById("hwrap").getBoundingClientRect().bottom);
      const column = document.querySelector("#hwrap .b1").getBoundingClientRect(), x = column.left + column.width / 2;
      const rows = [...document.querySelectorAll(".rows>.r")].filter((r) => !r.hidden).map((r) => {
        const box = r.getBoundingClientRect(); return { r, mid: (box.top + box.bottom) / 2 };
      }).filter(({ mid }) => mid > top && mid < innerHeight);
      const hits = rows.filter(({ r, mid }) => { const hit = document.elementFromPoint(x, mid); return hit && hit.closest(".c") === r.children[1]; });
      return { rows: rows.length, hits: hits.length, y: Math.round(scrollY) };
    }`);
    check(`phone: rows on screen rendered and hit-testable (${label})`, probe.rows > 0 && probe.hits === probe.rows,
      `${probe.hits}/${probe.rows} rows at scrollY ${probe.y}`);
  }
  await shot("phone-deep");

  check("no console errors", consoleErrors.length === 0, consoleErrors.join(" | "));
  console.log(`screenshots in ${PREVIEW}; headless Firefox peak RAM ${browser.peakMb()} MB, `
    + `${availableMb()} MB available now`);
} catch (error) {
  failures++;
  console.log(`FAIL  harness stopped: ${error.stack || error}`);
} finally {
  await browser.close();
}
process.exit(failures ? 1 : 0);
