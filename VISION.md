# Impact Relay Vision

Donors should not have to wonder what happened after they gave.

Impact Relay is donor-impact middleware that connects a donation to its approved allocation, connects that allocation to actual expenditures, and connects those expenditures to verified programs and outcomes. It then returns that evidence to the donor through a clear receipt and their chosen communication channel.

## The problem

Most donation systems stop at payment confirmation. Accounting systems record expenditures, program tools record activities, and communication tools send newsletters, but those systems rarely produce a trustworthy donor-level explanation of:

- what the organization used the money for;
- how the expenditure related to the donor's allocation;
- what the expenditure subsequently enabled;
- whether the information was verified;
- whether a later correction changed the original claim.

## The product promise

Impact Relay provides two linked transparency artifacts:

1. **Use-of-funds receipt** — what was purchased or paid for, when, for how much, from which allocation, under which attribution method, and with what verification.
2. **Impact receipt** — what that expenditure or funded asset later enabled, such as a class held, equipment used, or a verified program milestone.

## Example

A donor contributes $1,000 to a community hardware fund.

- The donation is cleared and assigned to the fund.
- Finance approves a $720 purchase of robotics kits.
- Impact Relay records the expense, evidence, allocation, and attribution method.
- The donor receives a use-of-funds receipt explaining the purchase and their attributed share.
- When the kits are used in a verified community class, the donor receives an impact receipt.
- If the vendor later issues a refund, the original receipt remains visible and a correction receipt records the revised amount.

## Trust boundary

Impact Relay does not invent financial truth or outcomes.

- Financial systems and authorized staff provide source facts.
- Deterministic domain rules enforce money invariants.
- Agents collect evidence and propose bounded actions.
- Authorized humans approve consequential actions.
- Append-only receipts preserve provenance and correction history.

## Reference deployment

Hacker Dojo is the first reference deployment. The initial pilot focuses on a restricted hardware or community-class allocation and validates the full path from expenditure review to donor notification.

## Long-term direction

Impact Relay should become reusable infrastructure for nonprofits, makerspaces, educational programs, fiscal sponsors, and civic organizations that want to provide credible, consent-aware transparency without exposing donor PII or automating away financial accountability.