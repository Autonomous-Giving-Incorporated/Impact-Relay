import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('public Impact Relay remains responsive and accessible', async ({ page }) => {
  await page.goto('/index.html');
  await expect(page.locator('main')).toBeVisible();
  await expect(page.locator('.suite-brand')).toContainText('AGI product');
  await expect(page.locator('.suite-brand')).toContainText('Impact Relay');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
  const results = await new AxeBuilder({ page }).analyze();
  const severe = results.violations.filter(item => ['serious', 'critical'].includes(item.impact));
  expect(severe).toEqual([]);
});
