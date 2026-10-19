#!/usr/bin/env node
// Browser check of the site with published figures: serves .preview/sample-docs/, the site tests/check_build.py
// builds from the synthetic tests/fixtures/bands.sample.json (run that first), and checks the figures and tooltips the
// page shows against the fixture. Same headless Firefox and RAM limits as tests/ui_check.mjs.
// Usage: python3 tests/check_build.py && node tests/ui_data_check.mjs   (exit status 1 if any check fails)
import { join } from "node:path";
import { FRAMES, PREVIEW, SETTLED, availableMb, openBrowser } from "./browser.mjs";

let failures = 0;
const check = (name, ok, detail = "") => {
  if (!ok) failures++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const browser = await openBrowser({ docs: join(PREVIEW, "sample-docs") });
const { run, shot, viewport, load, consoleErrors } = browser;
// a pair's row: whether it is on screen, and [text, title, class] per band column keyed by the column's header label
const cells = (id) => run(`async () => {
  await (${SETTLED})();
  await (${FRAMES})();
  const row = document.querySelector('.rows>.r[data-id="${id}"]'), labels = [...document.querySelectorAll("#hwrap .h .c")].map((c) => c.textContent);
  const out = { visible: !row.hidden && !row.closest(".g").hidden };
  [...row.children].forEach((cell, k) => {
    if (k) out[labels[k]] = [cell.textContent, cell.getAttribute("title"), cell.classList.contains("na") ? "na" : ""];
  });
  return out;
}`);
const search = (text) => run(`async () => { const q = document.getElementById("q"); q.value = ${JSON.stringify(text)};
  q.dispatchEvent(new Event("input", { bubbles: true })); return true; }`);
const same = (got, expected) => JSON.stringify(got) === JSON.stringify(expected);
const INTERPOLATED = "Interpolated between two adjacent verified sizes";
const BLOCK = " · block 26,211,593";

try {
  await viewport(1280, 1520);
  await load();
  const head = await run(`async () => ({ sum: document.querySelector(".sum").textContent, foot: document.querySelector(".foot").textContent })`);
  check("summary shows the publication time", head.sum.includes("Updated 2026-10-18 08:00 UTC"), head.sum);
  check("legend shown with published figures", head.foot.includes("≥ marks a band not reached"), head.foot);

  let got = await cells(6);
  check("WETH → USDC: on Ethereum's first page, all five bands in USD over WETH, tooltips with the block", same(got, {
    visible: true, "1%": ["$2.4M1,000 WETH", INTERPOLATED + BLOCK, ""], "2%": ["$4.8M2,000 WETH", INTERPOLATED + BLOCK, ""],
    "3%": ["$7.2M3,000 WETH", "Largest verified size inside the band" + BLOCK, ""],
    "5%": ["$12M5,000 WETH", INTERPOLATED + BLOCK, ""],
    "10%": ["≥ $120M≥ 50K WETH", "Band not reached at the largest verified size" + BLOCK, ""] }), JSON.stringify(got));
  await search("btc.b ausd");
  got = await cells(810);
  check("BTC.b → AUSD (found by search): below-smallest-size bound, missing bands as —", same(got, {
    visible: true, "1%": ["< $50K< 0.5 BTC.b", "The smallest verified size already exceeds the band", ""],
    "2%": ["$125K1.25 BTC.b", INTERPOLATED, ""], "3%": ["—", null, "na"], "5%": ["$1.25M12.5 BTC.b", INTERPOLATED, ""],
    "10%": ["—", null, "na"] }), JSON.stringify(got));
  await search("weth usdc");
  await run(`async () => { document.querySelector('#bands [data-band="10"]').click(); await (${FRAMES})(); return true; }`);
  await shot("sample-figures");
  check("no console errors", consoleErrors.length === 0, consoleErrors.join(" | "));
  console.log(`headless Firefox peak RAM ${browser.peakMb()} MB, ${availableMb()} MB available now`);
} catch (error) {
  failures++;
  console.log(`FAIL  harness stopped: ${error.stack || error}`);
} finally {
  await browser.close();
}
process.exit(failures ? 1 : 0);
