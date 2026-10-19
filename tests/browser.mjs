// Shared by tests/ui_check.mjs and tests/ui_data_check.mjs: serves docs/ on localhost and drives one lean headless
// Firefox over WebDriver BiDi with Node's built-in WebSocket (no packages). Screenshots and the throwaway Firefox
// profile go to .preview/ (git-ignored).
// RAM: Firefox starts only if MIN_AVAILABLE_MB stays free after its expected FIREFOX_MB, every page step re-checks
// and the run stops, closing Firefox, once less than MIN_AVAILABLE_MB is available. Firefox is always closed from
// inside, also on Ctrl+C, SIGTERM or the WATCHDOG_S deadline: a snap Firefox refuses signals from a sandboxed shell,
// so a killed run could otherwise leave it running.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const MIN_AVAILABLE_MB = 2048; // RAM left to everything else on the machine, never used by these checks
const FIREFOX_MB = 700; // expected peak of the lean headless Firefox below
const WATCHDOG_S = 240;
// one content process, no prelaunched spare, no separate network, media or extension processes
const LEAN_PREFS = {
  "fission.autostart": false, "dom.ipc.processCount": 1, "dom.ipc.processCount.webIsolated": 1,
  "dom.ipc.processPrelaunch.enabled": false, "extensions.webextensions.remote": false, "network.process.enabled": false,
  "media.rdd-process.enabled": false, "browser.cache.disk.enable": false, "browser.sessionstore.resume_from_crash": false,
};

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
export const PREVIEW = join(ROOT, ".preview");
const DOCS = join(ROOT, "docs");
const PROFILE_PREFIX = join(PREVIEW, "firefox-profile"), PROFILE = `${PROFILE_PREFIX}-${process.pid}`;
const TYPES = { ".html": "text/html; charset=utf-8", ".json": "application/json", ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8" };

export const availableMb = () => {
  const line = readFileSync("/proc/meminfo", "utf8").split("\n").find((l) => l.startsWith("MemAvailable:"));
  return Math.floor(+line.split(/\s+/)[1] / 1024);
};
const processes = () => readdirSync("/proc").filter((name) => /^\d+$/.test(name)).map((pid) => {
  try {
    const status = readFileSync(`/proc/${pid}/status`, "utf8");
    return { pid: +pid, ppid: +/PPid:\s+(\d+)/.exec(status)[1], rssKb: +(/VmRSS:\s+(\d+)/.exec(status) || [0, 0])[1],
      command: readFileSync(`/proc/${pid}/cmdline`, "utf8").split("\0").join(" ") };
  } catch (e) { return null; }
}).filter(Boolean);

// one WebDriver BiDi connection: send(method, params) -> result; events go to onEvent
const connect = async (port, onEvent = () => {}) => {
  const ws = new WebSocket(`ws://127.0.0.1:${port}/session`);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = () => reject(new Error(`no WebDriver BiDi on port ${port}`));
    setTimeout(() => reject(new Error(`WebDriver BiDi on port ${port} did not open in 10 s`)), 10000);
  }).catch((error) => { ws.close(); throw error; });
  const pending = new Map();
  let nextId = 0;
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.method) onEvent(message);
    if (message.id === undefined || !pending.has(message.id)) return;
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.type === "error") reject(new Error(`${message.error}: ${message.message}`)); else resolve(message.result);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method}: no answer in 30 s`)); }, 30000);
    pending.set(id, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
    ws.send(JSON.stringify({ id, method, params }));
  });
  return { send, close: () => ws.close() };
};

// a headless Firefox an earlier run left: closed from inside over its own BiDi port when its session has ended;
// one whose session is still open is reported (stop it from a normal terminal)
const closeLeftovers = async () => {
  for (const proc of processes()) {
    const port = proc.command.includes(PROFILE_PREFIX) && /--remote-debugging-port=(\d+)/.exec(proc.command);
    if (!port) continue;
    let old = null;
    try {
      old = await connect(port[1]);
      await old.send("session.new", { capabilities: {} });
      await Promise.race([old.send("browser.close", {}), new Promise((r) => setTimeout(r, 5000))]);
      console.log(`closed the headless Firefox left by an earlier run (pid ${proc.pid})`);
    } catch (error) {
      console.log(`note: an earlier run's headless Firefox (pid ${proc.pid}, ${Math.round(proc.rssKb / 1024)} MB) is still `
        + `open (${error.message}). Stop it from a normal terminal: pkill -f 'site/.preview/firefox-profile'`);
    } finally {
      if (old) old.close(); // an open socket would keep this process alive after the run
    }
  }
  mkdirSync(PREVIEW, { recursive: true });
  for (const entry of readdirSync(PREVIEW, { withFileTypes: true })) {
    const path = join(PREVIEW, entry.name);
    if (entry.isDirectory() && path.startsWith(PROFILE_PREFIX) && !path.endsWith(`-${process.pid}`)
        && !processes().some((p) => p.command.includes(path))) {
      rmSync(path, { recursive: true, force: true });
    }
  }
};

