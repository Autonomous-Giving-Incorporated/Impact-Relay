import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  reporter: 'line',
  use: { baseURL: 'http://127.0.0.1:4174' },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } }
  ],
  webServer: {
    command: 'python3 -m http.server 4174',
    url: 'http://127.0.0.1:4174/index.html',
    reuseExistingServer: true
  }
});
