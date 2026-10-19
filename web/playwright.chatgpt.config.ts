import { defineConfig } from '@playwright/test';

// Keep this feature's server and artifacts independent of other workspace QA runs.
export default defineConfig({
  testDir: './tests',
  testMatch: 'chatgpt.spec.ts',
  outputDir: './test-results-chatgpt/artifacts',
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4187', browserName: 'chromium',
    viewport: {width: 1440, height: 1000}, trace: 'retain-on-failure'
  },
  webServer: {
    command: '../.venv/bin/python tests/serve_chatgpt.py',
    url: 'http://127.0.0.1:4187', reuseExistingServer: false,
    stdout: 'ignore', stderr: 'pipe'
  }
});
