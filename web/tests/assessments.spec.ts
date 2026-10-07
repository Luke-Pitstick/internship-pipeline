import {test, expect} from '@playwright/test';

// Browser fixtures contain only persisted API-shaped decisions. The Python suite
// exercises the real Jev service, owner API and revision races with MockTransport.
const criterion = {outcome: 'violated', confidence: 1, probabilities: {satisfied: 0, violated: 1, not_stated: 0, ambiguous: 0}, evidence_id: 'p1', evidence_probability: 1, evidence_confidence: 1};
const assessment = {
  identity: 'synthetic-identity', job_id: 'synthetic-job', job_revision: 'synthetic-job-revision', opening_revision: 0,
  profile_revision: 3, connection_revision: 7, selected_model: 'jev-latest', effective_model: 'jev-1.13.0', rubric_revision: 'synthetic-rubric',
  recommendation: 'review', eligible: null, normalized_fit: 92.5, assessed_at: 1791280800,
  criteria: {role: criterion}, dimensions: {skills: {score: 3, normalized: 100, weight: .35, confidence: .9, probabilities: {'0': 0, '1': 0, '2': 0, '3': 1}}},
  evidence: {p1: 'Explicit synthetic internship requirement. <script>untrusted instructions</script>'},
  candidate_evidence: {'fact-python': 'Built Python APIs.'}, uncertainty: ['role'], exact_checks: {job_open: 'satisfied'}, input_tokens: 100, output_tokens: 40
};

for (const narrow of [false, true]) {
  test(`persisted assessment detail, pending/error and explicit Applied actions ${narrow ? 'mobile' : 'desktop'}`, async ({page}) => {
    if (narrow) await page.setViewportSize({width: 390, height: 844});
    let state = 'pending', appliedAt: string | null = null, calls = 0;
    await page.route('**/api/session', route => route.fulfill({json: {authenticated: true, claimed: true, csrf: 'synthetic-csrf'}}));
    await page.route('**/api/onboarding', route => route.fulfill({json:{complete:true,has_jobs:true}}));
    await page.route('**/api/search-runs', route => route.fulfill({json:{runs:[]}}));
    await page.route('**/api/jobs/synthetic-job/resume', route => route.fulfill({json:{state:'blocked', profile_revision:0, model_revision:0}}));
    await page.route('**/api/jobs?*', route => {
      const job = {id: 'synthetic-job', title: 'Synthetic Python Internship', company: 'Example Labs', locations: ['Denver'],
        source_timestamp: '2026-09-30T12:00:00Z', first_seen: 1791280800, deadline: null, applied_at: appliedAt,
        description: 'Synthetic job description.', application_url: 'https://example.test/apply', resume: {download_path: null},
        fit: state === 'complete' ? 92.5 : null, eligible: null,
        evaluation: {state, result: state === 'complete' ? assessment : null, error: state === 'error' ? 'provider_unavailable' : null,
          attempts: state === 'pending' ? [] : [{started: 1791280800, completed: 1791280801, status: state === 'error' ? 'timeout' : 'success', reserved_tokens: 1000, input_tokens: state === 'error' ? null : 100, output_tokens: state === 'error' ? null : 40}]}};
      const params = new URL(route.request().url()).searchParams;
      const rows = params.get('view') === 'Applied' && !appliedAt ? [] : [job];
      return route.fulfill({json:{jobs:rows, selected: params.get('selected') ? job : null, pagination:{total:rows.length,page:1,pages:1,page_size:25}}});
    });
    await page.route('**/api/jobs/synthetic-job/evaluate', async route => {
      expect(route.request().method()).toBe('POST');
      expect(route.request().headers()['x-csrf-token']).toBe('synthetic-csrf');
      calls++; state = 'complete';
      await route.fulfill({json: {state: 'queued', identity: 'synthetic-identity'}});
    });
    await page.route('**/api/jobs/synthetic-job/applied', async route => {
      const body = route.request().postDataJSON();
      appliedAt = body.status === 'applied' ? '2026-10-06T12:00:00Z' : null;
      await route.fulfill({json: {applied_at: appliedAt}});
    });
    await page.goto('/');
    await expect(page.locator('[data-job]')).toHaveCount(1);
    await page.locator('[data-job]').click();
    await expect(page.getByRole('heading', {name: 'Synthetic Python Internship'})).toBeFocused();
    await expect(page.getByText('No current assessment is available.', {exact: false})).toBeVisible();
    expect(calls).toBe(0);
    await page.getByRole('button', {name: 'Evaluate job', exact: true}).click();
    await expect(page.getByText('Needs review', {exact: true}).last()).toBeVisible();
    await expect(page.getByText('Fit describes alignment with the rubric', {exact: false})).toBeVisible();
    await page.getByText('role · violated', {exact: true}).click();
    await expect(page.getByText('Evidence p1:', {exact: false})).toContainText('<script>untrusted instructions</script>');
    expect(await page.locator('.job-detail script').count()).toBe(0);
    await page.getByText('Confirmed candidate evidence', {exact: true}).click();
    await expect(page.getByText('fact-python: Built Python APIs.', {exact: true})).toBeVisible();
    await page.getByText('Assessment provenance and usage', {exact: true}).click();
    await expect(page.getByText('Profile revision 3;', {exact: false})).toContainText('effective model jev-1.13.0');
    expect(calls).toBe(1);
    await page.getByRole('button', {name: 'Mark as applied', exact: true}).click();
    await page.getByRole('button', {name: 'Applied', exact: true}).click();
    await expect(page.locator('[data-job]')).toHaveCount(1);
    await expect(page.getByRole('button', {name: 'Evaluate job', exact: true})).toBeDisabled();
    await page.getByRole('button', {name: 'Undo applied', exact: true}).click();
    await expect(page.locator('[data-job]')).toHaveCount(0);
    await page.getByRole('button', {name: 'All jobs', exact: true}).click();
    if (narrow) await page.getByRole('button', {name: '← Back to results', exact: true}).click();
    await page.locator('[data-job]').click();
    state = 'error'; await page.reload(); await page.locator('[data-job]').click();
    await expect(page.getByText('error · provider unavailable', {exact: true})).toBeVisible();
    await page.getByText('Evaluation attempts', {exact: true}).click();
    await expect(page.getByText('Input tokens unknown; output tokens unknown.', {exact: false})).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path: `test-results/t06-assessments-${narrow ? 'mobile' : 'desktop'}.png`, fullPage: true});
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-job]')).toBeFocused();
    expect(calls).toBe(1);
  });
}
