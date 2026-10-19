import {test, expect} from './workspace-fixture';
import {readFile} from 'node:fs/promises';
test('configured model draft, inspect facts, preview, download and explicit review without destinations', async ({page}) => {
  await page.goto(`/settings/#setup=${JSON.parse(await readFile('test-results-tailored/setup.json','utf8')).token}`);

  await page.getByLabel('Username', {exact:true}).fill('synthetic-tailored-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-tailored-password');
  await page.getByRole('button', {name:'Create owner account'}).click();
  await expect(page.getByLabel('Name',{exact:true})).toBeVisible();
  const job = JSON.parse(await readFile('test-results-tailored/job.json','utf8'));
  await page.goto(`/?selected=${job.id}`);
  await page.getByRole('tab', {name:'Résumé', exact:true}).click();
  await page.getByRole('button', {name:'Generate job-specific résumé',exact:true}).click();
  await expect(page.getByText(/Draft awaiting your review/)).toBeVisible({timeout:20000});
  await page.getByText('Inspect selected and omitted facts').click();
  await expect(page.getByText(/Built a Python API serving 120/)).toBeVisible();
  await expect(page.getByText(/Developed an accessible dashboard/)).toBeVisible();
  const state = await (await page.request.get(`/api/jobs/${job.id}/resume`)).json();
  await page.getByRole('button', {name:'Preview PDF',exact:true}).click();
  await expect(page.getByTitle('Job-specific résumé PDF preview')).toHaveAttribute('src',state.preview_url);
  const pdf = await page.request.get(state.preview_url);
  expect(pdf.headers()['content-disposition']).toContain('inline');
  expect((await pdf.body()).subarray(0,5).toString()).toBe('%PDF-');
  await expect.poll(() => page.frames().map(f=>f.url()).join(' ')).toContain('chrome-extension://');
  const viewer = page.frames().find(f=>f.url().startsWith('chrome-extension://'))!;
  await expect.poll(()=>viewer.evaluate(()=>(document.querySelector('pdf-viewer') as HTMLElement & {initialLoadComplete_:boolean})?.initialLoadComplete_)).toBe(true);
  const event = page.waitForEvent('download');
  await page.getByRole('link',{name:'Download draft PDF'}).click();
  await (await event).saveAs('test-results-tailored/t12-tailored-browser.pdf');
  await page.getByRole('button',{name:'I reviewed this draft and its omissions'}).click();
  await expect(page.getByText(/Review recorded/)).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path:'test-results-tailored/t12-mobile.png',fullPage:true});
});

test('TeX upload, AI source draft, download and explicit PDF rendering', async ({page}) => {
  await page.goto('/settings/');
  await page.getByLabel('Username', {exact:true}).fill('synthetic-tailored-owner');
  await page.getByLabel('Password', {exact:true}).fill('synthetic-tailored-password');
  await page.getByRole('button', {name:'Sign in', exact:true}).click();
  await expect(page.getByLabel('Name', {exact:true})).toBeVisible();
  const session = await (await page.request.get('/api/session')).json();
  const snapshot = await (await page.request.get('/api/profile-settings')).json();
  const reset = await page.request.post('/api/profile-settings', {
    headers: {'X-CSRF-Token': session.csrf},
    data: {expected_revision: snapshot.revision, profile: {}, preferences: {}}
  });
  expect(reset.ok()).toBe(true);
  await page.reload();
  const source = String.raw`\documentclass{article}
\begin{document}
Synthetic Candidate\par
synthetic@example.test\par
\section{Education}
Example University\par
Bachelor of Science in Computing\par
\section{Experience}
Built an example reporting tool.\par
% Optional interests
\end{document}
`;
  await page.locator('.settings-import > summary').click();
  await page.getByLabel('Resume document').setInputFiles({
    name: 'synthetic-resume.tex', mimeType: 'application/x-tex', buffer: Buffer.from(source)
  });
  await page.getByRole('button', {name:'Fill profile from resume', exact:true}).click();
  await expect(page.getByLabel('Name', {exact:true})).toHaveValue('Synthetic Candidate');
  await expect(page.getByLabel('Institution', {exact:true})).toHaveValue('Example University');
  await page.getByRole('button', {name:'Save changes', exact:true}).click();
  await expect(page.getByRole('status').filter({hasText:/Profile saved\./})).toBeVisible();
  const job = JSON.parse(await readFile('test-results-tailored/job.json','utf8'));
  await page.goto(`/?selected=${job.id}`);
  await page.getByRole('tab', {name:'Résumé', exact:true}).click();
  await page.getByRole('button', {name:'Generate job-specific résumé', exact:true}).click();
  await expect(page.getByText('TeX source ready', {exact:false})).toBeVisible({timeout:20000});
  await expect(page.getByRole('button', {name:'Preview PDF', exact:true})).toHaveCount(0);
  const draft = await (await page.request.get(`/api/jobs/${job.id}/resume`)).json();
  const tex = await page.request.get(draft.source_url);
  expect(tex.headers()['content-disposition']).toContain('tailored-resume.tex');
  expect(await tex.text()).toContain('Built an example reporting tool.');
  expect(await tex.text()).not.toContain('Optional interests');
  await expect(page.getByRole('link', {name:'Download tailored TeX'})).toBeVisible();
  await page.getByRole('button', {name:'Render PDF', exact:true}).click();
  await expect(page.getByRole('button', {name:'Preview PDF', exact:true})).toBeVisible({timeout:20000});
  const rendered = await (await page.request.get(`/api/jobs/${job.id}/resume`)).json();
  const pdf = await page.request.get(rendered.preview_url);
  expect((await pdf.body()).subarray(0,5).toString()).toBe('%PDF-');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
