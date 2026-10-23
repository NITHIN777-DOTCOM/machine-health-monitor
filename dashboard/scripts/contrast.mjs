// WCAG contrast check of the colour tokens in src/styles.css, both themes.
//   node scripts/contrast.mjs
// Text pairs need 4.5:1 (AA normal text); UI pairs (bars, chart lines, dots) need 3:1.
// Exits with code 1 if any pair fails.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "styles.css"), "utf8");

function block(selector) {
  const i = css.indexOf(selector + " {");
  if (i < 0) throw new Error(`no ${selector} block`);
  const body = css.slice(i, css.indexOf("\n}", i));
  const vars = {};
  for (const m of body.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})/g)) vars[m[1]] = m[2];
  return vars;
}

const light = block(":root");
const dark = { ...light, ...block(':root[data-theme="dark"]') };

function lum(hex) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function ratio(a, b) {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

// [foreground, background, minimum]
const PAIRS = [
  ["--text", "--bg", 4.5], ["--text", "--surface", 4.5], ["--text", "--surface-2", 4.5],
  ["--muted", "--surface", 4.5], ["--muted", "--bg", 4.5], ["--muted", "--surface-2", 4.5],
  ["--accent-text", "--surface", 4.5], ["--accent-text", "--bg", 4.5],
  ["--accent", "--surface", 3], ["--accent-fg", "--accent-strong", 4.5],
  ["--st-normal-text", "--surface", 4.5], ["--st-warning-text", "--surface", 4.5],
  ["--st-critical-text", "--surface", 4.5], ["--st-ml-text", "--surface", 4.5],
  ["--st-normal", "--surface", 3], ["--st-warning", "--surface", 3],
  ["--st-critical", "--surface", 3], ["--st-ml", "--surface", 3],
  ["--st-critical-fg", "--st-critical-strong", 4.5],
  ["--limit-warn", "--surface", 3], ["--limit-crit", "--surface", 3],
];

let failed = 0;
for (const [name, vars] of [["light", light], ["dark", dark]]) {
  console.log(`\n${name} theme`);
  for (const [fg, bg, min] of PAIRS) {
    if (!vars[fg] || !vars[bg]) { console.log(`  MISSING ${fg} / ${bg}`); failed++; continue; }
    const r = ratio(vars[fg], vars[bg]);
    const ok = r >= min;
    if (!ok) failed++;
    console.log(`  ${ok ? "ok  " : "FAIL"} ${r.toFixed(2).padStart(5)}:1 (min ${min})  ${fg} ${vars[fg]} on ${bg} ${vars[bg]}`);
  }
}
if (failed) {
  console.log(`\n${failed} pair(s) below the minimum`);
  process.exit(1);
}
console.log("\nall pairs pass");
