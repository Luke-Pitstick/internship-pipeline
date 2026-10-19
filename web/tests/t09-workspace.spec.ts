import {test, expect} from './workspace-fixture';
import {readFile, writeFile} from 'node:fs/promises';

test('stored 10k workspace URL, explicit actions, keyboard/mobile and real API timing with progress', async ({page}) => {
  test.setTimeout(120000);
  const errors:string[]=[]; page.on('pageerror',e=>errors.push(e.message));
  const token=JSON.parse(await readFile('test-results-t09/t09-setup.json','utf8')).token;
  await page.goto(`/#setup=${token}`);

  await page.getByLabel('Username',{exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password',{exact:true}).fill('synthetic-password-long');
  await page.getByRole('button',{name:'Create owner account'}).click();
  await expect(page.getByRole('heading',{name:'10,000 opportunities'})).toBeVisible();
  await expect(page.locator('[data-job]')).toHaveCount(25);
  const first=page.locator('[data-job]').first(); await first.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('.job-detail h2')).toBeFocused();
  const id=await first.getAttribute('data-job');
  await expect(page).toHaveURL(new RegExp(`selected=${id}`));
  await page.getByRole('tab', {name:'Notes',exact:true}).click();
  await page.getByLabel('Private job notes').fill('Synthetic owner note <script>alert(1)</script>');
  await page.getByRole('button',{name:'Save notes',exact:true}).click();
  await page.getByRole('button',{name:'Save job',exact:true}).click();
  await page.getByRole('button',{name:'Saved',exact:true}).click();
  await expect(page.locator('[data-job]')).toHaveCount(1);
  await page.reload(); await expect(page.getByLabel('Private job notes')).toHaveValue('Synthetic owner note <script>alert(1)</script>');
  await page.getByText('Record a decision override',{exact:true}).click();
  await page.getByLabel('Your decision').selectOption('rejected');
  await page.getByLabel('Reason',{exact:true}).fill('Owner reviewed synthetic requirement');
  await page.getByRole('button',{name:'Record override',exact:true}).click();
  await page.getByRole('button',{name:'Dismissed',exact:true}).click();
  await expect(page.locator('[data-job]')).toHaveCount(1);
  await expect(page.getByText('Current override: rejected.',{exact:false})).toBeVisible();
  await expect(page.getByRole('link',{name:'Open original application'})).toHaveAttribute('href',/https:\/\/example.test\/jobs\//);
  await expect(page.getByRole('button',{name:'Mark as applied',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Mark as applied',exact:true}).click();
  await page.getByRole('button',{name:'Applied',exact:true}).click();
  await expect(page.locator('[data-job]')).toHaveCount(1);
  await expect(page.getByRole('button',{name:'Undo applied',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'All jobs',exact:true}).click();
  await page.getByLabel('Sort field').selectOption('company');
  await page.getByLabel('Reverse sort direction').click();
  await expect(page).toHaveURL(/sort=company/); await expect(page).toHaveURL(/direction=asc/);
  await page.getByLabel('Page number',{exact:true}).fill('400');
  await page.getByRole('button',{name:'Go',exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Page 400 of 400'})).toBeVisible();
  await expect(page).toHaveURL(/page=400/); await page.reload();
  await expect(page.getByRole('status').filter({hasText:'Page 400 of 400'})).toBeVisible();
  // Wide glyphs reproduce the native Linux search-input minimum without depending on host fonts.
  await page.addStyleTag({content: '.search-field input {font-family:monospace}'});
  for (const width of [320, 390]) {
    await page.setViewportSize({width,height:844});
    await page.keyboard.press('Escape');
    await page.locator('[data-job]').first().click();
    await expect(page.locator('.job-detail h2')).toBeFocused();
    const overflow = await page.evaluate(() => [...document.querySelectorAll('body *')]
      .filter(element => {const box=element.getBoundingClientRect();return box.width>0&&(box.right>innerWidth+1||element.scrollWidth>element.clientWidth+1);})
      .map(element => ({tag:element.tagName,classes:element.className,text:element.textContent?.slice(0,80),right:element.getBoundingClientRect().right,scroll:element.scrollWidth,client:element.clientWidth})));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),JSON.stringify(overflow)).toBe(true);
    await page.keyboard.press('Escape'); await expect(page.locator('[data-job]').first()).toBeFocused();
    await page.screenshot({path:`test-results-t09/t09-mobile-${width}.png`,fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  const report=await page.evaluate(async()=>{
    const samples:Record<string,number[]>={}; const progress:number[]=[];
    for (const sort of ['postedAt','firstObservedAt','company','title','location','deadline','score']) {
      samples[sort]=[];
      for(let i=0;i<10;i++) {
        const start=performance.now();
        const [jobs,run]=await Promise.all([fetch(`/api/jobs?sort=${sort}&direction=${i%2?'asc':'desc'}&page=${i%2?400:1}`).then(r=>r.json()),fetch('/api/search-runs/current').then(r=>r.json())]);
        if(jobs.jobs.length!==25 || jobs.pagination.total!==10000) throw new Error('Invalid real page');
        samples[sort].push(performance.now()-start); progress.push(run.run.collected);
      }
    }
    return {samples,progress};
  });
  expect(Math.max(...report.progress)).toBeGreaterThan(Math.min(...report.progress));
  const summary=Object.fromEntries(Object.entries(report.samples).map(([sort,values])=>{const sorted=[...values].sort((a,b)=>a-b); return [sort,{median_ms:(sorted[4]+sorted[5])/2,p95_ms:sorted[9]}]}));
  await writeFile('test-results-t09/t09-real-api.json',JSON.stringify({...report,summary},null,2));
  expect(errors).toEqual([]);
});

test('filter recovery, retry, settings bookmarks and persistent run errors', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Username', {exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-password-long');
  await page.getByRole('button', {name:'Sign in', exact:true}).click();
  await expect(page.locator('[data-job]')).toHaveCount(25);
  await page.getByRole('searchbox').fill('no-such-synthetic-opportunity');
  await page.getByRole('button', {name:'Search jobs', exact:true}).click();
  await expect(page.getByRole('heading', {name:'No matching opportunities'})).toBeVisible();
  await page.getByRole('button', {name:'Clear filters'}).click();
  await expect(page.locator('[data-job]')).toHaveCount(25);
  await expect(page.getByRole('searchbox')).toHaveValue('');

  await page.route('**/api/jobs?*', route => route.fulfill({status:503,json:{detail:'Synthetic jobs connection failure'}}), {times:1});
  await page.getByRole('button', {name:'Search jobs', exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic jobs connection failure');
  await page.getByRole('button', {name:'Retry loading jobs'}).click();
  await expect(page.getByText('Synthetic jobs connection failure')).toHaveCount(0);
  await expect(page.locator('[data-job]')).toHaveCount(25);

  await page.getByText('Job discovery', {exact:true}).click();
  await page.getByRole('link', {name:'Manage sources'}).click();
  await expect(page.locator('.settings-panel-header h2')).toHaveText('Sources');
  await page.getByRole('button', {name:'AI Models',exact:true}).click();
  await expect(page).toHaveURL(/#AI%20Models$/);
  await page.reload();
  await expect(page.locator('.settings-panel-header h2')).toHaveText('AI Models');

  await page.goto('/');
  await page.getByText('Job discovery', {exact:true}).click();
  await page.getByText('Run details and history', {exact:true}).click();
  await page.route('**/api/search-runs/*/cancel', route => route.fulfill({status:409,json:{detail:'Synthetic cancellation failure'}}));
  await page.getByRole('button', {name:'Cancel remaining run work'}).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic cancellation failure');
  await page.waitForResponse(response => response.url().endsWith('/api/search-runs') && response.request().method()==='GET');
  await expect(page.getByRole('alert')).toContainText('Synthetic cancellation failure');
});

test('notes survive polling, failed actions stay visible, and changing jobs protects drafts', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Username', {exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-password-long');
  await page.getByRole('button', {name:'Sign in', exact:true}).click();
  await page.locator('[data-job]').nth(2).click();
  const id = await page.locator('[data-job][aria-pressed=true]').getAttribute('data-job');
  await page.getByRole('tab', {name:'Notes',exact:true}).click();
  await page.getByLabel('Private job notes').fill('Unsaved synthetic interview prep');
  await page.waitForResponse(r => r.url().includes('/api/jobs?') && r.request().method() === 'GET');
  await expect(page.getByLabel('Private job notes')).toHaveValue('Unsaved synthetic interview prep');
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('[data-job]').nth(3).click();
  await expect(page.getByLabel('Private job notes')).toHaveValue('Unsaved synthetic interview prep');
  await expect(page).toHaveURL(new RegExp(`selected=${id}`));
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('link',{name:'Settings',exact:true}).click();
  await expect(page.getByLabel('Private job notes')).toHaveValue('Unsaved synthetic interview prep');

  await page.route(`**/api/jobs/${id}/workspace`, route => route.fulfill({status:503,json:{detail:'Synthetic save unavailable'}}), {times:1});
  await page.getByRole('button', {name:'Save notes',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic save unavailable');
  await page.waitForResponse(r => r.url().includes('/api/jobs?') && r.request().method() === 'GET');
  await expect(page.getByRole('alert')).toContainText('Synthetic save unavailable');
  await expect(page.getByLabel('Private job notes')).toHaveValue('Unsaved synthetic interview prep');
  await page.getByRole('button', {name:'Save notes',exact:true}).click();
  await expect(page.getByText('Notes saved.', {exact:true})).toBeVisible();
  await expect(page.getByRole('button', {name:'Save notes',exact:true})).toBeDisabled();
  await page.reload();
  await expect(page.getByRole('tab', {name:'Notes',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.getByLabel('Private job notes')).toHaveValue('Unsaved synthetic interview prep');
  await page.getByLabel('Private job notes').fill('Discard this new draft');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('[data-job]').nth(3).click();
  await expect(page.getByRole('tab', {name:'Overview',exact:true})).toHaveAttribute('aria-selected','true');
  await page.getByRole('tab', {name:'Notes',exact:true}).click();
  await expect(page.getByLabel('Private job notes')).toHaveValue('');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('dismissed decisions can be restored and keyboard tabs preserve deep links', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Username', {exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-password-long');
  await page.getByRole('button', {name:'Sign in', exact:true}).click();
  await page.locator('[data-job]').nth(4).click();
  const id = await page.locator('[data-job][aria-pressed=true]').getAttribute('data-job');
  await page.getByRole('tab', {name:'Overview',exact:true}).focus();
  await page.keyboard.press('End');
  await expect(page.getByRole('tab', {name:'Notes',exact:true})).toBeFocused();
  await page.getByText('Record a decision override',{exact:true}).click();
  await page.getByLabel('Your decision').selectOption('rejected');
  await page.getByLabel('Reason',{exact:true}).fill('Synthetic owner decided to pass');
  await page.getByRole('button', {name:'Record override',exact:true}).click();
  await expect(page.getByRole('button',{name:'Restore dismissed job',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Dismissed',exact:true}).click();
  await expect(page.locator(`[data-job="${id}"]`)).toBeVisible();
  await page.getByRole('button',{name:'Restore dismissed job',exact:true}).click();
  await expect(page.locator(`[data-job="${id}"]`)).toHaveCount(0);
  await expect(page.getByText('Current override: None.',{exact:false})).toBeVisible();
  await page.getByRole('tab', {name:'Notes',exact:true}).focus();
  await page.keyboard.press('Home');
  await expect(page.getByRole('tab', {name:'Overview',exact:true})).toBeFocused();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', {name:'Match',exact:true})).toBeFocused();
  await expect(page).toHaveURL(/section=Match/);
  await page.reload();
  await expect(page.getByRole('tab', {name:'Match',exact:true})).toHaveAttribute('aria-selected','true');
});

test('mobile job focus, readable layouts, reduced motion and browser back work together', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Username', {exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-password-long');
  await page.getByRole('button', {name:'Sign in', exact:true}).click();
  await page.emulateMedia({reducedMotion:'reduce',colorScheme:'dark'});
  for (const size of [{width:375,height:812},{width:812,height:375},{width:768,height:1024}]) {
    await page.setViewportSize(size);
    await page.locator('[data-job]').nth(5).click();
    await expect(page.locator('.job-detail h2')).toBeFocused();
    if (size.width <= 760 || size.height <= 500) {
      await expect(page.getByRole('search')).toBeHidden();
      await expect(page.getByRole('navigation', {name:'Job views'})).toBeHidden();
      await expect(page.getByRole('button',{name:'Back to results',exact:true})).toBeInViewport();
    }
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole('tab', {name:'Notes',exact:true}).click();
    expect(await page.getByLabel('Private job notes').evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(size.width <= 760 || size.height <= 500 ? 16 : 14);
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-job]').nth(5)).toBeFocused();
    await page.screenshot({path:`test-results-t09/dashboard-${size.width}x${size.height}.png`});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-job]').nth(6).click();
  const firstId = await page.locator('[data-job][aria-pressed=true]').getAttribute('data-job');
  await page.locator('[data-job]').nth(7).click();
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`selected=${firstId}`));
  await expect(page.locator(`[data-job="${firstId}"]`)).toHaveAttribute('aria-pressed','true');
  await page.addStyleTag({content: '.dashboard {font-size:200%} .dashboard p,.dashboard button,.dashboard input,.dashboard select {font-size:inherit}'});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('mark applied directly from mobile results, recover from errors and undo after reload', async ({page}) => {
  await page.goto('/');
  await page.getByLabel('Username',{exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password',{exact:true}).fill('synthetic-password-long');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  const card = page.locator('.job-card').nth(8);
  const id = await card.locator('[data-job]').getAttribute('data-job');
  const mark = card.getByRole('button', {name:/^Mark as applied to /});
  await expect(page.getByRole('button',{name:'Applied',exact:true})).toBeVisible();
  await page.route(`**/api/jobs/${id}/applied`, route => route.fulfill({status:503,json:{detail:'Synthetic tracking unavailable'}}), {times:1});
  await mark.click();
  await expect(page.getByRole('alert')).toContainText('Synthetic tracking unavailable');
  await expect(mark).toBeEnabled();
  await mark.focus();
  await page.keyboard.press('Enter');
  await expect(card.getByRole('button',{name:/^Undo applied to /})).toBeVisible();
  await expect(page.locator('.job-detail')).toBeHidden();
  await expect(page).not.toHaveURL(/selected=/);
  await page.getByRole('button',{name:'Applied',exact:true}).click();
  await expect(page.locator(`[data-job="${id}"]`)).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button',{name:'Applied',exact:true})).toHaveAttribute('aria-pressed','true');
  const appliedCard = page.locator('.job-card').filter({has: page.locator(`[data-job="${id}"]`)});
  await appliedCard.getByRole('button',{name:/^Undo applied to /}).click();
  await expect(page.locator(`[data-job="${id}"]`)).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
