import {test, expect} from '@playwright/test';
import {readFile, writeFile} from 'node:fs/promises';

test('stored 10k workspace URL, explicit actions, keyboard/mobile and real API timing with progress', async ({page}) => {
  test.setTimeout(120000);
  const errors:string[]=[]; page.on('pageerror',e=>errors.push(e.message));
  const token=JSON.parse(await readFile('test-results-t09/t09-setup.json','utf8')).token;
  await page.goto('/');
  await page.getByLabel('Operator setup token').fill(token);
  await page.getByLabel('Username',{exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password',{exact:true}).fill('synthetic-password-long');
  await page.getByRole('button',{name:'Create owner account'}).click();
  await expect(page.getByRole('heading',{name:'10,000 opportunities'})).toBeVisible();
  await expect(page.locator('[data-job]')).toHaveCount(25);
  const first=page.locator('[data-job]').first(); await first.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('.job-detail h2')).toBeFocused();
  const id=await first.getAttribute('data-job');
  await expect(page).toHaveURL(new RegExp(`selected=${id}`));
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
  await page.getByRole('button',{name:'Rejected',exact:true}).click();
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
  for (const width of [320, 390]) {
    await page.setViewportSize({width,height:844});
    await page.keyboard.press('Escape');
    await page.locator('[data-job]').first().click();
    await expect(page.locator('.job-detail h2')).toBeFocused();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
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
