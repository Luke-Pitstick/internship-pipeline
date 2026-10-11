import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function login(page: Page) {
  await page.goto(`/settings/#setup=${JSON.parse(await readFile('test-results/setup.json', 'utf8')).token}`);
  await expect(page.getByLabel('Username', {exact: true})).toBeVisible();
  await page.getByLabel('Username', {exact: true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact: true}).fill('synthetic-owner-password');
  await page.getByRole('button', {name: /Create owner account|^Sign in$/}).click();
  await expect(page.getByLabel('Name', {exact: true})).toBeVisible();
}

test('resume import fills the existing editable profile fields before saving', async ({page}) => {
  await login(page);
  const session = await (await page.request.get('/api/session')).json();
  const current = await (await page.request.get('/api/profile-settings')).json();
  const reset = await page.request.post('/api/profile-settings', {headers: {'X-CSRF-Token': session.csrf}, data: {
    expected_revision: current.revision, profile: {}, preferences: {}
  }});
  expect(reset.ok()).toBe(true);
  const before = await reset.json();
  await page.reload();
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.docx');
  await page.getByRole('button', {name: 'Fill profile from resume'}).click();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Synthetic Candidate');
  await expect(page.getByLabel('Name', {exact: true})).toBeEnabled();
  await expect(page.getByLabel('Email', {exact: true})).toHaveValue('synthetic@example.test');
  await expect(page.getByLabel('Institution', {exact: true})).toHaveValue('Example University');
  await expect(page.getByLabel('Degree', {exact: true})).toHaveValue('Bachelor of Science in Computing');
  await expect(page.getByRole('group', {name: 'Review extracted facts'})).toHaveCount(0);
  expect((await (await page.request.get('/api/profile-settings')).json()).revision).toBe(before.revision);
  await page.getByLabel('Name', {exact: true}).fill('Reviewed Synthetic Candidate');
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: /Saved · revision/})).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Reviewed Synthetic Candidate');
  const history = await (await page.request.get('/api/resume-imports/current')).json();
  expect(history.import.evidence.some((item: {field: string}) => item.field === 'email')).toBe(true);
  expect(history.import.evidence.some((item: {field: string}) => item.field === 'name')).toBe(false);
});

test('resume autofill preserves saved facts, supports replacement and discard, and rejects stale saves', async ({page}) => {
  await login(page);
  const session = await (await page.request.get('/api/session')).json();
  let saved = await (await page.request.get('/api/profile-settings')).json();
  const manual = {id: 'manual-browser-fact', kind: 'project', status: 'confirmed', text: 'A manually confirmed synthetic project.', skills: []};
  const reset = await page.request.post('/api/profile-settings', {headers: {'X-CSRF-Token': session.csrf}, data: {
    expected_revision: saved.revision, profile: {name: '', facts: [manual]}, preferences: {soft: {skills: ['Rust']}}
  }});
  expect(reset.ok()).toBe(true);
  await page.reload();
  await page.getByLabel('Resume document').setInputFiles({name: 'bad.pdf', mimeType: 'application/pdf', buffer: Buffer.from('unreadable-synthetic')});
  await expect(page.getByLabel('Name', {exact: true})).toBeEnabled();
  await expect(page.getByRole('button', {name: 'Add education', exact: true})).toBeEnabled();
  await page.getByRole('button', {name: 'Fill profile from resume'}).click();
  await expect(page.getByRole('alert').filter({hasText: 'not a PDF'})).toBeVisible();
  await page.getByLabel('Available from', {exact: true}).fill('2027-06-01');
  await expect(page.getByLabel('Available from', {exact: true})).toHaveValue('2027-06-01');
  await page.getByRole('button', {name: 'Discard changes'}).click();

  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.docx');
  await page.getByRole('button', {name: 'Fill profile from resume'}).click();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Synthetic Candidate');
  await expect(page.getByLabel('Supporting fact', {exact: true})).toHaveCount(4);
  const skillField = page.locator('.choice-field').filter({has: page.getByLabel('Related skills', {exact:true})}).nth(1);
  await expect(skillField.getByRole('button', {name:'Remove Python', exact:true})).toBeVisible();
  await expect(skillField.getByRole('button', {name:'Remove SQL', exact:true})).toBeVisible();
  await expect(page.getByLabel('Will you need employer sponsorship?')).toHaveValue('unknown');
  await page.getByLabel('Available from', {exact: true}).fill('2027-06-01');
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: /Saved · revision/})).toBeVisible();
  saved = await (await page.request.get('/api/profile-settings')).json();
  expect(saved.profile.facts.some((item: {id: string}) => item.id === manual.id)).toBe(true);
  expect(saved.preferences.soft.skills).toEqual(['Rust']);
  expect(saved.profile.available_from).toBe('2027-06-01');
  expect(saved.profile.requires_sponsorship).toBeNull();
  const stableIds = saved.profile.facts.map((item: {id: string}) => item.id);
  await page.reload();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Synthetic Candidate');
  await expect(page.getByText(`Last reviewed DOCX · profile revision ${saved.revision}`, {exact: true})).toBeVisible();
  expect((await (await page.request.get('/api/profile-settings')).json()).profile.facts.map((item: {id: string}) => item.id)).toEqual(stableIds);

  await page.getByLabel('Name', {exact: true}).fill('Unsaved edit');
  await expect(page.getByLabel('Resume document')).toBeDisabled();
  await page.getByRole('button', {name: 'Discard changes'}).click();
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/replacement.synthetic.docx');
  await page.getByRole('button', {name: 'Fill profile from resume'}).click();
  await expect(page.getByRole('status').filter({hasText: 'Profile fields filled.'})).toBeVisible();
  // Remove an outdated imported claim through the same ordinary profile editor.
  const outdated = page.locator('fieldset.fact-entry').filter({has: page.getByLabel('Supporting fact', {exact: true})}).nth(1);
  await expect(outdated.getByLabel('Supporting fact', {exact: true})).toHaveValue('Python, SQL');
  await outdated.getByRole('button', {name: /Remove fact/}).click();
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: /Saved · revision/})).toBeVisible();
  saved = await (await page.request.get('/api/profile-settings')).json();
  expect(saved.profile.facts.find((item: {id: string}) => item.id === manual.id)).toEqual(manual);
  expect(saved.profile.facts.some((item: {text: string}) => item.text === 'Python, SQL')).toBe(false);
  expect(saved.profile.facts.some((item: {text: string}) => item.text === 'Python, Go')).toBe(true);

  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.pdf');
  await page.getByRole('button', {name: 'Fill profile from resume'}).click();
  await expect(page.getByRole('status').filter({hasText: 'Profile fields filled.'})).toBeVisible();
  const competing = await page.request.post('/api/profile-settings', {headers: {'X-CSRF-Token': session.csrf}, data: {
    expected_revision: saved.revision, profile: {...saved.profile, name: 'Concurrent synthetic name'}, preferences: saved.preferences
  }});
  expect(competing.ok()).toBe(true);
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(page.getByRole('alert').filter({hasText: 'Settings changed'})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Save changes', exact: true})).toBeDisabled();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name: 'Reload saved settings'}).click();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Concurrent synthetic name');

  await page.setViewportSize({width: 390, height: 844});
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.pdf');
  await page.getByRole('button', {name: 'Fill profile from resume'}).click();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Synthetic Candidate');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results/t10-resume-import-mobile.png', fullPage: true});
  await page.getByRole('button', {name: 'Discard changes'}).click();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Concurrent synthetic name');
  await expect(page.getByLabel('Resume document')).toBeEnabled();
});

