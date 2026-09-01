# Security

## Reporting a vulnerability

Report privately at
<https://github.com/myrrym/places-stories-api/security/advisories/new>. Please
do not open a public issue for a vulnerability.

Expect an acknowledgement within a week. This is a personal open-source
project, not a funded one, so there is no bug bounty and no formal SLA — but
reports are taken seriously and credited unless you would rather not be.

## Scope

The API is read-only and unauthenticated: there are no user accounts, no
sessions, no write endpoints and no personal data in the database. The things
worth reporting are therefore:

- SQL injection or any other way to reach the database outside the intended
  queries
- A way to bypass the per-IP rate limiter, including spoofing
  `X-Forwarded-For` past the trusted-proxy check
- Cache poisoning: making one client's proximity query serve another client
  wrong or unauthorised data
- Resource exhaustion through crafted query parameters
- Secrets committed to the repository or baked into the published image

Out of scope: findings against a deployment you do not control, volumetric
denial of service, and reports that a public read-only API is publicly
readable.

## Deployment notes

If you run your own instance:

- Set a real `POSTGRES_PASSWORD` in `.env`. The value in `.env.example` is a
  placeholder for local development only.
- Set `TRUSTED_PROXY_CIDRS` to your reverse proxy's range, and nothing wider.
  Leaving it empty is safe (the peer address is used); setting it too wide lets
  clients spoof their IP past the rate limiter.
- Do not publish the `db` and `cache` ports. The compose file publishes them on
  55432 and 56379 for local development convenience; remove those mappings in
  any deployment reachable from the internet.
