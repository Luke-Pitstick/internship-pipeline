import {test, expect, type Page} from './workspace-fixture';
import {readFile} from 'node:fs/promises';
import type {SavedSource} from '../src/lib/source-settings';

async function login(page: Page) {
  await page.goto(`/settings/#setup=${JSON.parse(await readFile(process.env.PIPELINE_BROWSER_SETUP ?? 'test-results/setup.json', 'utf8')).token}`);
  await page.getByLabel('Username', {exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-owner-password');
  await page.getByRole('button', {name:/Create owner account|^Sign in$/}).click();
  await expect(page.getByLabel('Name', {exact:true})).toBeVisible();
}

test('large source libraries support grouping, paging, filtering and editing without expanding run panels', async ({page}) => {
  let sources: SavedSource[] = Array.from({length:27}, (_, index) => ({
    id:`source-${index}`, revision:1, name:`Company ${String(index).padStart(2, '0')}`,
    source:index < 23 ? 'greenhouse' : 'jobspy', board:`board-${index}`,
    search_term:index < 23 ? '' : 'Software internship', location:index % 2 ? 'Denver' : 'Toronto',
    country:'USA', sites:['indeed'], hours_old:72, results_wanted:100,
    daily_at:'09:00', timezone:'UTC', max_jobs:20, max_calls:30, max_tokens:5000000,
    paused:index % 3 === 0, next_run:2000000000 - index, last_success:1000000000 + index,
  }));
  const writes: {url:string; body:Record<string, unknown>}[] = [];
  let runRequests = 0;
  page.on('request', request => {if (request.url().includes('/api/search-runs?search_id=')) runRequests++;});
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await login(page);
  await page.route('**/api/search-settings**', async route => {
    const request = route.request();
    if (request.method() === 'POST') {
      const body = request.postDataJSON();
      writes.push({url:request.url(), body});
      if (request.url().endsWith('/pause')) {
        const id = request.url().split('/').at(-2);
        sources = sources.map(source => source.id === id ? {...source, paused:body.paused, revision:source.revision + 1} : source);
      } else if (request.url().endsWith('/delete')) {
        const id = request.url().split('/').at(-2);
        sources = sources.filter(source => source.id !== id);
      } else sources = sources.map(source => source.id === body.id ? {...source, ...body, revision:source.revision + 1} : source);
    }
    await route.fulfill({json:{searches:sources, sites:['indeed', 'linkedin'], countries:[{value:'USA', code:'US'}]}});
  });
  await page.getByRole('button', {name:'Sources', exact:true}).click();
  const library = page.getByRole('region', {name:'Saved sources', exact:true});
  const boards = library.getByRole('region', {name:'Greenhouse boards', exact:true});
  await expect(library.getByText('27 sources · 18 active · 9 paused')).toBeVisible();
  await expect(library.locator('.source-row')).toHaveCount(0);
  await expect(page.getByLabel('Search name', {exact:true})).toBeHidden();
  expect(runRequests).toBe(0);
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height:1000});
    await page.screenshot({path:`test-results-settings/source-library-collapsed-${width}.png`, fullPage:true});
  }
  await page.setViewportSize({width:1440, height:1000});
  await boards.getByRole('button', {name:'Greenhouse boards 23', exact:true}).focus();
  await page.keyboard.press('Enter');
  await expect(boards.locator('.source-row')).toHaveCount(10);
  expect(runRequests).toBe(0);
  await boards.getByRole('button', {name:'Next', exact:true}).click();
  await expect(boards.getByRole('region', {name:'Company 10', exact:true})).toBeVisible();
  await boards.getByRole('button', {name:'Next', exact:true}).click();
  await expect(boards.locator('.source-row')).toHaveCount(3);
  await expect(boards.getByRole('button', {name:'Next', exact:true})).toBeDisabled();

  await page.getByLabel('Find a source').fill('board-21 Denver');
  await expect(library.locator('.source-row')).toHaveCount(1);
  await page.getByLabel('Status', {exact:true}).selectOption('active');
  await expect(library.getByText(/No sources match/)).toBeVisible();
  await page.getByLabel('Status', {exact:true}).selectOption('paused');
  await page.getByRole('button', {name:'Resume Company 21', exact:true}).click();
  await expect(library.getByText(/No sources match/)).toBeVisible();
  expect(writes.at(-1)?.body).toEqual({expected_revision:1, paused:false});
  await page.getByLabel('Status', {exact:true}).selectOption('active');
  await page.getByRole('button', {name:'Edit Company 21', exact:true}).click();
  await expect(page.getByLabel('Search name', {exact:true})).toBeFocused();
  await page.getByLabel('Search name', {exact:true}).fill('Renamed company');
  await page.getByRole('button', {name:'Save search', exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Search saved.'})).toBeVisible();
  expect(writes.at(-1)?.body).toMatchObject({id:'source-21', name:'Renamed company', expected_revision:2});
  await page.getByRole('button', {name:'Details for Renamed company', exact:true}).click();
  await expect(boards.getByRole('button', {name:'Run now', exact:true})).toBeVisible();
  expect(runRequests).toBeGreaterThan(0);
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name:'Delete Renamed company', exact:true}).click();
  await expect(library.getByText(/No sources match/)).toBeVisible();
  expect(writes.at(-1)?.body).toEqual({expected_revision:3});

  await page.getByRole('button', {name:'Clear filters', exact:true}).click();
  await page.getByLabel('Sort sources').selectOption('success');
  await expect(boards.locator('.source-row h5').first()).toHaveText('Company 22');
  await page.getByLabel('Sort sources').selectOption('next');
  await expect(boards.locator('.source-row h5').first()).toHaveText('Company 22');
  await page.getByLabel('Find a source').fill('Software Toronto');
  await expect(library.locator('.source-row')).toHaveCount(2);
  await page.getByRole('button', {name:'Clear filters', exact:true}).click();
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({width, height:1000});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width !== 320) await page.screenshot({path:`test-results-settings/source-library-expanded-${width}.png`, fullPage:true});
  }
  await page.locator('.available-sources > summary').click();
  await page.getByRole('button', {name:'Add LinkedIn search', exact:true}).click();
  await expect(page.getByLabel('Search name', {exact:true})).toBeFocused();
  await expect(page.getByLabel('Source', {exact:true})).toHaveValue('jobspy');
  await expect(page.getByRole('button', {name:'Remove LinkedIn', exact:true})).toBeVisible();
  expect(errors).toEqual([]);
});