test('edits and discard during extraction cannot be overwritten by a late autofill', async ({page}) => {
  await login(page);
  const savedName = await page.getByLabel('Name', {exact: true}).inputValue();
  let release!: () => void;
  let started!: () => void;
  let pending = new Promise<void>(resolve => { release = resolve; });
  let intercepted = new Promise<void>(resolve => { started = resolve; });
  await page.route('**/api/resume-imports/*/preview', async route => {
    started();
    await pending;
    await route.continue();
  });
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.docx');
  await page.getByRole('button', {name: 'Fill profile from resume'}).click();
  await intercepted;
  await page.getByLabel('Name', {exact: true}).fill('Manual edit during extraction');
  release();
  await expect(page.getByRole('alert').filter({hasText: 'Your profile changed during extraction'})).toBeVisible();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Manual edit during extraction');
  await page.getByRole('button', {name: 'Discard changes'}).click();

  pending = new Promise<void>(resolve => { release = resolve; });
  intercepted = new Promise<void>(resolve => { started = resolve; });
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.docx');
  await page.getByRole('button', {name: 'Fill profile from resume'}).click();
  await intercepted;
  await page.getByRole('button', {name: 'Discard changes'}).click();
  const response = page.waitForResponse(value => value.url().endsWith('/preview'));
  release();
  await response;
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue(savedName);
  await expect(page.getByRole('button', {name: 'Discard changes', exact: true})).toBeDisabled();
});


test('resume upload validates files and explains proxy failures before a successful retry', async ({page}) => {
  await login(page);
  await page.getByLabel('Resume document').setInputFiles({name:'resume.txt', mimeType:'text/plain', buffer:Buffer.from('synthetic')});
  await expect(page.getByRole('alert').filter({hasText:'Choose a nonempty PDF or DOCX'})).toBeVisible();
  await expect(page.getByRole('button', {name:'Fill profile from resume'})).toBeDisabled();
  await page.route('**/api/resume-imports/upload?*', route => route.fulfill({status:413, contentType:'text/html', body:'Request too large'}));
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.pdf');
  await page.getByRole('button', {name:'Fill profile from resume'}).click();
  await expect(page.getByRole('alert').filter({hasText:'server rejected this file as too large'})).toBeVisible();
  await page.unroute('**/api/resume-imports/upload?*');
  await page.getByRole('button', {name:'Fill profile from resume'}).click();
  await expect(page.getByRole('status').filter({hasText:'Profile fields filled.'})).toBeVisible();
  await page.getByRole('button', {name:'Discard changes', exact:true}).click();
});
