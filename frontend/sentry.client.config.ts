import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,
  tracesSampleRate: 0.2,

  // Disable session replay (privacy + bundle size)
  replaysSessionSampleRate: 0,
  replaysOnErrorSampleRate: 0,

  // GDPR: no PII
  sendDefaultPii: false,

  beforeSend(event) {
    if (event.user) {
      delete event.user.ip_address;
      delete event.user.email;
    }
    return event;
  },
});
