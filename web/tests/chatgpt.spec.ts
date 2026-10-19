import { test, expect, type Page } from './workspace-fixture';
import { readFile } from 'node:fs/promises';

async function signIn(page: Page) {
  const token = JSON.parse(await readFile('test-results-chatgpt/setup.json', 'utf8')).token;
  await page.goto(`/settings/#setup=${token}`);
  await page.getByLabel('Username', {exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-owner-password');
  if (await page.getByRole('button', {name:'Create owner account'}).isVisible()) {
    await page.getByRole('button', {name:'Create owner account'}).click();
  } else {
    await page.getByRole('button', {name:'Sign in',exact:true}).click();
  }
}

test('ChatGPT settings connect remotely, choose an account model, test limits, and disconnect', async ({page}) => {
  await signIn(page);
  const account = {id:'a'.repeat(64), email:'synthetic@example.test', client_id:'oaiapp_synthetic', status:'connected', welcomed:false};
  let connected = false;
  let finishConnection = false;
  let limitReached = true;
  let saved: Record<string, unknown> | null = null;
  let revision = 0;
  const empty = {configured:false, revision:0, tested_revision:null, ready:false, config:null, last_test:null};
  await page.route('**/api/model-connections', route => route.fulfill({json:{jev:empty, general: saved ?? empty}}));
  await page.route('**/api/chatgpt', route => route.fulfill({json:{accounts:connected ? [account] : [], local:false}}));
  await page.route('**/api/chatgpt/start', route => {
    expect(route.request().postDataJSON()).toEqual({expected_revision:revision, account_id:connected ? account.id : null});
    return route.fulfill({json:{attempt_id:'synthetic-attempt', authorize_url:null, pairing_code:'synthetic-pairing-code-for-browser-only'}});
  });
  await page.route('**/api/chatgpt/status', route => {
    if (finishConnection) connected = true;
    return route.fulfill({json:{status:finishConnection ? 'connected' : 'paired', account_id: finishConnection ? account.id : null}});
  });
  await page.route('**/api/chatgpt/models', route => route.fulfill({json:{models:[{slug:'synthetic-model',display_name:'Synthetic ChatGPT Model'}]}}));
  await page.route('**/api/chatgpt/welcome', route => {account.welcomed=true;return route.fulfill({json:{acknowledged:true}});});
  await page.route('**/api/model-connections/general/save', route => {
    const {expected_revision, ...config} = route.request().postDataJSON();
    expect(expected_revision).toBe(revision);
    expect(config.auth_mode).toBe('chatgpt');
    expect(config.chatgpt_account_id).toBe(account.id);
    expect(config.model).toBe('synthetic-model');
    expect(config).not.toHaveProperty('api_key');
    saved = {...empty,configured:true,revision:++revision,config};
    return route.fulfill({json:saved});
  });
  await page.route('**/api/model-connections/general/test', route => {
    const status = limitReached ? 'subscription_limit' : 'success';
    saved = {...saved, ready:!limitReached, tested_revision:limitReached ? null : revision,
      last_test:{status,effective_model:'synthetic-model',input_tokens:40,output_tokens:20}};
    return route.fulfill({json:{connection:saved,status,message:limitReached
      ? 'ChatGPT plan usage limit reached. Manage usage in ChatGPT settings.' : 'Synthetic capability test passed.'}});
  });
  await page.route('**/api/chatgpt/disconnect', route => {
    account.status='disconnected';
    saved = {...saved,ready:false};
    return route.fulfill({json:{revoked:false,message:'Disconnected locally. Remote revocation was not confirmed; disconnect the app in ChatGPT settings to end remote access.'}});
  });

  await page.goto('/settings/#AI%20Models');
  const general = page.locator('form').filter({has:page.getByRole('heading',{name:'General LLM',exact:true})});
  await general.getByLabel('Provider',{exact:true}).selectOption('chatgpt');
  await expect(general.locator('input[type=password]')).toHaveCount(0);
  await expect(general.getByLabel('Maximum output tokens')).toHaveCount(0);
  await expect(general.getByRole('button',{name:'Save General LLM',exact:true})).toBeDisabled();
  const buttonColors = await general.getByRole('button',{name:'Continue with ChatGPT',exact:true}).evaluate(element => {
    const style = getComputedStyle(element); return {color:style.color, background:style.backgroundColor};
  });
  expect(buttonColors.color).not.toBe(buttonColors.background);
  expect(buttonColors.background).not.toBe('rgba(0, 0, 0, 0)');
  await general.getByRole('button',{name:'Continue with ChatGPT',exact:true}).click();
  await expect(general.getByRole('link',{name:'Download the ChatGPT connection helper'})).toHaveAttribute('href','/api/chatgpt/helper');
  await expect(general.getByLabel('One-time pairing code')).toHaveText('synthetic-pairing-code-for-browser-only');
  await expect(general.locator('code')).toContainText('--origin http://127.0.0.1:4187');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:'test-results-chatgpt/remote-mobile.png',fullPage:true});
  finishConnection = true;
  const welcome = page.getByRole('dialog');
  await expect(welcome).toBeVisible();
  await expect(welcome.getByRole('heading')).toHaveText("You're using your ChatGPT plan");
  await welcome.getByRole('button',{name:'Got it'}).click();
  await expect(welcome).not.toBeVisible();
  await expect(general.getByLabel('ChatGPT account')).toHaveValue(account.id);
  await general.getByLabel('Model',{exact:true}).selectOption('synthetic-model');
  await general.getByRole('button',{name:'Save General LLM',exact:true}).click();
  await expect(general.getByRole('button',{name:'Test General LLM',exact:true})).toBeEnabled();
  await general.getByRole('button',{name:'Test General LLM',exact:true}).click();
  await expect(page.getByRole('alert').filter({hasText:'ChatGPT plan usage limit reached'})).toBeVisible();
  await expect(general.getByRole('link',{name:'Manage usage',exact:true})).toHaveAttribute('href','https://chatgpt.com/settings/usage');
  limitReached = false;
  await general.getByRole('button',{name:'Test General LLM',exact:true}).click();
  await expect(general.getByText('Capability test passed',{exact:true})).toBeVisible();
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:'test-results-chatgpt/connected-desktop.png',fullPage:true});
  // Restoring a saved draft must restore its account-specific catalog too.
  const another = {...account,id:'b'.repeat(64),email:'another@example.test',client_id:'oaiapp_another',welcomed:true};
  await page.route('**/api/chatgpt', route => route.fulfill({json:{accounts:[account,another],local:false}}));
  await page.route('**/api/chatgpt/models', route => route.fulfill({json:{models:route.request().postDataJSON().account_id === account.id
    ? [{slug:'synthetic-model',display_name:'Synthetic ChatGPT Model'}] : [{slug:'other-model',display_name:'Other account model'}]}}));
  await page.reload();
  await expect(page.getByRole('heading',{name:'AI Models',exact:true})).toBeVisible();
  await expect(general.getByLabel('Model',{exact:true})).toHaveValue('synthetic-model');
  await general.getByLabel('ChatGPT account').selectOption(another.id);
  await general.getByLabel('Model',{exact:true}).selectOption('other-model');
  await general.getByRole('button',{name:'Discard General LLM changes',exact:true}).click();
  await expect(general.getByLabel('ChatGPT account')).toHaveValue(account.id);
  await expect(general.getByLabel('Model',{exact:true})).toHaveValue('synthetic-model');
  await expect(general.getByLabel('Model',{exact:true}).locator('option[value="other-model"]')).toHaveCount(0);
  await general.getByLabel('ChatGPT account').selectOption(another.id);
  await general.getByLabel('Model',{exact:true}).selectOption('other-model');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button',{name:'Reload model connections'}).click();
  await expect(general.getByLabel('ChatGPT account')).toHaveValue(account.id);
  await expect(general.getByLabel('Model',{exact:true})).toHaveValue('synthetic-model');
  await general.getByRole('button',{name:'Disconnect ChatGPT',exact:true}).click();
  await general.getByRole('button',{name:'Confirm disconnect',exact:true}).click();
  await expect(general.getByRole('status')).toContainText('Remote revocation was not confirmed');
  await expect(general.getByText('Reconnect this account to use its ChatGPT plan.')).toBeVisible();
  expect(await page.evaluate(() => Object.keys(localStorage).some(key => /chatgpt|token|pairing/i.test(key)))).toBe(false);
});

