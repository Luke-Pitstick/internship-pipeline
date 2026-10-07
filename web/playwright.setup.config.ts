import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',testMatch:'setup.spec.ts',workers:1,outputDir:'test-results-setup',
  use:{baseURL:'http://127.0.0.1:4184',browserName:'chromium',viewport:{width:1440,height:1000}},
  webServer:{command:'../.venv/bin/python tests/setup-serve.py',url:'http://127.0.0.1:4184',reuseExistingServer:false}});
