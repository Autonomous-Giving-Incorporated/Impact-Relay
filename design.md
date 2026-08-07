# Design — Impact Relay public evidence surface

Impact Relay is the public proof layer of the **AGI suite** (Autonomously Giving Incorporated). It keeps an evidence-led, stat-first information architecture while adopting the **shared corporate brand foundation** used by AGI and Portfolio Signals.

**Suite UI/UX is not optional.** Identity, palette, type, focus, status language, suite navigation, and footer governance must stay consistent with the companion repos. Product-specific layout and density may differ; branding may not. Full contract: [`docs/AGI-DESIGN-SYSTEM.md`](docs/AGI-DESIGN-SYSTEM.md).

## Visual direction (shared AGI foundation)

- Paper `#f7f8fa`, white surface `#ffffff`, cool gray `#e6e9ec`
- Ink `#0e1116`, graphite `#1f232b`, muted derived from graphite
- AGI gold `#e6b23c` for attention and focus; AGI green `#2e7d6b` / mint for verified and suite links
- Success/verified deep teal; warning `#6a5200`; danger `#a83232`
- **Space Grotesk** display, **Inter** body, **IBM Plex Mono** metadata
- Thin rules, 2px control / 4px surface corners, no decorative shadows or gradients

Implementation: `tokens.css` (`--agi-*` primitives + local aliases) → `styles.css`. Do not reintroduce legacy warm-paper / Georgia treatments.

## Information architecture (Impact Relay–specific)

1. Campaign stat-led hero and raised-funds provenance
2. Milestone ladder
3. Public evidence, including 990 records and history
4. Event digests
5. Impact outcomes
6. Use-of-funds receipts
7. Notification feed
8. Privacy boundary

## Identity and actions

The masthead reads **AGI → Impact Relay → campaign context** and provides reciprocal links to AGI and Portfolio Signals (`autogive.app`). The primary Donate action uses AGI ink with a gold edge; suite navigation uses AGI green. The footer repeats the AGI mark and product identity, then credits “Software by Zero State” beside Tokens, Logo use, and Legal.

## Guardrails

- Do not use decorative eyebrows on every section.
- Do not add thick severity rails, equal four-up dashboard grids, or invented metrics.
- Status and provenance must remain explicit in text.
- Public evidence and donation controls must work at narrow viewports without hiding authority context.
- Never replace AGI identity with tenant or builder branding in the masthead.
- When shared suite tokens change in AGI or Portfolio Signals, update this surface in the same change window.

## QA

Visual acceptance against the AGI brand board is recorded in [`design-qa.md`](design-qa.md).
