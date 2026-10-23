// Takes the Phase 5 review screenshots into docs/screenshots/phase5/: every state at
// 1366x768 and 1920x1080, light and dark, plus a full-page shot at 1366 (light).
// States: the five demo scenarios, recording in progress, the controls panel open, and
// replay mode (with the panel open, so the progress bar shows).
//
// Needs: backend on http://127.0.0.1:8000 in simulator mode (MHM_SOURCE=simulator), the Vite
// dev server on http://127.0.0.1:5173, and `npm run screenshots:install` once.
//   npm run screenshots                 # everything
//   npm run screenshots -- recovery     # only some
//
// Four browser windows watch the same stream; each one shoots as soon as its own page shows
// the target state, so all four capture the same moment. The recording made for the replay
// shots is deleted at the end (data/recordings/ holds real data only).

import { mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

process.env.PLAYWRIGHT_BROWSERS_PATH = "0";          // the project-local Chromium
const { chromium } = await import("playwright");

const API = "http://127.0.0.1:8000";
const APP = "http://127.0.0.1:5173/";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = join(ROOT, "docs", "screenshots", "phase5");
const RECORDINGS = join(ROOT, "data", "recordings");

const VIEWS = [
  { w: 1366, h: 768, theme: "light", full: true },
  { w: 1366, h: 768, theme: "dark" },
  { w: 1920, h: 1080, theme: "light" },
  { w: 1920, h: 1080, theme: "dark" },
];

const overall = () => document.querySelector(".banner")?.getAttribute("data-overall");
const mlStatus = () => document.querySelector("[data-ml-status]")?.getAttribute("data-ml-status");

let recorded = null;   // file made by the "recording" step, replayed by "replay"

// `setup` changes the backend before the pages load; `prepare` runs per page after load
// (e.g. open the controls); `ready` runs in the page and returns true when the screen shows
// what the shot is for. `settle_s` lets the charts fill first.
const STEPS = [
  {
    name: "normal", settle_s: 30,
    setup: () => setSource({ type: "simulator", scenario: "normal", speed: 10 }),
    ready: `(${mlStatus})() === "OK" && (${overall})() === "NORMAL"`,
  },
  {
    name: "sudden_fault",
    setup: () => setSource({ type: "simulator", scenario: "sudden_fault", speed: 3 }),
    // A row clearly past the limit, not one dipping into the hysteresis band ("near").
    ready: `(${overall})() === "CRITICAL" && (${mlStatus})() === "ANOMALY"
      && !document.querySelector("[data-testid=headline]")?.textContent?.includes("near")`,
  },
  {
    name: "slow_drift",
    setup: () => setSource({ type: "simulator", scenario: "slow_drift", speed: 3 }),
    ready: `!!document.querySelector('.forecast-item[data-status="approaching"]')`,
  },
  {
    name: "recovery",
    setup: () => setSource({ type: "simulator", scenario: "recovery", speed: 1 }),
    ready: `document.querySelector(".banner")?.getAttribute("data-recovering") === "yes"`,
  },
  {
    name: "sensor_fault",
    setup: () => setSource({ type: "simulator", scenario: "sensor_fault", speed: 3 }),
    ready: `(${mlStatus})() === "ML_UNAVAILABLE" && !!document.querySelector('.sensor-card[data-status="fault"]')`,
  },
  {
    name: "recording", settle_s: 8,
    setup: async () => {
      await setSource({ type: "simulator", scenario: "sudden_fault", speed: 5 });
      await post("/api/record/start");
    },
    ready: `!!document.querySelector("[data-testid=rec-indicator]")
      && Number(document.querySelector("[data-testid=rec-indicator]").textContent.match(/(\\d+) rows/)?.[1]) >= 20`,
    after: async () => {
      await sleep(8);                                  // a little more data for the replay
      recorded = (await post("/api/record/stop")).file;
      console.log(`  recorded ${recorded}`);
    },
  },
  {
    name: "controls",
    setup: () => setSource({ type: "simulator", scenario: "normal", speed: 5 }),
    prepare: (page) => page.click("[data-testid=controls-toggle]"),
    ready: `!!document.querySelector("[data-testid=ctl-scenarios]") && (${overall})() === "NORMAL"`,
  },
  {
    name: "replay",
    setup: () => {
      if (!recorded) throw new Error("replay needs the recording step first");
      return setSource({ type: "replay", file: recorded, speed: 1, loop: true });
    },
    prepare: async (page) => {
      await page.click("[data-testid=controls-toggle]");
      await page.getByRole("button", { name: "Recorded", exact: true }).click();
    },
    ready: `document.querySelector("[data-testid=mode-badge]")?.textContent?.includes("RECORDED")
      && !!document.querySelector("[data-testid=replay-progress]")
      && document.querySelector(".banner")?.getAttribute("data-overall") !== "NORMAL"`,
  },
];

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path}: HTTP ${res.status} ${await res.text()}`);
  return res.json();
}

const setSource = (body) => post("/api/source", body);
const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));

const only = process.argv.slice(2);
const steps = only.length ? STEPS.filter((s) => only.includes(s.name)) : STEPS;
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const pages = [];
for (const v of VIEWS) {
  const ctx = await browser.newContext({ viewport: { width: v.w, height: v.h }, colorScheme: v.theme });
  await ctx.addInitScript((t) => {
    try { localStorage.setItem("mhm-theme", t); } catch { /* ignore */ }
  }, v.theme);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error(`  page error (${v.w}x${v.h} ${v.theme}): ${e.message}`));
  pages.push({ v, page });
}

const files = [];
try {
  for (const st of steps) {
    console.log(st.name);
    await st.setup();
    await Promise.all(pages.map(async ({ page }) => {
      await page.goto(APP);
      await page.waitForSelector("[data-testid=controls-toggle]");
      if (st.prepare) await st.prepare(page);
    }));
    if (st.settle_s) await sleep(st.settle_s);
    await Promise.all(pages.map(async ({ v, page }) => {
      await page.waitForFunction(st.ready, null, { timeout: 180_000, polling: 100 });
      await page.waitForTimeout(150);              // let the charts paint the same frame
      const base = `${st.name}_${v.w}x${v.h}_${v.theme}`;
      await page.screenshot({ path: join(OUT, `${base}.png`) });
      files.push(`${base}.png`);
      if (v.full) {
        await page.screenshot({ path: join(OUT, `${st.name}_full_${v.w}_${v.theme}.png`), fullPage: true });
        files.push(`${st.name}_full_${v.w}_${v.theme}.png`);
      }
      const headline = await page.textContent("[data-testid=headline]");
      console.log(`  ${v.w}x${v.h} ${v.theme}: ${headline}`);
    }));
    if (st.after) await st.after();
  }
} finally {
  await browser.close();
  await post("/api/record/stop").catch(() => {});
  await setSource({ type: "simulator", scenario: "normal", speed: 1 }).catch(() => {});
  if (recorded) {
    rmSync(join(RECORDINGS, recorded), { force: true });
    console.log(`deleted test recording ${recorded}`);
  }
}
console.log(`\n${files.length} files in ${OUT}`);
