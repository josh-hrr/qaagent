#!/usr/bin/env bash
# Start the web service, and the generation worker alongside it.
#
# Render has no free background worker, so on the free plan both processes live
# in this one service. That is a real trade, not a free one:
#
#   * A free service spins down after 15 minutes without traffic. A run in
#     flight is killed; `reap_runs` below marks it failed on the next start
#     rather than leaving it stuck at "running" forever.
#   * While somebody watches a run the page polls every two seconds, which
#     keeps the service awake — so runs started and watched usually finish.
#
# On a paid plan, move the worker to its own service (see render.yaml) and use
# this script's gunicorn line as the web start command.
set -o errexit
set -o nounset
set -o pipefail

cd backend

# Anything a previous instance left mid-run is failed before we accept traffic.
python manage.py reap_runs

python manage.py db_worker &
WORKER_PID=$!

# If the worker dies, take the service down with it: a web service that looks
# healthy while no run can ever finish is worse than a restart.
trap 'kill "$WORKER_PID" 2>/dev/null || true' EXIT

# One worker: a free instance has 512 MB and is already running the
# generation worker beside gunicorn. Two web workers plus the Anthropic SDK
# is how you get an out-of-memory kill instead of a running service.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:$PORT" \
  --workers 1 \
  --threads 4 \
  --timeout 120