test('local ChatGPT sign-in opens an authorization tab and cancellation remains available', async ({page}) => {
  await signIn(page);
  await page.route('**/api/chatgpt', route => route.fulfill({json:{accounts:[],local:true}}));
  await page.route('**/api/chatgpt/start', route => route.fulfill({json:{attempt_id:'local-attempt',pairing_code:null,authorize_url:'http://127.0.0.1:4187/synthetic-chatgpt-authorization'}}));
  await page.context().route('**/synthetic-chatgpt-authorization', route => route.fulfill({contentType:'text/html',body:'<title>Synthetic OpenAI authorization</title>'}));
  await page.route('**/api/chatgpt/status', route => route.fulfill({json:{status:'pending',account_id:null}}));
  await page.route('**/api/chatgpt/cancel', route => route.fulfill({json:{cancelled:true}}));
  await page.goto('/settings/#AI%20Models');
  await page.getByLabel('Provider',{exact:true}).selectOption('chatgpt');
  const popup = page.waitForEvent('popup');
  await page.getByRole('button',{name:'Continue with ChatGPT',exact:true}).click();
  const signInTab = await popup;
  await expect(signInTab).toHaveTitle('Synthetic OpenAI authorization');
  await expect(page.getByRole('status').filter({hasText:'Complete sign-in in the OpenAI tab'})).toBeVisible();
  await page.getByRole('button',{name:'Cancel connection',exact:true}).click();
  await expect(page.getByRole('button',{name:'Continue with ChatGPT',exact:true})).toBeVisible();
  await signInTab.close();
});
