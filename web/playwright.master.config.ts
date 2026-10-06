import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', testMatch: 'master.spec.ts', workers: 1, reporter: 'list',
  outputDir: 'test-results-master',
  use: { baseURL: 'http://127.0.0.1:4175', browserName: 'chromium', channel: 'chromium', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: { command: '../.venv/bin/python tests/master-serve.py', url: 'http://127.0.0.1:4175', reuseExistingServer: false, stdout: 'ignore', stderr: 'ignore' }
});
