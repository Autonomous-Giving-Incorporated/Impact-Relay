# Public guided onboarding handoff

Impact Relay's public evidence site is read-only. It may explain organization setup and hand an
operator to the authenticated Fund Intelligence workspace, but it does not discover, list, create,
or mutate tenants. It does not run an onboarding wizard.

## Shared authentication and handoff contract

The canonical handoff is:

```text
https://autogive.app/fund-intel/workspace?onboarding=impact-relay
```

Authentication and organization authorization belong to the destination workspace. The public
site sends no credential, token, session value, hash fragment, referrer, opener relationship, or
arbitrary incoming parameter. The link opens in the same tab and carries `rel="noreferrer"` plus
`referrerpolicy="no-referrer"`.

One optional tenant hint may be copied from the public page's incoming query string under the
literal key `tenant`. It is accepted only when there is exactly one raw `tenant` field and its raw
value matches the anchored ASCII expression `^org_[a-z0-9_]+$` with a maximum total length of 128
characters. The site does not trim, case-fold, decode, repair, or otherwise normalize that value.
Duplicate, encoded, empty, overlength, or malformed values are rejected. A rejected or absent hint
produces the canonical URL unchanged; an accepted hint produces only:

```text
https://autogive.app/fund-intel/workspace?onboarding=impact-relay&tenant=org_example
```

The hint is not proof of membership and must never bypass workspace authentication or tenant
authorization.

## Readiness boundary

This handoff is guidance, not activation. It never changes `runtime_ready`,
`operational`, or any readiness receipt. This public site cannot bootstrap a runtime;
no ledger, connector, worker, delivery, or publication capability becomes operational
from visiting or following this link. Existing human and policy gates are unchanged.
The FI source entrypoint `workers/portfolio-signals/src/bootstrap.js` is explicitly
read-only and denies non-GET/HEAD requests; this source observation is not a claim
about which Worker version is deployed. Live runtime activation was not tested.

The coordinated FI consumer (`workspace/onboarding-intent.js` and
`tests/workspace-onboarding-intent.test.mjs` in the FI shared-onboarding change)
accepts `onboarding=impact-relay` and `tenant=org_*` at
`/portfolio-signals/workspace`. The legacy `/fund-intel/workspace` alias below
reaches that same route. Tenant hints remain non-authoritative until the
workspace matches them against authenticated organization context.

## Language convention

The public site is currently static and English-only. Onboarding copy therefore lives centrally in
`index.html` with the rest of the public English interface; no separate runtime string catalog or
localization path is introduced by this handoff.

## Suite route evidence

Read-only inspection of
`Autonomous-Giving-Incorporated/workers/suite-routes.ts` from the immutable GitHub blob
`3be399456de20bdee6938661586f5176486456a1` shows:

- `/fund-intel` and `/fund-intel/*` return a 301 path redirect to `/portfolio-signals` and the
  corresponding suffix;
- `/portfolio-signals/workspace` maps to the Portfolio Signals upstream `/workspace.html`;
- the gateway retains the request query string across its redirect; URL fragments never reach the
  server;
- this is edge routing, not an Impact Relay or AGI onboarding backend.

The blob was retrieved read-only through the GitHub API on 2026-09-09. No sibling repository was
modified.

## Acceptance matrix

| Case | Expected result |
|---|---|
| No `tenant` | Canonical handoff only |
| One literal `tenant=org_example_2` | Append only that tenant hint |
| Duplicate `tenant` | Reject both; canonical handoff only |
| Uppercase, punctuation, empty suffix, or over 128 characters | Reject; canonical handoff only |
| Percent-encoded tenant text | Reject without normalization |
| Tokens, sessions, redirects, unrelated query fields, or fragment | Never transfer |
| Link interaction | Same tab; no referrer or opener transfer |
| Help interaction | Native visible `details` / `summary`, keyboard operable |
| Page network | Existing public aggregate GETs only; no tenant registry/list or mutation request |
| Workspace readiness | Not established by this handoff; no runtime bootstrap or activation |
