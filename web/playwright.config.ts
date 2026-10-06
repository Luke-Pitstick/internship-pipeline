import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  testIgnore: 'master.spec.ts',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:4174', browserName: 'chromium', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: { command: '../.venv/bin/python tests/serve.py', url: 'http://127.0.0.1:4174', reuseExistingServer: false, stdout: 'ignore', stderr: 'ignore' }
});
