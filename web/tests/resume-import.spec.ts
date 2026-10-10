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

test('resume upload reviews source, previews, confirms, replaces safely, and rejects stale drafts', async ({page}) => {
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
  await page.getByRole('button', {name: /Upload replacement|Upload and review/}).click();
  await expect(page.getByRole('alert').filter({hasText: 'not a PDF'})).toBeVisible();
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.docx');
  await page.getByRole('button', {name: /Upload replacement|Upload and review/}).click();
  await expect(page.getByRole('group', {name: 'Review extracted facts'})).toBeVisible();
  await expect(page.getByLabel('Include source 1', {exact: true})).toBeChecked();
  await expect(page.getByLabel('Degree excerpt 3')).toHaveValue('Bachelor of Science in Computing');
  await expect(page.getByLabel('Imported skills 4')).toHaveValue('Python, SQL');
  await expect(page.getByLabel('Include source 7', {exact: true})).not.toBeChecked();
  await expect(page.getByLabel('Name', {exact: true})).toBeDisabled();
  await page.getByRole('button', {name: 'Preview profile changes'}).click();
  await expect(page.getByRole('heading', {name: 'Profile change preview'})).toBeVisible();
  await expect(page.getByText('Added skill: Python, SQL · Skills: Python, SQL', {exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Confirm and save imported profile'})).toBeDisabled();
  await page.getByLabel('I reviewed the selected claims against the source and confirm the profile changes.').check();
  await page.getByRole('button', {name: 'Confirm and save imported profile'}).click();
  await expect(page.getByRole('status').filter({hasText: 'Resume reviewed and saved'})).toBeVisible();
  saved = await (await page.request.get('/api/profile-settings')).json();
  expect(saved.profile.facts.some((item: {id: string}) => item.id === manual.id)).toBe(true);
  expect(saved.preferences.soft.skills).toEqual(['Rust']);
  expect(saved.profile.requires_sponsorship).toBeNull();
  const stableIds = saved.profile.facts.map((item: {id: string}) => item.id);
  await page.reload();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Synthetic Candidate');
  await expect(page.getByText(`Last reviewed DOCX · profile revision ${saved.revision}`, {exact: true})).toBeVisible();
  expect((await (await page.request.get('/api/profile-settings')).json()).profile.facts.map((item: {id: string}) => item.id)).toEqual(stableIds);
  await page.getByLabel('Name', {exact: true}).fill('Unsaved edit');
  await expect(page.getByRole('button', {name: 'Upload replacement'})).toBeDisabled();
  await page.getByRole('button', {name: 'Discard changes'}).click();
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/replacement.synthetic.docx');
  await page.getByRole('button', {name: 'Upload replacement'}).click();
  await page.getByLabel('Remove: Python, SQL', {exact: true}).check();
  await expect(page.getByLabel(`Remove: ${manual.text}`, {exact: true})).toHaveCount(0);
  await page.getByRole('button', {name: 'Preview profile changes'}).click();
  await expect(page.getByText('Removed: Python, SQL', {exact: true})).toBeVisible();
  await page.getByLabel('I reviewed the selected claims against the source and confirm the profile changes.').check();
  await page.getByRole('button', {name: 'Confirm and save imported profile'}).click();
  await expect(page.getByRole('status').filter({hasText: 'Resume reviewed and saved'})).toBeVisible();
  saved = await (await page.request.get('/api/profile-settings')).json();
  expect(saved.profile.facts.find((item: {id: string}) => item.id === manual.id)).toEqual(manual);
  expect(saved.profile.facts.some((item: {text: string}) => item.text === 'Python, SQL')).toBe(false);
  expect(saved.profile.facts.some((item: {text: string}) => item.text === 'Python, Go')).toBe(true);
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.pdf');
  await page.getByRole('button', {name: 'Upload replacement'}).click();
  await page.getByRole('button', {name: 'Preview profile changes'}).click();
  const competing = await page.request.post('/api/profile-settings', {headers: {'X-CSRF-Token': session.csrf}, data: {
    expected_revision: saved.revision, profile: {...saved.profile, name: 'Concurrent synthetic name'}, preferences: saved.preferences
  }});
  expect(competing.ok()).toBe(true);
  await page.getByLabel('I reviewed the selected claims against the source and confirm the profile changes.').check();
  await page.getByRole('button', {name: 'Confirm and save imported profile'}).click();
  await expect(page.getByRole('alert').filter({hasText: 'Settings changed'})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Confirm and save imported profile'})).toBeDisabled();
  await page.getByRole('button', {name: 'Reload saved profile to import again'}).click();
  await expect(page.getByLabel('Name', {exact: true})).toHaveValue('Concurrent synthetic name');
  await page.setViewportSize({width: 390, height: 844});
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.pdf');
  await page.getByRole('button', {name: 'Upload replacement'}).click();
  await expect(page.getByRole('group', {name: 'Review extracted facts'})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results/t10-resume-import-mobile.png', fullPage: true});
  await page.getByRole('button', {name: 'Cancel import'}).click();
  await expect(page.getByLabel('Resume document')).toBeVisible();
});
