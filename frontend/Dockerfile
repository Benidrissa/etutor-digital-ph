FROM node:20-alpine AS base

# Stage 1: Install dependencies
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Stage 2: Build
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN mkdir -p public

ARG NEXT_PUBLIC_SENTRY_DSN
ARG SENTRY_ORG
ARG SENTRY_PROJECT
ARG SENTRY_AUTH_TOKEN

# Build via webpack so @serwist/next runs — Next.js 16 defaults to Turbopack,
# which silently skips webpack plugins and ships an image with no /sw.js
# (offline mode dies; see #2113).
RUN npm run build && \
    if [ ! -s public/sw.js ]; then \
      echo "ERROR: @serwist/next did not emit public/sw.js — refusing to ship a PWA without a service worker." >&2; \
      exit 1; \
    fi

# Stage 3: Production
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --chown=nextjs:nodejs docker-entrypoint.sh /app/docker-entrypoint.sh

USER nextjs

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 3000

# Traefik-compatible healthcheck (Node.js-based, NOT wget — wget fails in Alpine)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://localhost:3000/fr/dashboard').then(r => r.status < 500 ? process.exit(0) : process.exit(1)).catch(() => process.exit(1))" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
