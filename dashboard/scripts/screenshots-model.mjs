// Phase 8.2 screenshots of the Model panel into docs/screenshots/phase8/: 1366x768 and
// 1920x1080, light and dark, with the "Live labels" table, plus the "Cleaned labels" view
// and the ML card's model tag (1366 light).
//
// Needs: the backend on API (default http://127.0.0.1:8000) in simulator mode
// (MHM_SOURCE=simulator) and the dashboard on APP (default the Vite dev server,
// http://127.0.0.1:5173/). `npm run screenshots:install` once.
//   npm run screenshots:model
//   API=http://127.0.0.1:8010 APP=http://127.0.0.1:8010/ npm run screenshots:model   # FastAPI serves the build

import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

process.env.PLAYWRIGHT_BROWSERS_PATH = "0";          // the project-local Chromium
const { chromium } = await import("playwright");

const API = process.env.API ?? "http://127.0.0.1:8000";
const APP = process.env.APP ?? "http://127.0.0.1:5173/";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = join(ROOT, "docs", "screenshots", "phase8");
const VIEWS = [
  { w: 1366, h: 768, theme: "light" },
  { w: 1366, h: 768, theme: "dark" },
  { w: 1920, h: 1080, theme: "light" },
  { w: 1920, h: 1080, theme: "dark" },
];

mkdirSync(OUT, { recursive: true });
const res = await fetch(`${API}/api/source`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ type: "simulator", scenario: "normal", speed: 5 }),
});
if (!res.ok) throw new Error(`POST /api/source: HTTP ${res.status}`);

const browser = await chromium.launch();
for (const v of VIEWS) {
  const ctx = await browser.newContext({ viewport: { width: v.w, height: v.h }, colorScheme: v.theme });
  await ctx.addInitScript((t) => {
    try { localStorage.setItem("mhm-theme", t); } catch { /* ignore */ }
  }, v.theme);
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error(`  page error (${v.w}x${v.h} ${v.theme}): ${e.message}`));
  await page.goto(APP);
  await page.waitForFunction(() => document.querySelector("[data-ml-status]")?.getAttribute("data-ml-status") === "OK",
    null, { timeout: 60_000 });
  await page.click("[data-testid=model-toggle]");
  await page.waitForSelector("[data-testid=eval-table] tbody tr");
  await page.waitForSelector("[data-testid=model-chart] .recharts-line");
  await page.waitForTimeout(500);
  const base = `model_panel_${v.w}x${v.h}_${v.theme}`;
  await page.screenshot({ path: join(OUT, `${base}.png`) });
  // The whole drawer: it normally scrolls on its own, so lift the height limit first.
  await page.locator("[data-testid=model-panel]").evaluate((el) => { el.style.maxHeight = "none"; el.style.position = "static"; });
  await page.locator("[data-testid=model-panel]").screenshot({ path: join(OUT, `${base}_drawer.png`) });
  if (v.w === 1366 && v.theme === "light") {
    await page.getByRole("button", { name: "Cleaned labels" }).click();
    await page.waitForTimeout(300);
    await page.locator("[data-testid=model-panel]").screenshot({ path: join(OUT, "model_panel_cleaned_labels_drawer.png") });
    await page.click("[data-testid=model-toggle]");
    await page.locator("[aria-labelledby=ml-title]").screenshot({ path: join(OUT, "ml_card_model_tag.png") });
  }
  console.log(`  ${base}: ok`);
  await ctx.close();
}
await browser.close();
console.log(`screenshots in ${OUT}`);
