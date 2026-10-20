# Hosted testing beta

Target: Railway project `cnvrted-community-testing`, service `communities`, one replica with a 500 MB volume mounted at `/data`. Public HTTPS origin: https://communities-production-003a.up.railway.app

The Docker image copies application code and public catalog data only. It excludes the local database, settings, environment files and `.deployment*` files. This hosted instance starts with fresh profiles, feedback and experiment metrics. API keys are runtime environment variables, never browser values or Git files.

## Access and privacy

Visitors can use the app without creating an account. A signed, HttpOnly, Secure, SameSite browser cookie identifies their private session. Job access and analysis reuse enforce server-side ownership. Feedback and saved profiles are scoped to that session; the catalog of public community sources remains shared. Clearing cookies loses access to those results. This is browser-session isolation, not authenticated account access across devices.

Provider settings and maintenance jobs are disabled for public visitors. The experiment report requires an owner token. The token is entered in the report dialog and held in page memory, not localStorage or a URL. Owner sessions are excluded from experiment reports, including earlier events from the same cookie.

The owner token and deployment origin are kept in the ignored, owner-readable `.deployment-access.json` on the operator's machine. Never commit, screenshot, publish or share that file. Hosted credentials are entered only after explicit approval or by the owner in Railway Variables.

## Usage bounds

Default limits: 12 analysis/recommendation jobs per browser per UTC day, 24 per IP, 120 across the service. One active job per browser, three active jobs globally and two worker threads. A recommendation may make multiple provider calls, so a job cap is not a precise dollar cap. Provider spending limits remain useful. Hashes of IP addresses are used for quotas; raw IPs are not persisted by this app.

The SQLite volume retains catalog updates and experiment metrics between deploys. At startup, private hosted jobs older than seven days are removed, as are expired quota buckets. Restarts mark interrupted jobs failed; users can retry. This beta uses one persistent process, not a durable distributed queue. Background daily discovery is disabled in hosted mode.

## Configuration

Required runtime values:

- `CNVRTED_HOSTED=1`, `PUBLIC_URL` set to the exact HTTPS origin, `PORT=8080`, `CNVRTED_DATA_DIR=/data`.
- `SESSION_SECRET` and `ADMIN_TOKEN`: independent cryptographically random values of at least 32 characters. Preserve them between redeploys.
- `AI_PROVIDER=anthropic`, `AI_MODEL` and `ANTHROPIC_API_KEY` configured privately.
- Optional `GLOBAL_DAILY_JOBS`, `VISITOR_DAILY_JOBS`, `IP_DAILY_JOBS`.

`railway.json` configures the Docker build, `/health` readiness check and a single replica. Do not add replicas against the same SQLite volume. Use a shared database and durable queue before scaling beyond a small beta.

## Verification

Run `python3 -m unittest discover -s app -p 'test_*.py'` and `node --check app/static/app.js`. The 48 tests include session signatures, per-session CSRF, host/origin rejection, private job reads and analysis reuse, feedback isolation, owner-only settings/reporting, quotas, server-owned assignment, and QA exclusion, alongside the original recommendation tests.

After deploying, verify HTTPS health, two independent browser sessions, protected reports/settings, website analysis, recommendations and persisted experiment events. Owner QA requests should use the owner token so they are excluded from decision metrics. Then share only the public origin with participants.
