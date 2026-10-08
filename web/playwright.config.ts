import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  testIgnore: ['web-security.spec.ts', 'master.spec.ts', 'tailored.spec.ts', 'search.spec.ts', 't09-workspace.spec.ts', 'email.spec.ts', 'sheets.spec.ts', 'generation-policy.spec.ts', 'setup.spec.ts'],
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:4174', browserName: 'chromium', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: { command: '../.venv/bin/python tests/serve.py', url: 'http://127.0.0.1:4174', reuseExistingServer: false, stdout: 'ignore', stderr: 'ignore' }
});
