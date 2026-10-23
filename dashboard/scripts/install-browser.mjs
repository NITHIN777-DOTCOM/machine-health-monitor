// Installs Playwright's Chromium inside this project (node_modules/playwright-core/.local-browsers)
// instead of the user-wide cache. Only needed for `npm run screenshots`.
import { spawnSync } from "node:child_process";

const env = { ...process.env, PLAYWRIGHT_BROWSERS_PATH: "0" };
const res = spawnSync("npx", ["playwright", "install", "chromium"], { stdio: "inherit", env, shell: true });
process.exit(res.status ?? 1);
