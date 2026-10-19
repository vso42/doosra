// doosra · Slippage bands. build.py inlines this file at the end of the page. Every row is already in the HTML, each
// chain's first page visible, so this only wires the theme, chain, band and search controls, the pages, the chain
// folds and the sticky header.
(() => {
  "use strict";
  const d = document, root = d.documentElement, $ = (id) => d.getElementById(id);
  const tbl = $("tbl"), scroller = $("scroll"), hwrap = $("hwrap"), head = hwrap.querySelector(".h"), counts = $("counts"),
    empty = $("empty"), emptyText = $("empty-text"), search = $("q"), themeBtn = $("theme"),
    metaTheme = d.querySelector('meta[name="theme-color"]'), selCss = $("sel"), bar = $("hl");
  const PAGE = +tbl.dataset.page;
  const plural = (n, word) => n.toLocaleString("en-US") + " " + word + (n === 1 ? "" : "s");
  const norm = (text) => text.toLowerCase().replace(/₮/g, "t");

  // theme: saved choice, set before first paint by the inline script in <head>
  const paintTheme = () => {
    const light = root.dataset.theme === "light";
    themeBtn.setAttribute("aria-label", light ? "Switch to dark theme" : "Switch to light theme");
    metaTheme.content = light ? "#f3f1ec" : "#000000";
  };
  themeBtn.addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
    try { localStorage.setItem("doosra-theme", root.dataset.theme); } catch (e) { /* private mode */ }
    paintTheme();
  });
  paintTheme();

  // Rows a filter brings back show a screenful at a time: data-rn in the same frame, then data-rf per frame
  // (build.py config). A newer filter replaces an unfinished job, and a row shows only if its page still wants it.
  let job = null;
  const reveal = (rows) => {
    const mine = (job = {});
    let next = 0;
    const step = (count) => {
      if (job !== mine) return;
      for (const end = Math.min(rows.length, next + count); next < end; next++) if (rows[next].want) rows[next].el.hidden = false;
      if (next < rows.length) requestAnimationFrame(() => step(+tbl.dataset.rf));
    };
    step(+tbl.dataset.rn);
  };

  // pages: the same markup as build.py's pager() and page_window(), 7 slots once a chain has more than 7 pages
  const pageWindow = (current, total) => {
    if (total <= 7) return Array.from({ length: total }, (_, k) => k + 1);
    if (current <= 4) return [1, 2, 3, 4, 5, 0, total];
    if (current >= total - 3) return [1, 0, total - 4, total - 3, total - 2, total - 1, total];
    return [1, 0, current - 1, current, current + 1, 0, total];
  };
  const pagerHtml = (page, count) => {
    const pages = Math.ceil(count / PAGE);
    let html = '<button type="button" class="pb" data-to="prev" aria-label="Previous page"' + (page === 1 ? " disabled" : "")
      + ">‹</button>";
    for (const shown of pageWindow(page, pages)) {
      html += shown ? '<button type="button" class="pb" data-to="' + shown + '" aria-label="Page ' + shown + '"'
        + (shown === page ? ' aria-current="page"' : "") + ">" + shown + "</button>"
        : '<span class="gap" aria-hidden="true">…</span>';
    }
    html += '<button type="button" class="pb" data-to="next" aria-label="Next page"' + (page === pages ? " disabled" : "")
      + ">›</button>";
    return html + '<span class="pr">' + ((page - 1) * PAGE + 1) + "–" + Math.min(page * PAGE, count) + " of "
      + count.toLocaleString("en-US") + "</span>";
  };

  // chain groups: every row with its search text; `matches` are the rows the filters keep, `visible` the current page
  const groups = Array.from(scroller.querySelectorAll(".g"), (el) => {
    const rows = Array.from(el.querySelectorAll(".rows>.r"), (row) => ({ el: row, hay: row.dataset.q + " " + el.dataset.name }));
    rows.forEach((r, k) => { r.want = k < PAGE; });
    return { el, chain: el.dataset.chain, count: el.querySelector(".gn"), pagerRow: el.querySelector(".pgr"),
      pager: el.querySelector(".pg"), rows, matches: rows, page: 1, visible: rows.slice(0, PAGE), shown: rows.length };
  });

  // a chain's page of its matching rows: rows leaving are hidden at once, rows coming in are added to `incoming`
  const showPage = (g, page, incoming) => {
    const pages = Math.max(1, Math.ceil(g.matches.length / PAGE));
    g.page = Math.min(Math.max(1, page), pages);
    const next = g.matches.slice((g.page - 1) * PAGE, g.page * PAGE), keep = new Set(next);
    for (const r of g.visible) if (!keep.has(r)) { r.want = false; r.el.hidden = true; }
    for (const r of next) { r.want = true; if (r.el.hidden) incoming.push(r); }
    g.visible = next;
    const paged = pages > 1;
    if (g.pagerRow.hidden === paged) g.pagerRow.hidden = !paged;
    if (paged) g.pager.innerHTML = pagerHtml(g.page, g.matches.length);
  };

  // filters: a row matches when its chain is picked and it holds every search term; each chain restarts at page 1
  const picked = new Set();
  const apply = () => {
    const raw = search.value.trim();
    const terms = norm(raw).split(/[^a-z0-9.]+/).map((t) => t.replace(/^\.+|\.+$/g, "")).filter(Boolean);
    const incoming = [];
    let pairs = 0, chains = 0;
    for (const g of groups) {
      const on = picked.size === 0 || picked.has(g.chain);
      g.matches = !on ? [] : terms.length ? g.rows.filter((r) => terms.every((t) => r.hay.includes(t))) : g.rows;
      const n = g.matches.length;
      if (!n) {
        if (!g.el.hidden) g.el.hidden = true; // hide the group first: its rows then change out of sight
        for (const r of g.visible) { r.want = false; r.el.hidden = true; }
        g.visible = [];
        continue;
      }
      showPage(g, 1, incoming);
      if (g.el.hidden) g.el.hidden = false;
      if (g.shown !== n) { g.count.textContent = plural(n, "pair"); g.shown = n; }
      pairs += n;
      chains++;
    }
    counts.textContent = plural(pairs, "pair") + " · " + plural(chains, "chain");
    const none = pairs === 0;
    empty.hidden = !none;
    hwrap.hidden = scroller.hidden = none;
    if (none) emptyText.textContent = terms.length ? "No pairs match “" + raw + "”." : "No pairs on these chains.";
    reveal(incoming);
  };

  let frame = 0;
  search.addEventListener("input", () => {
    if (!frame) frame = requestAnimationFrame(() => { frame = 0; apply(); });
  });

  const chainBox = $("chains"), chainBtns = Array.from(chainBox.querySelectorAll("button"));
  const paintChains = () => {
    for (const b of chainBtns) {
      b.setAttribute("aria-pressed", String(b.dataset.chain ? picked.has(b.dataset.chain) : picked.size === 0));
    }
  };
  chainBox.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const chain = b.dataset.chain;
    if (!chain) picked.clear();
    else {
      if (picked.has(chain)) picked.delete(chain); else picked.add(chain);
      if (picked.size === groups.length) picked.clear();
    }
    paintChains();
    apply();
  });
  $("clear").addEventListener("click", () => {
    search.value = "";
    picked.clear();
    paintChains();
    apply();
  });

  // the selected column: its header cell carries .on and one bar sits behind the column, so a band change touches
  // three elements whatever the number of rows; the bar follows the header cell when the table is resized
  let headOn = null;
  const placeBar = () => {
    if (!headOn || !headOn.offsetWidth) return; // table hidden: placed again when it shows
    bar.style.width = headOn.offsetWidth + "px";
    bar.style.transform = "translateX(" + headOn.offsetLeft + "px)";
  };
  const highlight = (band) => {
    const cell = head.querySelector(".b" + band);
    if (headOn !== cell) {
      if (headOn) headOn.classList.remove("on");
      cell.classList.add("on");
      headOn = cell;
    }
    placeBar();
  };
  new ResizeObserver(placeBar).observe(hwrap.firstElementChild);
  const bandBox = $("bands"), bandBtns = Array.from(bandBox.querySelectorAll("button[data-band]"));
  bandBox.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-band]");
    if (!b) return;
    tbl.dataset.sel = b.dataset.band;
    highlight(+b.dataset.band);
    for (const x of bandBtns) x.setAttribute("aria-pressed", String(x === b));
  });

  // pager buttons and chain folds, one listener for the whole table
  scroller.addEventListener("click", (e) => {
    const b = e.target.closest(".pb, .fold");
    if (!b || b.disabled) return;
    if (b.classList.contains("fold")) {
      const open = b.getAttribute("aria-expanded") !== "true";
      b.setAttribute("aria-expanded", String(open));
      b.closest(".g").classList.toggle("folded", !open);
      return;
    }
    const g = groups.find((x) => x.pager === b.parentNode), to = b.dataset.to, focused = d.activeElement === b;
    const incoming = [];
    showPage(g, to === "prev" ? g.page - 1 : to === "next" ? g.page + 1 : +to, incoming);
    for (const r of incoming) r.el.hidden = false; // one page: at most PAGE rows
    if (focused) { // the pager was rebuilt: keep keyboard focus on the same control, else on the current page
      const again = g.pager.querySelector('[data-to="' + to + '"]:not(:disabled)') || g.pager.querySelector("[aria-current]");
      again.focus({ preventScroll: true });
    }
  });

  // the column header sits outside the horizontal scroller so it can stick to the top of the window
  scroller.addEventListener("scroll", () => { hwrap.scrollLeft = scroller.scrollLeft; }, { passive: true });

  // from the built page's static tint of the default column to the bar, in one task so no frame shows neither
  highlight(+tbl.dataset.sel);
  selCss.textContent = "";
  bar.hidden = false;

  // a search the browser restored on back/forward navigation
  if (search.value) apply();
})();
