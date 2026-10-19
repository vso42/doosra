#!/usr/bin/env node
// Browser check of what goes public: docs/ holds the page and data/figures.json only, figures.json carries exactly the
// band figures of the local data/bands.json (data/ is not in the repo) and nothing private, and the page shows no hashes,
// offers no downloads and fetches no data. Same headless Firefox and RAM limits as tests/ui_check.mjs.
// Usage: python3 build.py && node tests/ui_publish_check.mjs   (exit status 1 if any check fails)
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

const listed = new Set(read("data/pairs.json").pairs.map((p) => String(p.pair_id)));
const bands = read("data/bands.json");

const published = readdirSync(join(ROOT, "docs/data"));
check("docs/data holds figures.json and nothing else", same(published, ["figures.json"]), published);
const text = readFileSync(join(ROOT, "docs/data/figures.json"), "utf8"), figures = JSON.parse(text);
check("figures.json has no local paths, file hashes, block hashes or provenance",
  !/\/home\/|sha256|provenance|0x[0-9a-fA-F]{64}/.test(text), text.match(/\/home\/[^"]{0,40}|sha256|provenance|0x[0-9a-fA-F]{64}/)?.[0]);
check("figures.json keeps only the update time and the band figures",
  same(Object.keys(figures).sort(), ["pairs", "updated"]), Object.keys(figures));
const bandIds = Object.keys(bands.pairs).filter((id) => listed.has(id) && Object.keys(bands.pairs[id].bands || {}).length);
check(`figures.json lists every published pair (${bandIds.length})`,
  same(Object.keys(figures.pairs).sort(), [...bandIds].sort()), Object.keys(figures.pairs).length);
const wrong = bandIds.filter((id) => Object.entries(bands.pairs[id].bands).some(([band, f]) => {
  const got = figures.pairs[id]?.bands?.[band];
  return !got || got.amount !== f.amount || got.usd !== f.usd || got.kind !== f.kind;
}));
check("figures.json band amounts, USD values and kinds equal data/bands.json", !wrong.length, wrong.slice(0, 5));

const browser = await openBrowser();
try {
  await browser.viewport(1280, 1520);
  await browser.load();
  const state = await browser.run(`async () => ({
    requests: performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/data/")),
    downloads: document.querySelectorAll('a[download],a[href*="/data/"],a[href$=".json"],a[href$=".csv"]').length,
    header: document.querySelector("#depth-title").textContent,
    modelTitle: document.querySelector(".rows .c[title]")?.title || "",
    hashTitles: [...document.querySelectorAll("[title]")].filter((e) => /hash|0x[0-9a-fA-F]{64}/.test(e.title)).map((e) => e.title).slice(0, 3),
    avalanche: document.querySelector('.g[data-chain="avalanche"] .chain-note')?.textContent,
    afterNote: document.querySelector(".foot")?.nextElementSibling?.outerHTML.slice(0, 80) || null,
  })`);
  check("band figures labeled model estimates", state.header.includes("model estimates")
    && state.modelTitle.includes("contract execution unverified"), { header: state.header, title: state.modelTitle });
  check("no tooltip shows a hash", !state.hashTitles.length, state.hashTitles);
  check("no download links and no data fetched by the page", !state.downloads && !state.requests.length, state.requests);
  check("Avalanche note kept", state.avalanche === "Still struggling on bin counting; will provide soon.", state.avalanche);
  check("nothing below the band table's note", state.afterNote === null, state.afterNote);

  await browser.viewport(390, 844);
  await browser.load();
  const phone = await browser.run(`async () => { await (${FRAMES})();
    return { page: document.documentElement.scrollWidth, viewport: innerWidth }; }`);
  check("phone: no sideways page scroll", phone.page <= phone.viewport, phone);
  check("no console errors", browser.consoleErrors.length === 0, browser.consoleErrors);
  console.log(`headless Firefox peak RAM ${browser.peakMb()} MB`);
} catch (error) {
  check("browser harness completes", false, error.stack || String(error));
} finally {
  await browser.close();
}
process.exit(failures ? 1 : 0);
