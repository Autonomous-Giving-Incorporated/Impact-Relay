import { test as base, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const ONBOARDING_URL =
  'https://autogive.app/fund-intel/workspace?onboarding=impact-relay';

const test = base.extend({
  page: async ({ page }, use) => {
    const failures = [];
    page.on('console', message => {
      if (message.type() === 'error') failures.push(`console: ${message.text()}`);
    });
    page.on('requestfailed', request => failures.push(`request: ${request.url()}`));
    page.on('response', response => {
      if (!response.ok()) failures.push(`response ${response.status()}: ${response.url()}`);
    });
    await use(page);
    expect(failures).toEqual([]);
  }
});

test('offers a read-only handoff to organization setup', async ({ page }) => {
  await page.goto('index.html');

  const handoff = page.getByRole('link', { name: 'Set up your organization' });
  await expect(handoff).toBeVisible();
  await expect(handoff).toHaveAttribute('href', ONBOARDING_URL);
  await expect(handoff).not.toHaveAttribute('target', '_blank');
  await expect(handoff).toHaveAttribute('rel', 'noreferrer');
  await expect(handoff).toHaveAttribute('referrerpolicy', 'no-referrer');

  const guide = page.getByRole('group', { name: 'How organization setup works' });
  await expect(guide).toBeVisible();
  await expect(guide.locator('summary')).toBeVisible();
  await expect(guide).toContainText('Sign in or create an operator account');
  await expect(guide).toContainText('Choose or request access to your organization');
  await expect(guide).toContainText('Review readiness in the Fund Intelligence workspace');
  await expect(guide).toContainText('This public site cannot bootstrap a runtime');
});

test('forwards one literal valid tenant and nothing else', async ({ page }) => {
  await page.goto(
    'index.html?tenant=org_example_2&token=secret&session=private&next=https://evil.example/#access_token=fragment'
  );

  await expect(page.getByRole('link', { name: 'Set up your organization' })).toHaveAttribute(
    'href',
    `${ONBOARDING_URL}&tenant=org_example_2`
  );
});

for (const [label, query] of [
  ['duplicate', '?tenant=org_one&tenant=org_two'],
  ['uppercase', '?tenant=org_Example'],
  ['encoded normalization', '?tenant=%6Frg_example'],
  ['empty suffix', '?tenant=org_'],
  ['punctuation', '?tenant=org_example-2'],
  ['too long', `?tenant=org_${'a'.repeat(125)}`]
]) {
  test(`rejects ${label} tenant input`, async ({ page }) => {
    await page.goto(`index.html${query}`);
    await expect(page.getByRole('link', { name: 'Set up your organization' })).toHaveAttribute(
      'href',
      ONBOARDING_URL
    );
  });
}

test('setup help is keyboard operable and the public page performs no mutations', async ({ page }, testInfo) => {
  const requests = [];
  page.on('request', request => requests.push({ method: request.method(), url: request.url() }));

  await page.goto('index.html');
  const summary = page.locator('.onboarding-handoff summary');
  await page.locator('body').focus();
  for (let tabs = 0; tabs < 20 && await page.evaluate(() => document.activeElement?.tagName !== 'SUMMARY'); tabs += 1) {
    await page.keyboard.press('Tab');
  }
  await expect(summary).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('.onboarding-handoff details')).toHaveAttribute('open', '');

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter(item => ['serious', 'critical'].includes(item.impact))).toEqual([]);

  const screenshot = testInfo.outputPath(`onboarding-${testInfo.project.name}.png`);
  await page.screenshot({ path: screenshot, fullPage: true });

  expect(requests.filter(request => request.method !== 'GET')).toEqual([]);
  expect(requests.some(request => /(?:tenant|client).*(?:registry|list)/i.test(request.url))).toBe(false);
  expect(requests.some(request => /\/api\//.test(new URL(request.url).pathname))).toBe(false);
});

test('keyboard activation reaches only the exact external handoff', async ({ page, context }) => {
  let navigation;
  await page.route('https://autogive.app/**', async route => {
    navigation = route.request();
    await route.fulfill({
      contentType: 'text/html',
      body: '<!doctype html><title>Captured handoff</title><p id="opener"></p><script>document.getElementById("opener").textContent = String(window.opener)</script>'
    });
  });
  await page.goto('index.html?tenant=org_example_2&token=secret#access_token=fragment');

  const handoff = page.getByRole('link', { name: 'Set up your organization' });
  await page.locator('body').focus();
  for (let tabs = 0; tabs < 20 && !(await handoff.evaluate(node => node === document.activeElement)); tabs += 1) {
    await page.keyboard.press('Tab');
  }
  await expect(handoff).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(`${ONBOARDING_URL}&tenant=org_example_2`);

  expect(navigation.url()).toBe(`${ONBOARDING_URL}&tenant=org_example_2`);
  expect(navigation.headers().referer).toBeUndefined();
  expect(navigation.url()).not.toMatch(/token|session|fragment|evil/i);
  expect(context.pages()).toHaveLength(1);
  await expect(page.locator('#opener')).toHaveText('null');
});

test('public Impact Relay remains responsive and accessible', async ({ page }) => {
  await page.goto('index.html');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.locator('.suite-brand')).toContainText('AGI product');
  await expect(page.locator('.suite-brand')).toContainText('Impact Relay');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
  const results = await new AxeBuilder({ page }).analyze();
  const severe = results.violations.filter(item => ['serious', 'critical'].includes(item.impact));
  expect(severe).toEqual([]);
});
