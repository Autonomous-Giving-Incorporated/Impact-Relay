# Design QA — Impact Relay

- Reference: supplied AGI brand board (`codex-clipboard-7b0a155b-424e-4f90-a4c2-7af6e0bd2174.png`)
- Suite contract: [`docs/AGI-DESIGN-SYSTEM.md`](docs/AGI-DESIGN-SYSTEM.md) (must remain coherent with AGI + Portfolio Signals)
- Implementation: `http://127.0.0.1:8082/index.html`
- Viewport: 1280 × 720
- Comparison artifact: `/private/tmp/impact-qa.png`

## Review

- P0: none
- P1: none
- P2: none
- Identity: AGI is the persistent master brand, Impact Relay is the product, and Hacker Dojo remains campaign context.
- Tokens and type: the evidence-led interface uses the shared AGI palette, Space Grotesk display, and Inter interface typography (aligned with AGI `tokens.css` and Portfolio Signals shell).
- Navigation: reciprocal product links use the `autogive.app` route family (AGI, Portfolio Signals, Impact Relay).
- Builder attribution: Zero State appears only in the legal footer beside Tokens, Logo use, and Legal.
- Public onboarding handoff: the visible CTA remains in the AGI evidence shell, uses the shared
  primary-action treatment, and pairs with keyboard-operable native `details` / `summary` help.
- Narrow viewport: the onboarding handoff collapses to one column without horizontal overflow.

final result: passed

Playwright loaded the prefixed production asset paths and public JSON successfully in Chromium on
desktop and Pixel 7 viewports. All 22 browser cases passed, including expanded-help axe scans,
keyboard Tab/Enter interaction, exact intercepted handoff navigation, and response/console failure
guards. Screenshots are written beneath Playwright's repository-relative `test-results/`
output directories as `onboarding-desktop-chromium.png` and `onboarding-mobile-chromium.png`.
The external handoff is intercepted for navigation assertions, not a live login/activation test.
