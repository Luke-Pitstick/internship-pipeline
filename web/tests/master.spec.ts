import { test, expect, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

async function renderedPreview(page: Page) {
  await page.getByTitle('Master résumé PDF preview').scrollIntoViewIfNeeded();
  await expect.poll(() => page.frames().map(f => f.url()).join('\n')).toContain('chrome-extension://');
  const viewer = page.frames().find(f => f.url().startsWith('chrome-extension://'))!;
  await expect.poll(() => viewer.evaluate(() =>
    (document.querySelector('pdf-viewer') as HTMLElement & {initialLoadComplete_: boolean})?.initialLoadComplete_
  )).toBe(true);
}

test('master PDF uses saved facts, generates, previews, downloads, caches and handles errors on mobile', async ({page}) => {
  await page.goto('/settings/');
  await page.getByLabel('Operator setup token').fill(JSON.parse(await readFile('test-results-master/setup.json', 'utf8')).token);
  await page.getByLabel('Username', {exact: true}).fill('synthetic-master-owner');
  await page.getByLabel('Password', {exact: true}).fill('synthetic-master-password');
  await page.getByRole('button', {name: 'Create owner account'}).click();
  await page.getByLabel('Name', {exact: true}).fill('Synthetic Candidate');
  await page.getByLabel('Email', {exact: true}).fill('synthetic@example.test');
  await page.getByRole('button', {name: 'Add fact or skill'}).click();
  await page.getByLabel('Supporting fact').fill('Built a Python survey API processing 120 synthetic requests per day.');
  await page.getByLabel('Confirmation', {exact: true}).selectOption('confirmed');
  await page.getByRole('button', {name: 'Add education'}).click();
  await page.getByLabel('Institution', {exact: true}).fill('Example University');
  await page.getByLabel('Degree', {exact: true}).fill('Bachelor of Science');
  await page.getByLabel('Education confirmation', {exact: true}).selectOption('confirmed');
  await page.getByRole('button', {name: 'Resume Generation', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Generate master résumé', exact: true})).toBeDisabled();
  await page.getByRole('button', {name: 'Profile', exact: true}).click();
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(page.getByText('Active revision 1', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Resume Generation', exact: true}).click();
  await page.getByRole('button', {name: 'Generate master résumé', exact: true}).click();
  await expect(page.getByText(/Ready · saved profile revision 1/)).toBeVisible({timeout: 20000});
  const ready = await page.request.get('/api/master-resume');
  const artifact = await ready.json();
  await page.getByRole('button', {name: 'Preview master PDF'}).click();
  const frame = page.getByTitle('Master résumé PDF preview');
  await expect(frame).toHaveAttribute('src', artifact.preview_url);
  const preview = await page.request.get(artifact.preview_url);
  expect(preview.headers()['x-frame-options']).toBe('SAMEORIGIN');
  expect(preview.headers()['content-disposition']).toContain('inline');
  expect((await preview.body()).subarray(0, 5).toString()).toBe('%PDF-');
  await renderedPreview(page);
  await page.screenshot({path: 'test-results-master/t11-master-desktop.png', fullPage: true});
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('link', {name: 'Download master PDF'}).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('master-resume.pdf');
  await download.saveAs('test-results-master/t11-master-browser.pdf');
  await page.getByRole('button', {name: 'Reuse saved master PDF'}).click();
  await expect(page.getByText(/Ready · saved profile revision 1/)).toBeVisible();
  expect((await (await page.request.get('/api/master-resume')).json()).completed_at).toBe(artifact.completed_at);
  await page.setViewportSize({width: 390, height: 844});
  await page.getByRole('button', {name: 'Preview master PDF'}).click();
  await renderedPreview(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results-master/t11-master-mobile.png', fullPage: true});
  await page.getByRole('button', {name: 'Profile', exact: true}).click();
  await page.getByLabel('Name', {exact: true}).fill('Unsupported 😃');
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(page.getByText('Active revision 2', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Resume Generation', exact: true}).click();
  await expect(page.getByRole('link', {name: 'Download master PDF'})).toHaveCount(0);
  await page.getByRole('button', {name: 'Generate master résumé', exact: true}).click();
  await expect(page.getByRole('alert')).toContainText('unsupported character');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results-master/t11-master-error-mobile.png', fullPage: true});
});
