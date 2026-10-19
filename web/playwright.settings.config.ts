import {defineConfig} from '@playwright/test';
process.env.PIPELINE_BROWSER_SETUP = 'test-results-settings/setup.json';
export default defineConfig({
  testDir:'./tests', testMatch:['settings.spec.ts','profile.spec.ts','models.spec.ts','resume-import.spec.ts'], workers:1, reporter:'list', outputDir:'test-results-settings',
  use:{baseURL:'http://127.0.0.1:4195',browserName:'chromium',viewport:{width:1440,height:1000},trace:'retain-on-failure'},
  webServer:{command:'../.venv/bin/python tests/settings-serve.py',url:'http://127.0.0.1:4195',reuseExistingServer:false,stdout:'ignore',stderr:'pipe'}
});
