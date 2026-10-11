import { test as base } from '@playwright/test';

// Workspace feature suites start after onboarding; setup.spec.ts covers the real gate.
export const test = base.extend({
  context: async ({ context }, use) => {
    await context.route('**/api/onboarding', route => route.fulfill({json: {complete: true}}));
    await use(context);
  },
});
export { expect, type Page } from '@playwright/test';
