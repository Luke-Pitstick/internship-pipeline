import {test, expect, type Page} from '@playwright/test';
import {readFile} from 'node:fs/promises';

async function checkLayout(page:Page,step:string) {
  for(const viewport of [{width:1440,height:1000},{width:375,height:812},{width:812,height:375}]) {
    await page.setViewportSize(viewport);
    await page.evaluate(()=>window.scrollTo(0,0));
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${step} fits ${viewport.width}px`).toBe(true);
    for(const field of await page.locator('label.form-field:visible').all()) {
      await expect(field).toHaveCSS('display','block');
      await expect(field).toHaveCSS('border-top-width','0px');
    }
    if(viewport.width===375) {
      for(const input of await page.locator('input:not([type=checkbox]):not([readonly]):visible, select:visible, textarea:visible').all()) {
        await expect(input).toHaveCSS('font-size','16px');
      }
    }
    await page.screenshot({path:`test-results-setup/${step}-${viewport.width}.png`,fullPage:step==='integrations'});
  }
  await page.setViewportSize({width:1440,height:1000});
}

test('setup generates searches from preferences and opens Jobs with navigation only after completion',async({page})=>{
  test.setTimeout(90000);
  const pageErrors:string[]=[];
  page.on('pageerror',error=>pageErrors.push(error.message));
  await page.route('**/api/model-connections/general/models', route =>
    route.fulfill({json:{models:[{id:'test-model',name:'Test model'}]}}));
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto(`/#setup=${JSON.parse(await readFile('test-results-setup/setup.json','utf8')).token}`);

  await expect(page.getByRole('navigation',{name:'Main navigation'})).toHaveCount(0);
  await checkLayout(page,'account');
  await page.getByLabel('Username',{exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password',{exact:true}).fill('synthetic-owner-password');
  await page.getByRole('button',{name:'Create owner account'}).click();
  await expect(page).toHaveURL(/\/setup\//);
  await checkLayout(page,'models');
  const jev = page.locator('form').filter({has:page.getByRole('heading',{name:'Jev',exact:true})});
  await jev.getByLabel(/^API key/).fill('synthetic-invalid');
  await jev.getByRole('button',{name:'Save Jev',exact:true}).click();
  await jev.getByRole('button',{name:'Test Jev',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:/credential|authentication|rejected/i})).toBeVisible();
  await page.getByLabel('Defer model work and collect jobs first').check();
  await expect(jev).toHaveCount(0);
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Profile & résumé',exact:true})).toBeFocused();
  // Validation stays on this step and puts keyboard focus on the invalid field.
  await page.getByLabel('Email',{exact:true}).fill('invalid-address');
  await page.getByLabel('Email',{exact:true}).press('Enter');
  await expect(page.getByLabel('Email',{exact:true})).toBeFocused();
  await expect(page.getByLabel('Email',{exact:true})).toHaveAttribute('aria-invalid','true');
  await page.getByRole('button',{name:'Discard changes',exact:true}).click();
  // Résumé import and personal details are optional; unknowns can be saved.
  await page.getByRole('button',{name:'Save and continue',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Job filters',exact:true})).toBeFocused();
  await page.getByRole('button',{name:'Back',exact:true}).click();
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.docx');
  await expect(page.getByRole('button',{name:'Save and continue',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Fill profile from resume'}).click();
  await expect(page.getByLabel('Name',{exact:true})).toHaveValue('Synthetic Candidate');
  page.once('dialog',dialog=>dialog.dismiss());
  await page.getByRole('button',{name:'Back',exact:true}).click();
  await expect(page.getByLabel('Name',{exact:true})).toHaveValue('Synthetic Candidate');
  await checkLayout(page,'profile');
  await page.getByRole('button',{name:'Save and continue',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Job filters',exact:true})).toBeFocused();
  await page.getByRole('button',{name:'Back',exact:true}).click();
  await expect(page.getByLabel('Name',{exact:true})).toHaveValue('Synthetic Candidate');
  await page.reload();
  await expect(page.getByLabel('Name',{exact:true})).toHaveValue('Synthetic Candidate');
  await page.getByRole('button',{name:'Save and continue',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Job filters',exact:true})).toBeVisible();
  await page.getByLabel('Required countries').fill('Canada');
  await page.getByLabel('Required countries').press('ArrowDown');
  await page.getByLabel('Required countries').press('Enter');
  await checkLayout(page,'filters');
  // A failed save preserves the draft and leaves the current step in place.
  await page.route('**/api/profile-settings',async route=>{
    if(route.request().method()==='POST')await route.fulfill({status:503,json:{detail:'Temporary save failure. Try again.'}});
    else await route.continue();
  });
  await page.getByRole('button',{name:'Save and continue',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'Temporary save failure'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Job filters',exact:true})).toBeVisible();
  await page.unroute('**/api/profile-settings');
  await page.getByRole('button',{name:'Save and continue',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Optional integrations',exact:true})).toBeVisible();
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:/Saved search/})).toHaveCount(0);
  await expect(page.getByLabel('SMTP host')).toHaveCount(0);
  await expect(page.getByLabel('Spreadsheet ID')).toHaveCount(0);
  await checkLayout(page,'integrations-skipped');
  await page.getByLabel('Email during setup').selectOption('connect');
  await page.getByLabel('Sheets during setup').selectOption('connect');
  await expect(page.getByLabel('Spreadsheet ID')).toBeVisible();
  await expect(page.getByLabel('job id outward column')).toBeHidden();
  await expect(page.getByLabel('Delivery mode')).toBeHidden();
  await checkLayout(page,'integrations');
  await page.getByText('Column mapping and sync options',{exact:true}).click();
  await expect(page.getByLabel('job id outward column')).toBeVisible();
  await checkLayout(page,'integrations-advanced');
  await page.getByLabel('Spreadsheet ID').fill('unsaved-spreadsheet');
  page.once('dialog',dialog=>dialog.dismiss());
  await page.getByLabel('Sheets during setup').selectOption('skip');
  await expect(page.getByLabel('Sheets during setup')).toHaveValue('connect');
  await expect(page.getByLabel('Spreadsheet ID')).toHaveValue('unsaved-spreadsheet');
  page.once('dialog',dialog=>dialog.accept());
  await page.getByLabel('Sheets during setup').selectOption('skip');
  await expect(page.getByLabel('Spreadsheet ID')).toHaveCount(0);
  await page.getByLabel('SMTP host').fill('smtp.example.test');
  await page.getByLabel('Username',{exact:true}).fill('synthetic');
  await page.getByLabel('Password',{exact:true}).fill('synthetic-smtp-secret');
  await page.getByLabel('Sender email').fill('from@example.test');
  await page.getByLabel('Recipient email').fill('to@example.test');
  await page.getByRole('button',{name:'Save email settings'}).click();
  await page.getByRole('button',{name:'Send test email'}).click();
  await expect(page.getByText(/failed.*credential_unavailable|failed/i).first()).toBeVisible({timeout:12000});
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.getByRole('button',{name:'Finish setup and find jobs'})).toBeDisabled();
  await page.getByRole('button',{name:'Edit integrations',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Optional integrations',exact:true})).toBeFocused();
  await page.getByLabel('Email during setup').selectOption('skip');
  await page.getByLabel('Sheets during setup').selectOption('skip');
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.getByText(/Email: Skipped/)).toBeVisible();
  await page.getByRole('button',{name:'Edit model connections',exact:true}).click();
  await page.getByLabel('Defer model work and collect jobs first').uncheck();
  await jev.getByLabel(/^API key/).fill('synthetic-valid');
  await jev.getByRole('button',{name:'Save Jev',exact:true}).click();
  await jev.getByRole('button',{name:'Test Jev',exact:true}).click();
  await expect(jev.getByText('Capability test passed',{exact:true})).toBeVisible();
  const general=page.locator('form').filter({has:page.getByRole('heading',{name:'General LLM',exact:true})});
  await general.getByLabel(/^API key/).fill('synthetic-general-valid');
  await general.getByLabel('Model',{exact:true}).fill('test-model');
  await general.getByLabel('Model',{exact:true}).press('ArrowDown');
  await general.getByLabel('Model',{exact:true}).press('Enter');
  await general.getByRole('button',{name:'Save General LLM',exact:true}).click();
  await general.getByRole('button',{name:'Test General LLM',exact:true}).click();
  await expect(general.getByText('Capability test passed',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await page.getByRole('button',{name:'5. Configuration preview',exact:false}).click();
  await expect(page.getByText('internship · All locations · canada · indeed.',{exact:true})).toBeVisible();
  await checkLayout(page,'review');
  // Simulate a preference correction from a second tab while this preview is open.
  const session = await (await page.request.get('/api/session')).json();
  const snapshot = await (await page.request.get('/api/profile-settings')).json();
  snapshot.preferences.soft.roles = ['Software engineering'];
  const saved = await page.request.post('/api/profile-settings', {
    headers:{'X-CSRF-Token':session.csrf,'Origin':'http://127.0.0.1:4184'},
    data:{expected_revision:snapshot.revision,profile:snapshot.profile,preferences:snapshot.preferences},
  });
  expect(saved.ok()).toBe(true);
  await page.getByRole('button',{name:'Finish setup and find jobs'}).click();
  await expect(page.getByRole('alert')).toContainText('Settings changed');
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toHaveCount(0);
  await page.getByRole('button',{name:'Refresh configuration preview'}).click();
  await expect(page.getByText('Software engineering internship · All locations · canada · indeed.',{exact:true})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'test-results-setup/setup-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'Finish setup and find jobs'}).click();
  await expect(page).toHaveURL(/\/(?:\?.*)?$/);
  await expect(page.getByRole('navigation',{name:'Main navigation'})).toBeVisible();
  await expect(page.getByRole('link',{name:'Continue setup'})).toHaveCount(0);
  await expect(page.getByText('Synthetic Python internship',{exact:true}).first()).toBeVisible({timeout:15000});
  await page.getByRole('link',{name:'Settings',exact:true}).click();
  await page.getByRole('link',{name:'Jobs',exact:true}).click();
  await expect(page).toHaveURL(/\/(?:\?.*)?$/);
  await page.goto('/setup/');
  await expect(page).toHaveURL(/\/(?:\?.*)?$/);
  await page.reload();
  await expect(page).toHaveURL(/\/(?:\?.*)?$/);
  const state=await (await page.request.get('/api/onboarding')).json();
  expect(state.complete).toBe(true);expect(state.email).toBe('skip');expect(state.sheets).toBe('skip');
  const jobs=await (await page.request.get('/api/jobs')).json();
  expect(JSON.stringify(jobs)).not.toContain('synthetic-smtp-secret');
  expect(pageErrors).toEqual([]);
});
