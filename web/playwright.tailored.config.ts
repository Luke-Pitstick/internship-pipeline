import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', testMatch: 'tailored.spec.ts', workers: 1, reporter: 'list',
  outputDir: 'test-results-tailored',
  use: { baseURL: 'http://127.0.0.1:4177', browserName: 'chromium', channel: 'chromium', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: { command: '../.venv/bin/python tests/tailored-serve.py', url: 'http://127.0.0.1:4177', reuseExistingServer: false, stdout: 'ignore', stderr: 'ignore' }
});
