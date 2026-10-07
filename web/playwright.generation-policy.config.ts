import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', testMatch: 'generation-policy.spec.ts', workers: 1, reporter: 'list',
  outputDir: 'test-results-generation-policy',
  use: { baseURL: 'http://127.0.0.1:4191', browserName: 'chromium', channel: 'chromium', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: { command: '../.venv/bin/python tests/generation-policy-serve.py', url: 'http://127.0.0.1:4191', reuseExistingServer: false, stdout: 'ignore', stderr: 'pipe' }
});
