#!/bin/sh
set -e
# Patch the baked-in rewrite destination with the runtime BACKEND_URL.
# Next.js bakes process.env.BACKEND_URL into routes-manifest.json at build
# time; if BACKEND_URL was not set during the CI build it defaults to
# http://backend:8000, which collides with same-named services from tenant
# stacks sharing the Traefik proxy network. Patching here at startup lets
# docker-compose supply the correct container name (e.g. etutor-backend)
# without requiring a rebuild. (#1778)
if [ -n "$BACKEND_URL" ]; then
  sed -i "s|http://backend:8000|${BACKEND_URL}|g" /app/.next/routes-manifest.json
fi
exec node server.js "$@"
