#!/usr/bin/env bash
# Build for Render. Called by both services in render.yaml.
#
#   ./render-build.sh                 web: frontend + backend
#   ./render-build.sh --backend-only  worker: no frontend to serve
set -o errexit
set -o nounset
set -o pipefail

BACKEND_ONLY="${1:-}"

if [ "$BACKEND_ONLY" != "--backend-only" ]; then
  echo "--- building the frontend"
  cd frontend

  # Vite 8 builds with rolldown, whose compiler is a native binary published as
  # a per-platform optional dependency. The lockfile lists every platform, but
  # `npm ci` can still skip optional packages (npm/cli#4828) — and the failure
  # only shows up on Linux, as "Cannot find native binding", long after the
  # install looked fine. So: install, then prove the binary is actually there,
  # and rebuild from scratch the way npm itself recommends if it is not.
  npm ci --include=optional --no-audit --no-fund

  if [ ! -d node_modules/@rolldown/binding-linux-x64-gnu ]; then
    echo "--- rolldown's linux binding is missing; reinstalling without the lockfile"
    rm -rf node_modules package-lock.json
    npm install --include=optional --no-audit --no-fund
  fi

  npm run build
  cd ..
fi

echo "--- installing python dependencies"
pip install --no-cache-dir -r backend/requirements.txt

cd backend

if [ "$BACKEND_ONLY" != "--backend-only" ]; then
  # Collects Django's admin files and the Vite build together. The frontend's
  # asset URLs already point at /static/, set by vite.config.ts at build time.
  echo "--- collecting static files"
  python manage.py collectstatic --no-input
fi

# Migrations run in the build so a failed migration fails the deploy, rather
# than leaving a started service talking to a half-migrated database.
echo "--- applying migrations"
python manage.py migrate --no-input

# Refuses to continue on a default secret key or a missing encryption key.
echo "--- deployment checks"
python manage.py check --deploy --fail-level ERROR
