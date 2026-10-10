import {test,expect,type Page} from '@playwright/test';
import {readFile} from 'node:fs/promises';
const username='synthetic-security-owner', password='synthetic-security-password';
async function owner(page:Page) {
  await page.goto(`/settings/#setup=${JSON.parse(await readFile('test-results-web-security/setup.json','utf8')).token}`);
  await expect(page.getByRole('button',{name:'Notifications & Integrations',exact:true}).or(page.getByLabel('Username',{exact:true}))).toBeVisible();
  if(await page.getByRole('button', {name: 'Create owner account'}).isVisible()) {
    await page.getByLabel('Username',{exact:true}).fill(username);
    await page.getByLabel('Password',{exact:true}).fill(password);
    await page.getByRole('button',{name:'Create owner account'}).click();
  } else if(await page.getByRole('button',{name:'Sign in',exact:true}).isVisible()) {
    await page.getByLabel('Username',{exact:true}).fill(username);
    await page.getByLabel('Password',{exact:true}).fill(password);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
  }
  await page.getByRole('button',{name:'Notifications & Integrations',exact:true}).click();
  await expect(page.getByLabel('SMTP host')).toBeVisible();
}
test.beforeAll(async({browser})=>{
  const context=await browser.newContext({storageState:{cookies:[],origins:[]}});const page=await context.newPage();
  await owner(page);await context.storageState({path:'test-results-web-security/owner.json'});await context.close();
});
test.use({storageState:'test-results-web-security/owner.json'});
async function savedEmail(page:Page) {
  await page.getByLabel('SMTP host').fill('smtp.example.test');
  await page.getByLabel('Username',{exact:true}).fill('synthetic-user');
  await page.getByLabel('Password',{exact:true}).fill('synthetic-secret');
  await page.getByLabel('Sender email').fill('sender@example.test');
  await page.getByLabel('Recipient email').fill('recipient@example.test');
  await page.getByLabel('Enable automatic email delivery').check();
  await page.getByRole('button',{name:'Save email settings'}).click();
  await expect(page.getByText('Email settings saved.',{exact:true})).toBeVisible();
}
test('W1 email stale draft cannot reenable delivery after another browser disables it',async({page,browser})=>{
  await owner(page); await savedEmail(page);
  const contextB=await browser.newContext({storageState:{cookies:[],origins:[]}}); const tabB=await contextB.newPage(); await owner(tabB);
  await expect(tabB.getByLabel('Enable automatic email delivery')).toBeChecked();
  await page.getByLabel('Recipient email').fill('stale@example.test');
  await tabB.getByLabel('Enable automatic email delivery').uncheck();
  await tabB.getByLabel('Recipient email').fill('current@example.test');
  await tabB.getByRole('button',{name:'Save email settings'}).click();
  await expect(tabB.getByText('Email settings saved.',{exact:true})).toBeVisible();
  // Wait for A's actual status poll to read the new revision before saving its old fields.
  const poll=await page.waitForResponse(r=>r.url().endsWith('/api/email')&&r.request().method()==='GET');
  expect((await poll.json()).config.enabled).toBe(false);
  const response=page.waitForResponse(r=>r.url().endsWith('/api/email/save'));
  await page.getByRole('button',{name:'Save email settings'}).click();
  expect((await response).status()).toBe(409);
  const persisted=await(await page.request.get('/api/email')).json();
  expect(persisted.config.enabled).toBe(false); expect(persisted.config.recipient).toBe('current@example.test');
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Reload email settings'}).click();
  await expect(page.getByLabel('Enable automatic email delivery')).not.toBeChecked();
  await expect(page.getByLabel('Recipient email')).toHaveValue('current@example.test');
  await contextB.close();
});

