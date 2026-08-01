# Security and privacy boundary

Impact Relay is a **public aggregate** publishing surface.

## Must never appear in this repository

- donor or member names
- email addresses, phone numbers, street addresses
- itemized donation amounts tied to a person
- private stewardship notes
- CRM exports, workbooks, PDFs of registries
- service-role keys, API secrets, private tokens

## Allowed content

- aggregate raised / committed totals
- public donor counts
- milestone labels and impact statements
- operational notifications without personal data
- public donation processor links

## Incident response

If personal data is accidentally committed:

1. Remove it in a follow-up commit immediately.
2. Rotate any exposed credentials.
3. Treat historical git history as compromised for that data class and rewrite only with explicit operator approval.