export async function openBrowser({ docs = DOCS } = {}) {
  await closeLeftovers();
  const free = availableMb();
  if (free < MIN_AVAILABLE_MB + FIREFOX_MB) {
    throw new Error(`only ${free} MB RAM available: Firefox needs about ${FIREFOX_MB} MB and ${MIN_AVAILABLE_MB} MB must `
      + "stay free, so the browser checks did not start");
  }
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
    const file = normalize(join(docs, path.endsWith("/") ? path + "index.html" : path));
    if (!file.startsWith(docs) || !existsSync(file)) { res.writeHead(404).end(); return; }
    res.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream" }).end(readFileSync(file));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const port = await new Promise((resolve) => {
    const probe = createServer().listen(0, "127.0.0.1", () => { const { port: p } = probe.address(); probe.close(() => resolve(p)); });
  });
  mkdirSync(PROFILE, { recursive: true });
  writeFileSync(join(PROFILE, "user.js"),
    Object.entries(LEAN_PREFS).map(([key, value]) => `user_pref(${JSON.stringify(key)}, ${JSON.stringify(value)});`).join("\n") + "\n");
  const firefox = spawn("firefox", ["--headless", "--no-remote", "--profile", PROFILE, `--remote-debugging-port=${port}`,
    "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
  let log = "";
  await new Promise((resolve, reject) => {
    firefox.stderr.on("data", (chunk) => { log += chunk; if (log.includes("WebDriver BiDi listening")) resolve(); });
    firefox.on("exit", (code) => reject(new Error(`firefox exited ${code}\n${log}`)));
    setTimeout(() => reject(new Error(`firefox did not open WebDriver BiDi\n${log}`)), 30000);
  });

  // RAM of this Firefox: its main process (found by the profile path; the snap launcher re-parents it) and children
  let peakMb = 0;
  const sample = () => {
    const all = processes(), main = all.find((p) => p.command.includes(PROFILE) && !p.command.includes("-contentproc"));
    if (!main) return;
    const mb = Math.round(all.filter((p) => p.pid === main.pid || p.ppid === main.pid).reduce((s, p) => s + p.rssKb, 0) / 1024);
    peakMb = Math.max(peakMb, mb);
  };
  const sampler = setInterval(sample, 1000);

  const consoleErrors = [];
  const { send, close } = await connect(port, (message) => {
    if (message.method === "log.entryAdded" && message.params.level === "error") consoleErrors.push(message.params.text);
  });
  let closed = false, watchdog = null;
  const shutdown = async () => {
    if (closed) return;
    closed = true;
    clearInterval(sampler);
    clearTimeout(watchdog);
    const exited = new Promise((resolve) => firefox.once("exit", resolve));
    try { await Promise.race([send("browser.close", {}), new Promise((r) => setTimeout(r, 5000))]); } catch (e) { /* gone */ }
    await Promise.race([exited, new Promise((r) => setTimeout(r, 10000))]);
    close();
    server.close();
    const stillOpen = processes().some((p) => p.command.includes(PROFILE));
    if (stillOpen) console.log("note: headless Firefox did not close; stop it with: pkill -f 'site/.preview/firefox-profile'");
    else rmSync(PROFILE, { recursive: true, force: true });
  };
  const stop = (why, code) => async () => { console.log(`stopping: ${why}`); await shutdown(); process.exit(code); };
  process.once("SIGINT", stop("interrupted", 130));
  process.once("SIGTERM", stop("terminated", 143));
  watchdog = setTimeout(stop(`the run passed its ${WATCHDOG_S} s deadline`, 1), WATCHDOG_S * 1000);

  await send("session.new", { capabilities: {} });
  await send("session.subscribe", { events: ["log.entryAdded"] });
  const { contexts } = await send("browsingContext.getTree", {});
  const context = contexts[0].context;

  // run(source of an async page function) -> its JSON-serializable result; refuses once RAM runs short
  const run = async (fn) => {
    const left = availableMb();
    if (left < MIN_AVAILABLE_MB) throw new Error(`stopped to keep RAM free: ${left} MB available, under ${MIN_AVAILABLE_MB} MB`);
    const reply = await send("script.evaluate", { expression: `(async () => JSON.stringify((await (${fn})()) ?? null))()`,
      target: { context }, awaitPromise: true, resultOwnership: "none" })
      .catch((error) => { throw new Error(`${error.message} in page step: ${fn.replace(/\s+/g, " ").slice(0, 160)}`); });
    if (reply.type !== "success") throw new Error(JSON.stringify(reply.exceptionDetails));
    return JSON.parse(reply.result.value);
  };
  let loads = 0;
  return {
    url, run, consoleErrors,
    peakMb: () => { sample(); return peakMb; },
    // a distinct URL per load: a navigation to the current URL has stalled headless Firefox now and then
    load: async () => {
      await send("browsingContext.navigate", { context, url: `${url}?load=${++loads}`, wait: "complete" });
      await run(`async () => { await Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 5000))]); return true; }`);
    },
    viewport: (width, height) => send("browsingContext.setViewport", { context, viewport: { width, height }, devicePixelRatio: 1 }),
    shot: async (name) => {
      const { data } = await send("browsingContext.captureScreenshot", { context, origin: "viewport" });
      writeFileSync(join(PREVIEW, `${name}.png`), Buffer.from(data, "base64"));
    },
    close: shutdown,
  };
}

// page-side helpers, as source to splice into run() functions
export const FRAMES = `() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))`;
// rows a filter brings back show over a few frames: wait one frame for the filter to run, then until every visible
// chain shows its current page (up to data-page rows of the pairs its header counts)
export const SETTLED = `async () => {
  await new Promise((r) => requestAnimationFrame(r));
  const size = +document.getElementById("tbl").dataset.page;
  const expected = () => [...document.querySelectorAll(".g:not([hidden])")].reduce((sum, g) => {
    const n = +g.querySelector(".gn").textContent.replace(/,/g, "").split(" ")[0];
    const current = g.querySelector(".pgr:not([hidden]) [aria-current]"), page = current ? +current.dataset.to : 1;
    return sum + Math.max(0, Math.min(size, n - (page - 1) * size));
  }, 0);
  const shown = () => document.querySelectorAll(".g:not([hidden]) .rows>.r:not([hidden])").length;
  for (let i = 0; i < 240 && shown() !== expected(); i++) await new Promise((r) => requestAnimationFrame(r));
  return true;
}`;