test('source load failures offer a retry and show the empty library after recovery', async ({page}) => {
  await login(page);
  let fail = true;
  await page.route('**/api/search-settings', route => route.fulfill(fail
    ? {status:503, json:{detail:'Source settings temporarily unavailable'}}
    : {json:{searches:[], sites:['indeed'], countries:[]}}));
  await page.getByRole('button', {name:'Sources', exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'Source settings temporarily unavailable'})).toBeVisible();
  fail = false;
  await page.getByRole('button', {name:'Retry loading sources'}).click();
  await expect(page.getByText('No saved sources yet. Add a job site search or company board below.')).toBeVisible();
});


test('automatic discovery status is visible and refreshing preserves a source draft', async ({page}) => {
  await login(page);
  await page.route('**/api/source-discovery', route => route.fulfill({json:{pending:11800,monitored:81,failed:3,unsupported:2,directory_checked_at:1792500000,directory_error:null,stopped:false}}));
  await page.getByRole('button', {name:'Sources',exact:true}).click();
  const discovery=page.getByRole('region',{name:'Automatic company discovery'});
  await expect(discovery.getByText(/81 boards validated/)).toBeVisible();
  await expect(discovery.getByText(/3 unavailable boards/)).toBeVisible();
  await page.locator('.available-sources > summary').click();
  await page.getByRole('button',{name:'Add Ashby company board'}).click();
  await page.getByLabel('Search name',{exact:true}).fill('Unsaved company');
  await discovery.getByRole('button',{name:'Refresh source list'}).click();
  await expect(page.getByLabel('Search name',{exact:true})).toHaveValue('Unsaved company');
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
});
