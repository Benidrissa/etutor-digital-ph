import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
const STAGING_URL =
  process.env.STAGING_URL || 'https://etutor.elearning.portfolio2.kimbetien.com';
const PROD_URL = process.env.PROD_URL || 'https://app.sira-donnia.org';

// Persona projects (#2116) authenticate via auth.setup.ts and load the saved
// storageState file. New specs go under e2e/specs/{persona}/. Old flat specs
// in e2e/*.spec.ts continue to run under chromium/mobile-chrome projects below.
const personaProject = (name: string) => ({
  name,
  testDir: `./e2e/specs/${name}`,
  use: {
    ...devices['Desktop Chrome'],
    baseURL: STAGING_URL,
    storageState: name === '01-anonymous' ? undefined : `./e2e/.auth/${personaToFile(name)}`,
  },
  dependencies: name === '01-anonymous' ? [] : ['setup'],
});

function personaToFile(projectName: string): string {
  // '02-learner' → 'learner.json'; '03-org-owner' → 'org-owner.json'
  return `${projectName.replace(/^\d+-/, '')}.json`;
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { open: 'never' }]],
  timeout: 30_000,

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    // Existing flat specs — unchanged. Keep running against BASE_URL until
    // they're migrated or retired (cleanup follow-up to #2116).
    {
      name: 'chromium',
      testIgnore: ['**/specs/**', '**/smoke/**', '**/auth.setup.ts'],
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'mobile-chrome',
      testIgnore: ['**/specs/**', '**/smoke/**', '**/auth.setup.ts'],
      use: { ...devices['Pixel 5'] },
    },

    // Persona-based suite (#2116). The setup project authenticates each
    // persona via /api/v1/auth/login-password and saves storageState files
    // under e2e/.auth/. Each persona project loads its file so specs start
    // pre-authed. .auth/ is gitignored.
    {
      name: 'setup',
      testMatch: /auth\.setup\.ts$/,
      use: { baseURL: STAGING_URL },
    },
    personaProject('01-anonymous'),
    personaProject('02-learner'),
    personaProject('03-org-owner'),
    personaProject('04-sub-admin'),
    personaProject('05-admin'),

    // Production read-only smoke (#2116-5). Anonymous-only; targets PROD_URL
    // (default https://sira-donnia.org). Run hourly via cron in #2118.
    // Invoke locally with `--project=smoke`. No setup dependency — no auth.
    {
      name: 'smoke',
      testDir: './e2e/smoke',
      use: { ...devices['Desktop Chrome'], baseURL: PROD_URL },
    },
  ],

  webServer:
    process.env.CI || process.env.NO_WEB_SERVER
      ? undefined
      : {
          command: 'npm run dev',
          url: BASE_URL,
          reuseExistingServer: true,
          timeout: 60_000,
        },
});
