import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',testMatch:'search.spec.ts',workers:1,
  use:{baseURL:'http://127.0.0.1:4183',browserName:'chromium',viewport:{width:1440,height:1000}},
  webServer:{command:'../.venv/bin/python tests/search-serve.py',url:'http://127.0.0.1:4183',reuseExistingServer:false}});
