# AGI suite UI/UX consistency — Impact Relay

**Requirement:** Impact Relay’s public UI must stay visually and interactionally consistent with its companion products in the Autonomously Giving Incorporated suite:

| Product | Repository | Role |
|---|---|---|
| **AGI** | [Autonomous-Giving-Incorporated](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated) | Corporate master brand and explanatory workbench |
| **Fund Intel** | [Fund-Intel](https://github.com/scrimshawlife-ctrl/Fund-Intel) | Decision workspace and campaign operations |
| **Impact Relay** | this repo | Public evidence, ledger truth, and impact receipts |

Information density differs by product job. **Identity, palette, typography, focus, status language, suite navigation, and footer governance must match.** Do not invent a separate brand for this repository.

Canonical public origins use the `autogive.app` family:

- AGI home: `https://autogive.app/`
- Fund Intel: `https://autogive.app/fund-intel/`
- Impact Relay: `https://autogive.app/impact-relay/`

## Source of truth

| Concern | Owner / reference |
|---|---|
| Shared visual grammar | AGI [`docs/DESIGN_SYSTEM.md`](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/docs/DESIGN_SYSTEM.md) and AGI [`tokens.css`](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/tokens.css) (public reference values) |
| Suite identity + decision-workspace shell | Fund Intel [`docs/AGI-DESIGN-SYSTEM.md`](https://github.com/scrimshawlife-ctrl/Fund-Intel/blob/main/docs/AGI-DESIGN-SYSTEM.md) and [`docs/BRAND-SYSTEM.md`](https://github.com/scrimshawlife-ctrl/Fund-Intel/blob/main/docs/BRAND-SYSTEM.md) |
| Cross-repo navigation and token coherence | AGI [`docs/THREE_REPO_INTEGRATION.md`](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/docs/THREE_REPO_INTEGRATION.md) § D |
| Impact Relay product layout (evidence-led IA) | [`design.md`](../design.md) |
| Impact Relay implementation tokens | [`tokens.css`](../tokens.css) → consumed by [`styles.css`](../styles.css) |
| Visual QA baseline | [`design-qa.md`](../design-qa.md) |

When AGI or Fund Intel change shared primitives, update Impact Relay tokens, masthead/footer, and this document in the same delivery window. Prefer aliasing shared values over local one-off colors.

## Shared primitives

These values must match AGI / Fund Intel:

- Paper `#f7f8fa`, white surface `#ffffff`, cool gray `#e6e9ec`
- Ink `#0e1116`, graphite `#1f232b`, muted copy derived from graphite
- AGI gold `#e6b23c` (attention / focus); AGI green `#2e7d6b`; mint `#a5cbb8`
- Success / verified → deep teal; warning → `#6a5200`; danger → `#a83232`
- **Space Grotesk** display, **Inter** body/interface, **IBM Plex Mono** metadata
- Controls: 2px corners; structural surfaces: 4px corners; **no decorative shadows or gradients**

In this repo, canonical custom properties use the `--agi-` prefix in `tokens.css`. Local `--color-*` / `--font-*` aliases map to those properties so product CSS never invents an unrelated palette.

## Identity hierarchy

Masthead order is fixed:

1. AGI mark and wordmark (`assets/brand/agi-wordmark.png`, `agi-mark.png`)
2. Impact Relay product name and **Public Evidence** role
3. Tenant / campaign context (e.g. Hacker Dojo) — context only, never replaces AGI or product identity

Required suite links (reciprocal):

- AGI → `https://autogive.app/`
- Fund Intel → `https://autogive.app/fund-intel/`
- Sign-in (when shown) → Fund Intel workspace, not a separate auth brand

Footer always includes:

- AGI + product identity
- Tokens, Logo use, Legal (`autogive.app/brand#…`, `autogive.app/legal`)
- **“Software by Zero State”** as footer-only builder credit (not a masthead brand)

## Interaction and status rules

- Visible keyboard focus is mandatory (`--color-focus` / gold).
- Primary actions use carbon/ink; gold is reserved for attention, focus rings, and primary-button edge treatment.
- Deep teal marks verified state and suite navigation links.
- Status color is never the only signal — labels remain explicit text.
- Shared state language: loading, empty, error, blocked, waiting, verified.
- Tables and evidence records remain usable on narrow screens; authority and provenance stay visible.
- Donation and evidence actions retain campaign, provenance, and authority context in the UI.
- Respect `prefers-reduced-motion` for nonessential transitions.

## What may differ (product job, not brand)

Impact Relay remains **evidence-led and stat-first**, not a decision dashboard:

| Layer | Impact Relay | Fund Intel | AGI |
|---|---|---|---|
| Primary job | Public proof of raised funds, milestones, evidence, use-of-funds, impact | Campaign decisions and authenticated ops | Corporate narrative + suite entry |
| IA | Stat hero → milestones → evidence → digests → UOF → feed → privacy | Metrics, decisions, pipelines, controls | Lifecycle / proof narrative |
| Density | Compact ledger rows, thin rules | Operational tables and workspaces | Restrained paper + graphite proof |
| Tenant chrome | Campaign label only | Optional HD tenant tokens for campaign emphasis only | None |

Do **not**:

- Use decorative eyebrows on every section
- Add thick severity rails, equal four-up marketing grids, or invented metrics
- Replace AGI identity with tenant or Zero State branding in the masthead
- Publish donor PII or imply live payments / one-to-one attribution without authority
- Drift fonts (e.g. Georgia) or warm-paper palettes from older drafts

## Implementation checklist (this repo)

When changing public UI:

1. Read AGI design system + this file; keep `--agi-*` values in lockstep with siblings.
2. Preserve identity hierarchy and reciprocal suite links on every public surface.
3. Keep status text + color together; keep empty/pilot banners honest about provenance.
4. Verify narrow viewport: no hidden Donate / Evidence authority context.
5. Footer governance links and Zero State credit unchanged.
6. Update `design-qa.md` if visual acceptance criteria change.
7. Host-owned finance/donor screens live in the Fund Intel / Hacker Dojo host app — those screens must reuse the same AGI shell rules when they surface Impact Relay data.

## Visual pass notes (2026-08-03)

Public Impact Relay Pages (`index.html` + `tokens.css` / `styles.css`) already follow the shared AGI foundation: wordmark lockup, suite links, gold focus, green suite chrome, footer governance.

**Host app gaps (Fund Intel / campaign host — out of this repo’s merge scope, tracked for suite coherence):**

| Surface | Tokens | AGI lockup / suite nav | Footer governance |
|---|---|---|---|
| Fund Intel `workspace.html` | yes | partial (tenant-forward after auth) | auth gate yes |
| Fund Intel `finance-impact.html` | yes (via `styles.css`) | no AGI masthead; eyebrow-only “IMPACT RELAY · FINANCE” | missing Tokens / Logo / Legal / Zero State |
| Fund Intel `donor-impact.html` | yes | no AGI masthead; eyebrow-only “IMPACT RELAY · DONOR” | missing |
| Fund Intel public `index.html` (static fallback) | yes | may lag `app.js` branded shell | verify on deploy |

When those host screens are next touched, apply the same identity hierarchy and footer contract as Impact Relay public Pages and Fund Intel workspace auth gate. Do not block Impact Relay library releases on host chrome gaps.

## Related docs

- [`design.md`](../design.md) — Impact Relay public surface layout and guardrails
- [`design-qa.md`](../design-qa.md) — latest visual QA receipt
- [`../CLAUDE.md`](../CLAUDE.md) — contributor rules (points here for UI work)
- Fund Intel suite architecture: [AGI-SUITE-ARCHITECTURE.md](https://github.com/scrimshawlife-ctrl/Fund-Intel/blob/main/docs/AGI-SUITE-ARCHITECTURE.md)
- AGI three-repo surface: [THREE_REPO_INTEGRATION.md](https://github.com/scrimshawlife-ctrl/Autonomous-Giving-Incorporated/blob/main/docs/THREE_REPO_INTEGRATION.md)

---

Last updated: 2026-08-03
