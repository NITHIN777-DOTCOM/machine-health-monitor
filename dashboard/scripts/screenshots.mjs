// Takes the Phase 4 review screenshots: every scenario at 1366x768 and 1920x1080, light and
// dark, plus a full-page shot at 1366 (light). Saved to docs/screenshots/phase4/.
//
// Needs: backend on http://127.0.0.1:8000 in simulator mode (MHM_PORT=COM_NONE), the Vite
// dev server on http://127.0.0.1:5173, and `npm run screenshots:install` once.
//   npm run screenshots                 # all scenarios
//   npm run screenshots -- recovery     # only some
//
// Four browser windows watch the same stream; each one shoots as soon as its own page shows
// the target state (e.g. the recovery countdown), so all four capture the same moment.

import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

process.env.PLAYWRIGHT_BROWSERS_PATH = "0";          // the project-local Chromium
const { chromium } = await import("playwright");

const API = "http://127.0.0.1:8000";
const APP = "http://127.0.0.1:5173/";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "screenshots", "phase4");

const VIEWS = [
  { w: 1366, h: 768, theme: "light", full: true },
  { w: 1366, h: 768, theme: "dark" },
  { w: 1920, h: 1080, theme: "light" },
  { w: 1920, h: 1080, theme: "dark" },
];

// `ready` runs in the page and returns true when the screen shows what the shot is for.
// `settle_s` lets charts fill before waiting starts.
const SCENARIOS = [
  {
    name: "normal", speed: 10, settle_s: 30,
    ready: () => document.querySelector("[data-ml-status]")?.getAttribute("data-ml-status") === "OK"
      && document.querySelector(".banner")?.getAttribute("data-overall") === "NORMAL",
  },
  {
    name: "sudden_fault", speed: 3, settle_s: 0,
    // A row clearly past the limit, not one dipping into the hysteresis band ("near crit").
    ready: () => document.querySelector(".banner")?.getAttribute("data-overall") === "CRITICAL"
      && document.querySelector("[data-ml-status]")?.getAttribute("data-ml-status") === "ANOMALY"
      && !document.querySelector("[data-testid=headline]")?.textContent?.includes("near"),
  },
  {
    name: "slow_drift", speed: 3, settle_s: 0,
    // ML flags the rising vibration (WARNING, source ML) before the temperature trend is
    // steady enough to forecast, so the shot shows both: ML first, then the time to limit.
    ready: () => !!document.querySelector('.forecast-item[data-status="approaching"]'),
  },
  {
    name: "recovery", speed: 1, settle_s: 0,
    ready: () => document.querySelector(".banner")?.getAttribute("data-recovering") === "yes",
  },
  {
    name: "sensor_fault", speed: 3, settle_s: 0,
    ready: () => document.querySelector("[data-ml-status]")?.getAttribute("data-ml-status") === "ML_UNAVAILABLE"
      && !!document.querySelector('.sensor-card[data-status="fault"]'),
  },
];

async function setSource(scenario, speed) {
  const res = await fetch(`${API}/api/source`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type: "simulator", scenario, speed }),
  });
  if (!res.ok) throw new Error(`POST /api/source ${scenario}: HTTP ${res.status} ${await res.text()}`);
}

const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));

const only = process.argv.slice(2);
const scenarios = only.length ? SCENARIOS.filter((s) => only.includes(s.name)) : SCENARIOS;
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
  for (const sc of scenarios) {
    console.log(`${sc.name}: simulator at ${sc.speed}x`);
    await setSource(sc.name, sc.speed);
    await Promise.all(pages.map(({ page }) => page.goto(APP)));
    if (sc.settle_s) await sleep(sc.settle_s);
    await Promise.all(pages.map(async ({ v, page }) => {
      await page.waitForFunction(sc.ready, null, { timeout: 180_000, polling: 100 });
      await page.waitForTimeout(150);              // let the charts paint the same frame
      const base = `${sc.name}_${v.w}x${v.h}_${v.theme}`;
      await page.screenshot({ path: join(OUT, `${base}.png`) });
      files.push(`${base}.png`);
      if (v.full) {
        await page.screenshot({ path: join(OUT, `${sc.name}_full_${v.w}_${v.theme}.png`), fullPage: true });
        files.push(`${sc.name}_full_${v.w}_${v.theme}.png`);
      }
      const headline = await page.textContent("[data-testid=headline]");
      console.log(`  ${v.w}x${v.h} ${v.theme}: ${headline}`);
    }));
  }
} finally {
  await browser.close();
  await setSource("normal", 1).catch(() => {});
}
console.log(`\n${files.length} files in ${OUT}`);
