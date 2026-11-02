import { defineConfig } from '@playwright/test';

const port = process.env.E2E_PORT || '8899';
export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 90_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${port}`,
    viewport: { width: 1000, height: 700 },
    launchOptions: { args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] },
  },
  webServer: {
    command: `${process.env.PYTHON || 'python'} manage.py runserver ${port} --noreload`,
    url: `http://localhost:${port}/`,
    env: { DJANGO_SECRET_KEY: process.env.DJANGO_SECRET_KEY || 'e2e-only-not-a-real-key' },
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
