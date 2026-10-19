import {test, expect, type Page} from './workspace-fixture';
import {readFile} from 'node:fs/promises';

async function login(page: Page) {
  await page.goto(`/settings/#setup=${JSON.parse(await readFile('test-results-settings/setup.json', 'utf8')).token}`);
  await page.getByLabel('Username', {exact:true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-owner-password');
  await page.getByRole('button', {name:/Create owner account|^Sign in$/}).click();
  await expect(page.getByLabel('Name', {exact:true})).toBeVisible();
}
const section = (page: Page, name: string) => page.getByRole('navigation', {name:'Settings categories'}).getByRole('button', {name, exact:true});

test('section saves and discards are independent, history preserves drafts, and leaving warns', async ({page}) => {
  await login(page);
  const before = await (await page.request.get('/api/profile-settings')).json();
  await page.getByLabel('Name', {exact:true}).fill('Settings flow candidate');
  await section(page, 'Job Filters').click();
  await expect(page.getByRole('heading', {name:'Job Filters', exact:true})).toBeFocused();
  await page.getByLabel('Preferred roles', {exact:true}).fill('Settings UX research');
  await page.getByLabel('Preferred roles', {exact:true}).press('Enter');
  await page.goBack();
  await expect(page.getByLabel('Name', {exact:true})).toHaveValue('Settings flow candidate');
  await page.goForward();
  await expect(page.getByRole('button', {name:'Remove Settings UX research', exact:true})).toBeVisible();
  await page.getByRole('button', {name:'Save changes', exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Job filters saved.'})).toBeVisible();
  const filtered = await (await page.request.get('/api/profile-settings')).json();
  expect(filtered.profile).toEqual(before.profile);
  expect(filtered.preferences.soft.roles).toContain('Settings UX research');
  await expect(section(page, 'Profile').getByLabel('Unsaved changes')).toBeVisible();
  await section(page, 'Profile').click();
  await expect(page.getByLabel('Name', {exact:true})).toHaveValue('Settings flow candidate');
  await page.getByRole('button', {name:'Save changes', exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:'Profile saved.'})).toBeVisible();
  const saved = await (await page.request.get('/api/profile-settings')).json();
  expect(saved.profile.name).toBe('Settings flow candidate');
  expect(saved.preferences).toEqual(filtered.preferences);

  await page.getByLabel('Name', {exact:true}).fill('Keep this draft');
  await section(page, 'Job Filters').click();
  await page.getByRole('button', {name:'Remove Settings UX research', exact:true}).click();
  await page.getByRole('button', {name:'Discard changes', exact:true}).click();
  await expect(page.getByRole('button', {name:'Remove Settings UX research', exact:true})).toBeVisible();
  await section(page, 'Profile').click();
  await expect(page.getByLabel('Name', {exact:true})).toHaveValue('Keep this draft');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('link', {name:'Jobs', exact:true}).click();
  await expect(page).toHaveURL(/\/settings\//);
  await page.getByRole('button', {name:'Discard changes', exact:true}).click();
});

test('selected imports survive section changes and filter saves wait for reviewed imports', async ({page}) => {
  await login(page);
  await page.locator('.settings-import > summary').click();
  await page.getByLabel('Resume document').setInputFiles('tests/fixtures/resume.synthetic.docx');
  await section(page, 'Sources').click();
  await section(page, 'Profile').click();
  await expect(page.getByRole('button', {name:'Fill profile from resume'})).toBeEnabled();
  await page.getByRole('button', {name:'Fill profile from resume'}).click();
  await expect(page.getByLabel('Name', {exact:true})).toHaveValue('Synthetic Candidate');
  await section(page, 'Job Filters').click();
  await page.getByLabel('Preferred roles', {exact:true}).fill('Import review test');
  await page.getByLabel('Preferred roles', {exact:true}).press('Enter');
  await expect(page.getByRole('button', {name:'Save changes', exact:true})).toBeDisabled();
  await page.getByRole('button', {name:'Review imported profile'}).click();
  await page.getByRole('button', {name:'Discard changes', exact:true}).click();
  await section(page, 'Job Filters').click();
  await expect(page.getByRole('button', {name:'Save changes', exact:true})).toBeEnabled();
  await page.getByRole('button', {name:'Discard changes', exact:true}).click();
});

test('integration drafts survive switching, failures retain credentials, and subviews deep link', async ({page}) => {
  await login(page);
  await section(page, 'AI Models').click();
  const jev = page.locator('form').filter({has:page.getByRole('heading', {name:'Jev', exact:true})});
  await jev.getByLabel(/^API key/).fill('synthetic-model-retry-secret');
  await page.route('**/api/model-connections/jev/save', route => route.fulfill({status:503,json:{detail:'Synthetic model save failure'}}));
  await jev.getByRole('button', {name:'Save Jev', exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic model save failure');
  await expect(jev.locator('input[type=password]')).toHaveValue('synthetic-model-retry-secret');
  await jev.getByRole('button', {name:'Discard Jev changes'}).click();
  await section(page, 'Notifications & Integrations').click();
  await page.getByLabel('SMTP host').fill('smtp.example.test');
  await page.getByLabel('Username', {exact:true}).fill('synthetic-user');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-retry-secret');
  await page.getByLabel('Sender email').fill('sender@example.test');
  await page.getByLabel('Recipient email').fill('recipient@example.test');
  await page.route('**/api/email/save', route => route.fulfill({status:503,json:{detail:'Synthetic temporary save failure'}}));
  await page.getByRole('button', {name:'Save email settings'}).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic temporary save failure');
  await expect(page.getByLabel('Password', {exact:true})).toHaveValue('synthetic-retry-secret');
  await page.getByRole('button', {name:'Google Sheets', exact:true}).click();
  await expect(page.getByLabel('Spreadsheet ID', {exact:true})).toBeVisible();
  await expect(page.getByLabel('SMTP host')).toBeHidden();
  await page.getByLabel('Spreadsheet ID', {exact:true}).fill('synthetic-settings-sheet');
  await page.getByLabel('Google service-account JSON key').fill('{"synthetic":"retry-me"}');
  await page.route('**/api/sheets/save', route => route.fulfill({status:503,json:{detail:'Synthetic sheet save failure'}}));
  await page.getByRole('button', {name:'Save Sheets connection'}).click();
  await expect(page.getByRole('alert')).toContainText('Synthetic sheet save failure');
  await expect(page.getByLabel('Google service-account JSON key')).toHaveValue('{"synthetic":"retry-me"}');
  await page.goBack();
  await expect(page.getByLabel('SMTP host')).toHaveValue('smtp.example.test');
  await page.goForward();
  await expect(page.getByLabel('Spreadsheet ID', {exact:true})).toHaveValue('synthetic-settings-sheet');
  const link = page.url();
  const other = await page.context().newPage();
  await other.goto(link);
  await expect(other.getByLabel('Spreadsheet ID', {exact:true})).toBeVisible();
  await other.close();
  page.on('dialog', dialog => dialog.accept());
  await page.getByRole('button', {name:'Discard Sheets changes'}).click();
  await page.getByRole('button', {name:'Email alerts', exact:true}).click();
  await page.getByRole('button', {name:'Discard email changes'}).click();
});

test('all settings sections fit mobile and desktop with visible navigation and keyboard targets', async ({page}) => {
  const runtimeErrors: string[] = [];
  page.on('pageerror', error => runtimeErrors.push(error.message));
  await login(page);
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({width, height:900});
    for (const name of ['Profile', 'Job Filters', 'Sources', 'Resume Generation', 'AI Models', 'Notifications & Integrations', 'Diagnostics']) {
      if (width > 760) await section(page, name).click();
      else await page.getByLabel('Settings section').selectOption(name);
      await expect(page.getByRole('heading', {name, exact:true})).toBeVisible();
      if (width > 760) {
        const bounds = await section(page, name).boundingBox();
        expect(bounds!.height).toBeGreaterThanOrEqual(44);
      } else await expect(page.getByLabel('Settings section')).toHaveCSS('font-size','16px');
      const layout = await page.evaluate(() => ({
        width: innerWidth, content: document.documentElement.scrollWidth,
        overflow: [...document.querySelectorAll<HTMLElement>('main *')].filter(element => {
          const bounds = element.getBoundingClientRect();
          return bounds.width > 0 && bounds.right > innerWidth + 1;
        }).slice(0, 12).map(element => ({tag:element.tagName,id:element.id,
          class:element.className,right:element.getBoundingClientRect().right}))
      }));
      expect(layout.content, `${name} at ${width}px: ${JSON.stringify(layout.overflow)}`).toBeLessThanOrEqual(layout.width);
      if (width === 1440 || width === 390) await page.screenshot({path:`test-results-settings/${name.toLowerCase().replaceAll(/[^a-z]+/g,'-')}-${width}.png`,animations:'disabled'});
    }
    if (width === 1440 || width === 390) {
      if (width > 760) await section(page, 'Profile').click();
      else await page.getByLabel('Settings section').selectOption('Profile');
      await page.screenshot({path:`test-results-settings/settings-${width}.png`,fullPage:true,animations:'disabled'});
    }
  }
  expect(runtimeErrors).toEqual([]);
});
