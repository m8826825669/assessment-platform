import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./browser",
  fullyParallel: false,
  workers: 1,
  timeout: 180000,
  retries: 0,
  reporter: [["list"]],
  outputDir: "../artifacts/browser",
  use: {
    baseURL: "http://127.0.0.1:14173",
    browserName: "chromium",
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  webServer: {
    command: "npm run dev -- --port 14173",
    url: "http://127.0.0.1:14173",
    reuseExistingServer: false,
    timeout: 120000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
