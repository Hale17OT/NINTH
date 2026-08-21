# NINTH authentication and account deployment

NINTH now uses PostgreSQL for application accounts, server-managed sessions, preferences, and user-owned saved content. The sports/model datasets remain in their existing stores; account data is intentionally separate.

## Architecture

- Vue 3 + Pinia owns client authentication state and restores `/api/auth/me` before mounting the application.
- Express owns authentication and authorization. Protected APIs derive ownership only from the resolved session.
- Prisma manages PostgreSQL schema and additive migrations under `server/prisma/migrations`.
- Passwords use Argon2id. Browser cookies contain only opaque random session tokens; PostgreSQL stores their SHA-256 hashes.
- Google uses Authorization Code flow with PKCE, state expiry, exact redirect URIs, and only `openid email profile` scopes.
- Verification, password-reset, and OAuth-state tokens are random, short-lived, hashed at rest, and single-use.
- Email is behind `server/src/services/email/emailService.js`, so Gmail SMTP can be replaced without changing auth logic.

## Local setup

1. Copy `.env.example` to the ignored `.env` and replace placeholders.
2. Run `npm install`.
3. Start the bundled local PostgreSQL cluster with `npm run auth:db:up`. It listens on `127.0.0.1:54329` only.
4. Run `npm run auth:generate` and `npm run auth:migrate`.
5. Build and start the normal stack with `npm run build` and `npm start`.

`docker compose -f docker-compose.auth.yml up -d` is an optional local alternative. Do not use its development password in production.

To create optional development data, set `DEV_SEED_EMAIL` and `DEV_SEED_PASSWORD` only in `.env`, then run `npm run auth:seed`. Seeding refuses to run when `NODE_ENV=production`.

Existing local PDF and Alter Ego files are preserved. After the intended owner has registered, set `LEGACY_OWNER_EMAIL` and run `npm run auth:migrate:legacy`. The import is additive and idempotent; it never deletes or rewrites the source files.

## Public and protected route matrix

| Area | Guest access | API enforcement |
| --- | --- | --- |
| Home, schedules, teams, players, matchups | Public | Read-only public endpoints |
| Daily model performance | Public | Read-only `/api/model*` |
| Build Best 5 (`/builder`) | Public | Public model inputs |
| Advanced builders (`/build`, sport builders, props builder) | Account required | Session + CSRF for generated/saved writes |
| Saved predictions/builders/slips | Account required | Every query includes authenticated `userId` |
| Tracked slips and Alter Ego | Account required | PostgreSQL owner scope; legacy global files are not exposed |
| Account/profile/preferences/security | Account required | Session + CSRF for mutations |
| Sign in, sign up, forgot/reset/verify | Guest flow | Rate limited and schema validated |

The router preserves a safe internal `returnTo` target. External, protocol-relative, credential-bearing, and malformed redirects resolve to `/`.

## Google Cloud setup

Create an OAuth 2.0 **Web application** client in Google Cloud and configure the consent screen. Add only these local values:

- Authorized JavaScript origin: `http://localhost:5173`
- Authorized redirect URI: `http://localhost:3001/api/auth/google/callback`

For production, add the exact HTTPS frontend origin and exact HTTPS backend callback. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` in the deployment secret store. Google credentials are unrelated to a Gmail app password.

## Email setup

For temporary Gmail SMTP delivery, use port `465`, `SMTP_SECURE=true`, the complete Gmail address in `SMTP_USER`, and the Gmail app password in `SMTP_PASSWORD`. `SMTP_FROM` should use the same authenticated mailbox unless the account is configured for another sender.

Never commit an app password. Put it only in the ignored `.env` for local use and in the host's encrypted secret manager for deployment. A production transactional provider can replace Gmail by changing these environment variables or the email adapter.

## Production checklist

- Use managed PostgreSQL with TLS, backups, a restricted application role, connection pooling, and `DATABASE_URL` supplied as a secret.
- Set `NODE_ENV=production`, HTTPS `FRONTEND_URL`, `BACKEND_URL`, and `APP_URL`, plus an exact comma-separated `TRUSTED_FRONTEND_ORIGINS` list.
- Generate a unique 32+ character `SESSION_SECRET`; never reuse the development default.
- Keep `AUTH_COOKIE_SECURE=true` and `AUTH_COOKIE_SAME_SITE=lax` unless a reviewed cross-site deployment requires another policy.
- Run `npm ci`, `npm run auth:generate`, `npm run auth:migrate`, and `npm run build` before starting the server.
- Configure the reverse proxy to preserve HTTPS, pass the correct origin, and route `/api` to Express. The server trusts one proxy hop in production.
- Configure the production Google callback and SMTP or transactional-email secrets.
- Run `npm run test:auth` against a disposable test database before deployment.

## Security controls

NINTH includes HttpOnly/Secure production session cookies, CSRF double-submit validation plus trusted-origin checks, restricted credentialed CORS, Helmet security headers and CSP, input validation, generic password-login failures, neutral forgot-password responses, hashed sensitive tokens, absolute and idle session expiry, session revocation, sanitized logs, rate limits, safe redirects, server-owned resource IDs, and cross-user authorization tests.

The database schema is structured around indexed `userId` foreign keys so PostgreSQL Row-Level Security can be added later as defense in depth. Express ownership checks remain mandatory even if RLS is introduced.

## Verification commands

```powershell
npm run test:auth
npm run build
node --test server/src/domain/*.test.js server/src/services/*.test.js
node --test src/domain/*.test.js src/services/*.test.js
```

The auth test command automatically creates and migrates `ninth_test`; it never points at the development `ninth` database.
