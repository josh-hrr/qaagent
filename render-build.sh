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
  # a per-platform optional dependency. npm can skip those (npm/cli#4828), and
  # it fails late and confusingly: "Cannot find native binding", only on Linux.
  #
  # Test for the BINARY, not the directory — npm leaves the package folder in
  # place while the .node file inside is missing, which is what defeated the
  # first attempt at this.
  BINDING="node_modules/@rolldown/binding-linux-x64-gnu/rolldown-binding.linux-x64-gnu.node"

  npm ci --include=optional --no-audit --no-fund

  if [ ! -f "$BINDING" ]; then
    echo "--- rolldown's linux binary is missing; installing it explicitly"
    ROLLDOWN_VERSION="$(node -p "require('./node_modules/rolldown/package.json').version")"
    npm install --no-save --include=optional --no-audit --no-fund \
      "@rolldown/binding-linux-x64-gnu@${ROLLDOWN_VERSION}" || true
  fi

  if [ ! -f "$BINDING" ]; then
    echo "--- still missing; reinstalling from scratch, as npm itself suggests"
    rm -rf node_modules package-lock.json
    npm install --include=optional --no-audit --no-fund
  fi

  if [ ! -f "$BINDING" ]; then
    echo "!!! rolldown has no linux binary after three attempts:"
    ls -la node_modules/@rolldown/ || true
    exit 1
  fi

  echo "--- rolldown binary present, compiling"
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
