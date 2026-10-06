import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('model connections save, edit, test, persist and remove without revealing credentials', async ({ page }) => {
  await page.goto('/settings/');
  await expect(page.getByLabel('Password', {exact: true})).toBeVisible();
  if (await page.getByLabel('Operator setup token').isVisible()) {
    const token = JSON.parse(await readFile('test-results/setup.json', 'utf8')).token;
    await page.getByLabel('Operator setup token').fill(token);
    await page.getByLabel('Username', {exact: true}).fill('synthetic-owner');
    await page.getByLabel('Password', {exact: true}).fill('synthetic-owner-password');
    await page.getByRole('button', {name: 'Create owner account'}).click();
  } else {
    await page.getByLabel('Username', {exact: true}).fill('synthetic-owner');
    await page.getByLabel('Password', {exact: true}).fill('synthetic-owner-password');
    await page.getByRole('button', {name: 'Sign in', exact: true}).click();
  }
  await page.getByRole('button', {name: 'AI Models', exact: true}).click();
  const jev = page.locator('form').filter({has: page.getByRole('heading', {name: 'Jev', exact: true})});
  const general = page.locator('form').filter({has: page.getByRole('heading', {name: 'General LLM', exact: true})});
  await jev.getByLabel('API key', {exact: true}).fill('synthetic-browser-secret');
  await jev.getByRole('button', {name: 'Save Jev', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Jev saved.'})).toBeVisible();
  await expect(jev.locator('input[type=password]')).toHaveValue('');
  await expect(jev.getByRole('button', {name: 'Test Jev', exact: true})).toBeEnabled();
  await page.reload();
  await page.getByRole('button', {name: 'AI Models', exact: true}).click();
  await expect(jev.locator('input[type=password]')).toHaveValue('');
  await expect(jev.getByText('Saved · test required', {exact: true})).toBeVisible();
  await jev.getByLabel('Model', {exact: true}).fill('jev-latest');
  await expect(jev.getByRole('button', {name: 'Test Jev', exact: true})).toBeDisabled();
  await jev.getByRole('button', {name: 'Save Jev', exact: true}).click();
  await expect(jev.getByRole('button', {name: 'Test Jev', exact: true})).toBeEnabled();
  // The API's provider transport is tested with MockTransport in Python. Browser
  // feedback is stubbed only here, so CI never sends invented keys to a provider.
  await page.route('**/api/model-connections/jev/test', async route => {
    const response = await page.request.get('/api/model-connections');
    const state = (await response.json()).jev;
    state.ready = true; state.tested_revision = state.revision;
    state.last_test = {status: 'success', effective_model: 'jev-1.13.0', input_tokens: 120, output_tokens: 60};
    await route.fulfill({json: {connection: state, status: 'success', message: 'Synthetic capability test passed.'}});
  });
  await jev.getByRole('button', {name: 'Test Jev', exact: true}).click();
  await expect(jev.getByText('Capability test passed', {exact: true})).toBeVisible();
  await expect(jev.getByText('Effective model:', {exact: false})).toContainText('jev-1.13.0');
  await general.getByLabel('Model', {exact: true}).fill('test-model');
  await general.getByLabel('API key', {exact: true}).fill('synthetic-other-secret');
  await general.getByRole('button', {name: 'Save General LLM', exact: true}).click();
  await expect(general.locator('input[type=password]')).toHaveValue('');
  await expect(general.getByText('Saved · test required', {exact: true})).toBeVisible();
  await jev.getByRole('button', {name: 'Remove Jev', exact: true}).click();
  await jev.getByRole('button', {name: 'Confirm removal', exact: true}).click();
  await expect(jev.getByText('Not configured', {exact: true})).toBeVisible();
  await expect(general.getByText('Saved · test required', {exact: true})).toBeVisible();
  await general.getByRole('button', {name: 'Remove General LLM', exact: true}).click();
  await general.getByRole('button', {name: 'Confirm removal', exact: true}).click();
  await expect(general.getByText('Not configured', {exact: true})).toBeVisible();
  await page.reload();
  await page.getByRole('button', {name: 'AI Models', exact: true}).click();
  await expect(jev.getByText('Not configured', {exact: true})).toBeVisible();
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: 'test-results/t05-model-settings-mobile.png', fullPage: true});
});