test('W2 saved Sheets connection reopens with populated editable fields',async({page})=>{
  await owner(page);
  const fixture=JSON.parse(await readFile('test-results-web-security/setup.json','utf8'));
  await page.getByLabel('Spreadsheet ID',{exact:true}).fill('synthetic-sheet-id');
  await page.getByLabel('Google service-account JSON key').fill(fixture.service_account);
  await page.getByRole('button',{name:'Save Sheets connection'}).click();
  await expect(page.getByText('Sheets connection saved. Test current access before previewing.',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Test spreadsheet access'}).click();
  await expect(page.getByText('Selected spreadsheet: Synthetic Opportunities')).toBeVisible();
  await page.getByLabel('Destination tab').selectOption('Jobs');
  await page.getByRole('button',{name:'Save Sheets connection'}).click();
  await expect.poll(async()=> (await(await page.request.get('/api/sheets')).json()).config.tab).toBe('Jobs');
  await page.reload();
  await page.getByRole('button',{name:'Notifications & Integrations',exact:true}).click();
  await expect(page.getByLabel('Spreadsheet ID',{exact:true})).toHaveValue('synthetic-sheet-id');
  await expect(page.getByLabel('Destination tab')).toHaveValue('Jobs');
  await page.getByLabel('Inward notes column').selectOption('K');
  await page.getByRole('button',{name:'Save Sheets connection'}).click();
  await expect.poll(async()=> (await(await page.request.get('/api/sheets')).json()).config.inward_notes).toBe('K');
  await page.getByRole('button',{name:'Reload Sheets settings'}).click();
  await expect(page.getByLabel('Inward notes column')).toHaveValue('K');
});

test('W1 Sheets stale draft cannot overwrite another browser mapping',async({page,browser})=>{
  await owner(page);
  const fixture=JSON.parse(await readFile('test-results-web-security/setup.json','utf8'));
  await page.getByLabel('Spreadsheet ID',{exact:true}).fill('synthetic-sheet-id');
  await page.getByLabel('Google service-account JSON key').fill(fixture.service_account);
  await page.getByRole('button',{name:'Save Sheets connection'}).click();
  await expect(page.getByText('Sheets connection saved. Test current access before previewing.',{exact:true})).toBeVisible();
  const contextB=await browser.newContext({storageState:{cookies:[],origins:[]}}); const tabB=await contextB.newPage(); await owner(tabB);
  // Fill the saved ID explicitly so the independent W2 clone failure cannot mask W1.
  await tabB.getByLabel('Spreadsheet ID',{exact:true}).fill('synthetic-sheet-id');
  await tabB.getByLabel(/^company outward column/).selectOption('N');
  await tabB.getByRole('button',{name:'Save Sheets connection'}).click();
  await expect(tabB.getByText('Sheets connection saved. Test current access before previewing.',{exact:true})).toBeVisible();
  await page.getByLabel('Sync interval in minutes').fill('90');
  const poll=await page.waitForResponse(r=>r.url().endsWith('/api/sheets')&&r.request().method()==='GET');
  expect((await poll.json()).config.mapping.company).toBe('N');
  const response=page.waitForResponse(r=>r.url().endsWith('/api/sheets/save'));
  await page.getByRole('button',{name:'Save Sheets connection'}).click();
  expect((await response).status()).toBe(409);
  const persisted=await(await page.request.get('/api/sheets')).json();
  expect(persisted.config.mapping.company).toBe('N'); expect(persisted.config.interval_minutes).toBe(60);
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Reload Sheets settings'}).click();
  await expect(page.getByLabel(/^company outward column/)).toHaveValue('N');
  await contextB.close();
});

for(const [category,label,value] of [
  ['AI Models','#jev-model','jev-draft'],
  ['Sources','#source-name','Unsaved source'],
  ['Resume Generation','#generation-fit','83'],
  ['Notifications & Integrations','input[placeholder="smtp.example.com"]','draft.example.test'],
  ['Notifications & Integrations','input[placeholder="ID from the spreadsheet URL"]','draft-sheet-id'],
]) test(`W4 ${category} retains ordinary drafts and guards leaving Settings (${label})`,async({page})=>{
  await owner(page);
  await page.getByRole('button',{name:category,exact:true}).click();
  await page.locator(label).fill(value);
  expect(await page.evaluate(()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;})).toBe(true);
  await page.getByRole('button',{name:'Profile',exact:true}).click();
  await page.getByRole('button',{name:category,exact:true}).click();
  await expect(page.locator(label)).toHaveValue(value);
  page.once('dialog',dialog=>dialog.dismiss());
  await page.getByRole('link',{name:'Jobs',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Settings',exact:true})).toBeVisible();
  await expect(page.locator(label)).toHaveValue(value);
});
test('W6 malformed percent hash keeps Settings usable',async({page})=>{
  await owner(page);
  await page.goto('/settings/#%E0%A4%A');
  await expect(page.getByRole('heading',{name:'Settings',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Profile',exact:true})).toBeVisible();
  await expect(page.getByLabel('Name',{exact:true})).toBeVisible();
  await page.goto('/settings/#unknown');
  await expect(page.getByRole('heading',{name:'Profile',exact:true})).toBeVisible();
});

for(const [step,label,value] of [
 ['1. Models','#jev-model','jev-unsaved-setup'],
 ['2. Profile','#profile\\.name','Unsaved Setup Name'],
 ['3. Job filters','[id="preferences.hard.countries"]','Canada'],
 ['4. Saved search','#source-name','Unsaved Setup Source'],
 ['5. Optional integrations','input[placeholder="smtp.example.com"]','setup.example.test'],
 ['5. Optional integrations','input[placeholder="ID from the spreadsheet URL"]','setup-sheet-id'],
]) test(`W4 setup ${step} guards the edited step (${label})`,async({page})=>{
  await owner(page); await page.goto('/setup/');
  await page.getByRole('button',{name:new RegExp(step.replace('.','\\.'))}).click();
  await page.locator(label).fill(value);
  await expect(page.getByRole('button',{name:'Save progress and continue'})).toBeDisabled();
  page.once('dialog',d=>d.dismiss());
  await page.getByRole('button',{name:/6\. Configuration preview/}).click();
  await expect(page.locator(label)).toBeVisible();
  await expect(page.locator(label)).toHaveValue(value);
});
test('W5 bookmarked mobile selection opens detail and supports back/history/focus',async({page})=>{
  await owner(page);
  const id=JSON.parse(await readFile('test-results-web-security/setup.json','utf8')).job_id;
  await page.setViewportSize({width:390,height:844});
  await page.goto(`/?selected=${id}`);
  const detail=page.locator('.job-detail');
  await expect(detail).toBeVisible();
  await expect(detail.getByRole('heading',{name:'Synthetic Internship',exact:true})).toBeFocused();
  await page.getByRole('button',{name:/Back to results/}).click();
  await expect(detail).not.toBeVisible();
  await expect(page.locator(`[data-job="${id}"]`)).toBeFocused();
  expect(new URL(page.url()).searchParams.has('selected')).toBe(false);
  await page.locator(`[data-job="${id}"]`).press('Enter');
  await expect(detail).toBeVisible();
  await page.goBack();
  await expect(detail).not.toBeVisible();
  await page.goForward();
  await expect(detail).toBeVisible();
  await expect(detail.getByRole('heading',{name:'Synthetic Internship',exact:true})).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator(`[data-job="${id}"]`)).toBeFocused();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('W4 secrets stay in memory, clear on saves and explicit discard, and do not reach browser storage',async({page})=>{
  await owner(page);
  const secret='synthetic-web-security-secret';
  await page.getByLabel('Password',{exact:true}).fill(secret);
  await page.getByLabel('Google service-account JSON key').fill(secret);
  await page.getByRole('button',{name:'AI Models',exact:true}).click();
  await page.locator('#jev-key').fill(secret);
  await page.getByRole('button',{name:'Profile',exact:true}).click();
  await page.getByRole('button',{name:'AI Models',exact:true}).click();
  await expect(page.locator('#jev-key')).toHaveValue(secret);
  expect(await page.evaluate(value=>!JSON.stringify({...localStorage,...sessionStorage}).includes(value),secret)).toBe(true);
  await page.getByRole('button',{name:'Discard Jev changes'}).click();
  await expect(page.locator('#jev-key')).toHaveValue('');
  await page.locator('#jev-key').fill(secret);
  await page.getByRole('button',{name:'Save Jev',exact:true}).click();
  await expect(page.locator('#jev-key')).toHaveValue('');
  await page.getByRole('button',{name:'Notifications & Integrations',exact:true}).click();
  await expect(page.getByLabel('Password',{exact:true})).toHaveValue(secret);
  page.once('dialog',d=>d.dismiss());
  await page.getByRole('button',{name:'Reload email settings'}).click();
  await expect(page.getByLabel('Password',{exact:true})).toHaveValue(secret);
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Reload email settings'}).click();
  await expect(page.getByLabel('Password',{exact:true})).toHaveValue('');
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Reload Sheets settings'}).click();
  await expect(page.getByLabel('Google service-account JSON key')).toHaveValue('');
  await page.getByRole('link',{name:'Jobs',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Find your next chapter.',exact:true})).toBeVisible();
});
for(const choice of ['models','integrations']) test(`W4 setup ${choice} choices require explicit discard before leaving`,async({page})=>{
  await owner(page);await page.goto('/setup/');
  await page.getByRole('button',{name:choice==='models'?/1\. Models/:/5\. Optional integrations/}).click();
  const control=choice==='models'?page.getByLabel('Defer model work and collect jobs first'):page.getByLabel('Email during setup');
  if(choice==='models')await control.setChecked(!(await control.isChecked()));else await control.selectOption('connect');
  page.once('dialog',d=>d.dismiss());
  await page.getByRole('button',{name:/6\. Configuration preview/}).click();
  await expect(control).toBeVisible();
  expect(await page.evaluate(()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;})).toBe(true);
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:/6\. Configuration preview/}).click();
  await expect(page.getByRole('heading',{name:'Review before your first run'})).toBeVisible();
});
test('W4 selected résumé file is guarded before extraction',async({page})=>{
  await owner(page);await page.getByRole('button',{name:'Profile',exact:true}).click();
  await page.getByLabel('Resume document').setInputFiles({name:'synthetic.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.4 synthetic test only')});
  page.once('dialog',d=>d.dismiss());
  await page.getByRole('button',{name:'Sources',exact:true}).click();
  await expect(page.getByLabel('Resume document')).toBeVisible();
  expect(await page.getByLabel('Resume document').evaluate((element:HTMLInputElement)=>element.files?.[0]?.name)).toBe('synthetic.pdf');
});

test('W7 generation preview cannot advance a stale policy draft revision',async({page,browser})=>{
  await owner(page);await page.getByRole('button',{name:'Resume Generation',exact:true}).click();
  await page.getByLabel('Automatically generate qualifying drafts').check();
  await page.getByRole('button',{name:'Save generation rules'}).click();
  await expect(page.getByText('Generation rules saved. Manual generation remains available.')).toBeVisible();
  const contextB=await browser.newContext({storageState:{cookies:[],origins:[]}});const tabB=await contextB.newPage();
  await owner(tabB);await tabB.getByRole('button',{name:'Resume Generation',exact:true}).click();
  await expect(tabB.getByLabel('Automatically generate qualifying drafts')).toBeChecked();
  await tabB.getByLabel('Automatically generate qualifying drafts').uncheck();
  await tabB.getByLabel('Minimum fit',{exact:true}).fill('92');
  await tabB.getByRole('button',{name:'Save generation rules'}).click();
  await expect(tabB.getByText('Generation rules saved. Manual generation remains available.')).toBeVisible();
  await page.getByRole('button',{name:'Preview qualifying jobs'}).click();
  await expect(page.getByText('Preview updated for the rules shown below.')).toBeVisible();
  const response=page.waitForResponse(r=>r.url().endsWith('/api/generation-policy')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Save generation rules'}).click();
  expect((await response).status()).toBe(409);
  const persisted=await(await page.request.get('/api/generation-policy')).json();
  expect(persisted.policy.enabled).toBe(false);expect(persisted.policy.minimum_fit).toBe(92);
  await page.getByRole('button',{name:'Reload rules'}).click();
  await expect(page.getByLabel('Automatically generate qualifying drafts')).not.toBeChecked();
  await expect(page.getByLabel('Minimum fit',{exact:true})).toHaveValue('92');
  await contextB.close();
});

test('W8 delayed model capability result cannot advance an older editor revision',async({page,browser})=>{
  await owner(page);await page.getByRole('button',{name:'AI Models',exact:true}).click();
  await page.locator('#jev-model').fill('jev-1.13.0');
  await page.locator('#jev-key').fill('synthetic-held-capability-key');
  await page.getByRole('button',{name:'Save Jev',exact:true}).click();
  await expect(page.getByText('Jev saved. Test this revision to verify its capabilities.')).toBeVisible();
  const contextB=await browser.newContext({storageState:{cookies:[],origins:[]}});const tabB=await contextB.newPage();
  await owner(tabB);await tabB.getByRole('button',{name:'AI Models',exact:true}).click();
  const testRequest=page.waitForRequest(r=>r.url().endsWith('/api/model-connections/jev/test'));
  await page.getByRole('button',{name:'Test Jev',exact:true}).click();await testRequest;
  await tabB.locator('#jev-model').fill('jev-new-owner-choice');
  await tabB.getByRole('button',{name:'Save Jev',exact:true}).click();
  await expect(tabB.getByText('Jev saved. Test this revision to verify its capabilities.')).toBeVisible();
  await expect(page.getByText('Synthetic capability test passed.')).toBeVisible();
  const response=page.waitForResponse(r=>r.url().endsWith('/api/model-connections/jev/save'));
  await page.getByRole('button',{name:'Save Jev',exact:true}).click();
  expect((await response).status()).toBe(409);
  const persisted=await(await page.request.get('/api/model-connections')).json();
  expect(persisted.jev.config.model).toBe('jev-new-owner-choice');
  await page.getByRole('button',{name:'Reload model connections'}).click();
  await expect(page.locator('#jev-model')).toHaveValue('jev-new-owner-choice');
  await contextB.close();
});

test('W9 email reload cannot replace a draft while its save is in flight',async({page})=>{
  await owner(page);await savedEmail(page);
  let release!:()=>void;const held=new Promise<void>(resolve=>release=resolve);
  let admitted!:()=>void;const started=new Promise<void>(resolve=>admitted=resolve);
  await page.route('**/api/email/save',async route=>{admitted();await held;await route.continue();});
  await page.getByLabel('Recipient email').fill('inflight@example.test');
  await page.getByRole('button',{name:'Save email settings'}).click();await started;
  try {await expect(page.getByRole('button',{name:'Reload email settings'})).toBeDisabled();}
  finally {release();}
  await expect.poll(async()=> (await(await page.request.get('/api/email')).json()).config.recipient).toBe('inflight@example.test');
  await expect(page.getByLabel('Recipient email')).toHaveValue('inflight@example.test');
});

test('W10 failed setup step navigation preserves dirty state and its draft',async({page})=>{
  await owner(page);await page.goto('/setup/');
  await page.getByRole('button',{name:/4\. Saved search/}).click();
  await page.getByLabel('Search name').fill('Draft kept after failed visit');
  await expect(page.getByRole('button',{name:'Save progress and continue'})).toBeDisabled();
  await page.route('**/api/onboarding/visit',route=>route.fulfill({status:409,json:{detail:'Synthetic visit rejected'}}));
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:/6\. Configuration preview/}).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic visit rejected');
  await expect(page.getByLabel('Search name')).toHaveValue('Draft kept after failed visit');
  await expect(page.getByRole('button',{name:'Save progress and continue'})).toBeDisabled();
});
test('W3 real cookie-free concurrent HTTP callers cannot evade admission with forwarded headers',async({page,playwright})=>{
  const statuses=await Promise.all(Array.from({length:28},async(_,index)=>{
    const caller=await playwright.request.newContext({baseURL:'http://127.0.0.1:4187',storageState:{cookies:[],origins:[]}});
    try {const response=await caller.get('/api/session',{headers:{'X-Forwarded-For':`192.0.2.${index}`}});if(response.status()===429)expect(response.headers()['retry-after']).toBe('300');return response.status();}
    finally {await caller.dispose();}
  }));
  expect(statuses.filter(status=>status===200).length).toBeLessThanOrEqual(20);
  expect(statuses.filter(status=>status===429).length).toBeGreaterThanOrEqual(8);
  expect(statuses.every(status=>status===200||status===429)).toBe(true);
  expect((await(await page.request.get('/api/session')).json()).authenticated).toBe(true);
});
