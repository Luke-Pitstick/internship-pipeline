import { test, expect } from './workspace-fixture';
import { readFile } from 'node:fs/promises';

test('model connections save, edit, test, persist and remove without revealing credentials', async ({ page }) => {
  await page.route('**/api/model-connections/general/models', route => {
    const {endpoint} = route.request().postDataJSON();
    const id = endpoint.includes('anthropic') ? 'synthetic-claude' : endpoint.includes('openrouter') ? 'anthropic/synthetic-claude' : 'test-model';
    return route.fulfill({json: {models: [{id, name: id}]}});
  });
  const token = JSON.parse(await readFile(process.env.PIPELINE_BROWSER_SETUP ?? 'test-results/setup.json', 'utf8')).token;
  await page.goto(`/settings/#setup=${token}`);
  await expect(page.getByLabel('Password', {exact: true})).toBeVisible();
  if (await page.getByRole('button', {name: 'Create owner account'}).isVisible()) {
    await page.getByLabel('Username', {exact: true}).fill('synthetic-owner');
    await page.getByLabel('Password', {exact: true}).fill('synthetic-owner-password');
    await page.getByRole('button', {name: 'Create owner account'}).click();
  } else {
    await page.getByLabel('Username', {exact: true}).fill('synthetic-owner');
    await page.getByLabel('Password', {exact: true}).fill('synthetic-owner-password');
    await page.getByRole('button', {name: 'Sign in', exact: true}).click();
  }
  await page.getByRole('button', {name: 'AI Models', exact: true}).click();
  const limits = page.getByRole('region', {name: 'Scoring limits', exact: true});
  await expect(limits.getByLabel('Scoring calls per hour')).toHaveValue('60');
  await limits.getByLabel('Scoring calls per hour').fill('300');
  await limits.getByLabel('Scoring calls per day').fill('1500');
  await limits.getByLabel('Scoring tokens per day').fill('50000000');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('link', {name: 'Jobs', exact: true}).click();
  await expect(limits.getByLabel('Scoring tokens per day')).toHaveValue('50000000');
  await limits.getByRole('button', {name: 'Save scoring limits', exact: true}).click();
  await expect(limits.getByRole('status')).toHaveText('Scoring limits saved. Paused jobs will resume when the new limits allow.');
  await page.reload();
  await page.getByRole('button', {name: 'AI Models', exact: true}).click();
  await expect(limits.getByLabel('Scoring calls per hour')).toHaveValue('300');
  await expect(limits.getByLabel('Scoring calls per day')).toHaveValue('1500');
  await expect(limits.getByLabel('Scoring tokens per day')).toHaveValue('50000000');
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
  await general.getByLabel('API key', {exact: true}).fill('synthetic-other-secret');
  await general.getByLabel('Model', {exact: true}).fill('test-model');
  await general.getByLabel('Model', {exact: true}).press('ArrowDown');
  await general.getByLabel('Model', {exact: true}).press('Enter');
  await general.getByRole('button', {name: 'Save General LLM', exact: true}).click();
  await expect(general.locator('input[type=password]')).toHaveValue('');
  await expect(general.getByText('Saved · test required', {exact: true})).toBeVisible();
  await general.getByLabel('Provider', {exact: true}).selectOption({label: 'Claude (Anthropic)'});
  await expect(general.getByLabel('Model', {exact: true})).toHaveValue('');
  await expect(general.locator('input[type=password]')).toHaveAttribute('required', '');
  await general.getByRole('button', {name: 'Discard General LLM changes', exact: true}).click();
  await expect(general.getByLabel('Provider', {exact: true})).toHaveValue('https://api.openai.com/v1/responses');
  await expect(general.getByText('test-model', {exact: true}).first()).toBeVisible();
  await page.route('**/api/model-connections/general/test', async route => {
    const response = await page.request.get('/api/model-connections');
    const state = (await response.json()).general;
    state.ready = true; state.tested_revision = state.revision;
    state.last_test = {status: 'success', effective_model: state.config.model, input_tokens: 40, output_tokens: 20};
    await route.fulfill({json: {connection: state, status: 'success', message: 'Synthetic capability test passed.'}});
  });
  for (const provider of [
    {label: 'Claude (Anthropic)', endpoint: 'https://api.anthropic.com/v1/messages', model: 'synthetic-claude'},
    {label: 'OpenRouter', endpoint: 'https://openrouter.ai/api/v1/chat/completions', model: 'anthropic/synthetic-claude'}
  ]) {
    await general.getByLabel('Provider', {exact: true}).selectOption({label: provider.label});
    await expect(general.getByLabel('Endpoint', {exact: true})).toHaveValue(provider.endpoint);
    await expect(general.getByLabel('Model', {exact: true})).toHaveValue('');
    await expect(general.locator('input[type=password]')).toHaveValue('');
    await expect(general.locator('input[type=password]')).toHaveAttribute('required', '');
    await expect(general.getByRole('button', {name: 'Test General LLM', exact: true})).toBeDisabled();
    await general.locator('input[type=password]').fill('synthetic-' + provider.model.replace('/', '-'));
    await general.getByLabel('Model', {exact: true}).fill(provider.model);
    await general.getByLabel('Model', {exact: true}).press('ArrowDown');
    await general.getByLabel('Model', {exact: true}).press('Enter');
    await general.getByRole('button', {name: 'Save General LLM', exact: true}).click();
    await expect(general.getByText('Saved · test required', {exact: true})).toBeVisible();
    await general.getByRole('button', {name: 'Test General LLM', exact: true}).click();
    await expect(general.getByText('Capability test passed', {exact: true})).toBeVisible();
    await page.reload();
    await page.getByRole('button', {name: 'AI Models', exact: true}).click();
    await expect(general.getByLabel('Provider', {exact: true})).toHaveValue(provider.endpoint);
    await expect(general.getByText(provider.model, {exact: true}).first()).toBeVisible();
    await expect(general.locator('input[type=password]')).toHaveValue('');
  }
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

test('catalogs handle delayed provider switches, public lookup, empty results and retry', async ({page}) => {
  const empty = {configured:false, revision:0, tested_revision:null, ready:false, config:null, last_test:null};
  await page.route('**/api/model-connections', route => route.fulfill({json:{jev:empty, general:empty}}));
  let releaseOpenAI!: () => void;
  const pendingOpenAI = new Promise<void>(resolve => releaseOpenAI = resolve);
  let mode: 'success' | 'empty' | 'error' = 'success';
  await page.route('**/api/model-connections/general/models', async route => {
    const body = route.request().postDataJSON();
    if (body.endpoint.includes('api.openai.com')) {
      expect(body.api_key).toBe('synthetic-draft-key');
      await pendingOpenAI;
      return route.fulfill({json:{models:[{id:'old-openai',name:'Old OpenAI response'}]}});
    }
    expect(body.endpoint).toContain('openrouter.ai');
    expect(body).not.toHaveProperty('api_key');
    if (mode === 'error') return route.fulfill({status:502,json:{detail:'Model-list rate limit reached. Try again later.'}});
    return route.fulfill({json:{models:mode === 'empty' ? [] : [
      {id:'example/first',name:'First Model'}, {id:'example/second',name:'Second Model'}
    ]}});
  });
  const token = JSON.parse(await readFile(process.env.PIPELINE_BROWSER_SETUP ?? 'test-results/setup.json', 'utf8')).token;
  await page.goto(`/settings/#setup=${token}`);
  await page.getByLabel('Username', {exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-owner-password');
  await page.getByRole('button', {name:await page.getByRole('button', {name:'Create owner account'}).isVisible() ? 'Create owner account' : 'Sign in',exact:true}).click();
  await page.getByRole('button', {name:'AI Models',exact:true}).click();
  const general = page.locator('form').filter({has:page.getByRole('heading', {name:'General LLM',exact:true})});
  await expect(general.getByText('Enter an API key to load available models.', {exact:true})).toBeVisible();
  const started = page.waitForRequest('**/api/model-connections/general/models');
  await general.getByLabel('API key', {exact:true}).fill('synthetic-draft-key');
  await started;
  await expect(general.getByText('Loading available models…', {exact:true})).toBeVisible();
  await general.getByLabel('Provider', {exact:true}).selectOption({label:'OpenRouter'});
  await expect(general.getByText('2 models available.', {exact:true})).toBeVisible();
  const finished = page.waitForResponse(response => response.url().endsWith('/general/models') && response.request().postDataJSON().endpoint.includes('api.openai.com'));
  releaseOpenAI();
  await finished;
  await general.getByLabel('Model', {exact:true}).fill('example/second');
  await expect(general.getByRole('option', {name:'Second Model',exact:true})).toBeVisible();
  await expect(general.getByRole('option', {name:'Old OpenAI response',exact:true})).toHaveCount(0);
  await general.getByLabel('Model', {exact:true}).press('ArrowDown');
  await general.getByLabel('Model', {exact:true}).press('Enter');
  await expect(general.getByRole('button', {name:'Save General LLM',exact:true})).toBeEnabled();
  mode = 'error';
  await general.getByRole('button', {name:'Refresh available models',exact:true}).click();
  await expect(general.getByText('Model-list rate limit reached. Try again later.', {exact:true})).toBeVisible();
  mode = 'empty';
  await general.getByRole('button', {name:'Refresh available models',exact:true}).click();
  await expect(general.getByText('No models are available for this connection.', {exact:true})).toBeVisible();
  mode = 'success';
  await general.getByRole('button', {name:'Refresh available models',exact:true}).click();
  await expect(general.getByText('2 models available.', {exact:true})).toBeVisible();
  await expect(general.getByText('Model-list rate limit reached. Try again later.', {exact:true})).toHaveCount(0);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
