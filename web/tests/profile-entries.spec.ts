import { test, expect } from './workspace-fixture';
import { readFile } from 'node:fs/promises';

test('typed profile sections save structured details and skills on desktop and mobile', async ({page}) => {
  const runtimeErrors: string[] = [];
  page.on('pageerror', error => runtimeErrors.push(error.message));
  const {token} = JSON.parse(await readFile('test-results/setup.json', 'utf8'));
  await page.goto(`/settings/#setup=${token}`);
  await page.getByLabel('Username', {exact: true}).fill('synthetic-owner');
  await page.getByLabel('Password', {exact: true}).fill('synthetic-owner-password');
  await page.getByRole('button', {name: /Create owner account|^Sign in$/}).click();
  await expect(page.getByLabel('Name', {exact: true})).toBeVisible();
  const {csrf} = await (await page.request.get('/api/session')).json();
  const saved = await (await page.request.get('/api/profile-settings')).json();
  expect((await page.request.post('/api/profile-settings', {headers: {'X-CSRF-Token': csrf}, data: {
    expected_revision: saved.revision, profile: {}, preferences: {}
  }})).ok()).toBe(true);
  await page.reload();
  for (const name of ['Experience', 'Projects', 'Skills', 'Education']) {
    await expect(page.getByRole('heading', {name, exact: true})).toBeVisible();
  }
  await expect(page.getByText('Fact ID:', {exact: false})).toHaveCount(0);
  await expect(page.getByLabel('Type', {exact: true})).toHaveCount(0);
  await page.getByRole('button', {name: 'Add experience', exact: true}).click();
  const experience = page.getByRole('group', {name: 'Experience 1', exact: true});
  await expect(experience.getByLabel('Job title')).toBeFocused();
  await experience.getByLabel('Job title').fill('Software intern');
  await experience.getByLabel('Company', {exact: true}).fill('Example Company');
  await experience.getByLabel('Location', {exact: true}).fill('Denver, CO');
  await experience.getByLabel('Start date').fill('2026-06');
  await experience.getByLabel('End date').fill('2026-05');
  await experience.getByLabel('Responsibilities & accomplishments').fill('Built a reporting tool.');
  await experience.getByLabel('I confirm this experience').check();
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(experience.getByText('End date must be on or after the start date.')).toBeVisible();
  await experience.getByLabel('I currently work here', {exact: false}).check();
  await expect(experience.getByLabel('End date')).toBeDisabled();
  await expect(experience.getByLabel('End date')).toHaveValue('');
  await page.getByRole('button', {name: 'Add project', exact: true}).click();
  const project = page.getByRole('group', {name: 'Project 1', exact: true});
  await project.getByLabel('Project title', {exact: true}).fill('Course planner');
  await project.getByLabel('Project skills').fill('TypeScript');
  await project.getByLabel('Project skills').press('Enter');
  await project.getByRole('button', {name: 'Add link', exact: true}).click();
  await project.getByLabel('Link 1', {exact: true}).fill('https://example.test/planner');
  await project.getByLabel('I confirm this project').check();
  await page.getByLabel('Your skills').fill('Custom synthetic skill');
  await page.getByLabel('Your skills').press('Enter');
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Profile saved.'})).toBeVisible();
  await page.reload();
  await expect(experience.getByLabel('Company', {exact: true})).toHaveValue('Example Company');
  await expect(experience.getByLabel('I currently work here', {exact: false})).toBeChecked();
  await expect(project.getByLabel('Link 1', {exact: true})).toHaveValue('https://example.test/planner');
  await expect(project.getByRole('button', {name: 'Remove TypeScript', exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Remove Custom synthetic skill', exact: true})).toBeVisible();
  const snapshot = await (await page.request.get('/api/profile-settings')).json();
  expect(snapshot.profile.facts.find((fact: {kind: string}) => fact.kind === 'experience')).toMatchObject({
    title: 'Software intern', company: 'Example Company', location: 'Denver, CO',
    start_date: '2026-06', end_date: null, current: true, status: 'confirmed'
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height: 900});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: `test-results/profile-entries-${width}.png`, fullPage: true});
  }
  await project.getByRole('button', {name: 'Remove project 1', exact: true}).click();
  await page.getByRole('button', {name: 'Remove Custom synthetic skill', exact: true}).click();
  await page.getByRole('button', {name: 'Save changes', exact: true}).click();
  await expect(page.getByRole('status').filter({hasText: 'Profile saved.'})).toBeVisible();
  expect(runtimeErrors).toEqual([]);

  // The setup step uses the same editor and persisted entries.
  await page.context().unroute('**/api/onboarding');
  await page.goto('/setup/');
  await page.getByLabel('Defer model work and collect jobs first').check();
  await page.getByRole('button', {name: 'Continue', exact: true}).click();
  await expect(page.getByRole('heading', {name: 'Profile & résumé', exact: true})).toBeVisible();
  await expect(experience.getByLabel('Job title')).toHaveValue('Software intern');
  await expect(page.getByRole('button', {name: 'Add project', exact: true})).toBeVisible();
  await expect(page.getByText('Fact ID:', {exact: false})).toHaveCount(0);
});
