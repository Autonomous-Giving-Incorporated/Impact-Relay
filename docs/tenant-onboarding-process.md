# Unified Tenant Onboarding Process for autogive.app Suite

This document describes the complete web-based tenant onboarding process that integrates both the Fund-Intel/Portfolio Signals (frontend/client) and Impact Relay (backend/tenant) systems.

## Overview

The autogive.app suite consists of:
- **Portfolio Signals (Fund-Intel)**: Frontend workspace for client management, branding, and configuration
- **Impact Relay**: Backend donor-impact transparency ledger and workflow engine

Both systems must be onboarded in sync for a new nonprofit tenant, using the shared identifier contract: `client_id` (FI) == `tenant_id` (IR).

## Prerequisites

1. **Operator Access**: Master admin with MFA-enabled session in Portfolio Signals workspace
2. **Impact Relay Availability**: Local checkout or accessible package for tenant cloning
3. **Supabase Platform**: Active project at `utdioxwiskzatwoejgiu` (or target environment)
4. **Synthetic Tenant ID**: Choose format `org_[a-z0-9_]+` (e.g., `org_community_arts`)

## Complete Onboarding Flow

### Phase 1: Portfolio Signals Client Setup (Frontend)

#### Step 1: Access Workspace
1. Navigate to: https://autogive.app/portfolio-signals/workspace
2. Sign in with MFA-enabled master admin account
3. Verify you see the master admin dashboard

#### Step 2: Provision New Client
1. In workspace header, click client context dropdown → **"Manage Clients"**
2. Click **"+ New Client"** button
3. Fill in client details:
   - **Client ID**: `org_your_organization` (must match Impact Relay tenant_id)
   - **Slug**: `your-organization` (URL-friendly identifier)
   - **Display Name**: "Your Organization Name"
   - **Initial Director UUID**: [Auto-filled from current user or select]
4. Click **"Provision Client"**
5. Wait for provisioning completion (shows spinner → success toast)

#### Step 3: Director Setup (if separate user)
*Skip if using same user as master admin*
1. Invite director user via workspace → Settings → Team → "Invite Member"
2. Director completes email verification and sets up password
3. Director enrolls MFA (TOTP) in Supabase Auth
4. Operator runs: `./scripts/platform/set-mfa-enforced.sql` for director's user ID
5. Director signs in to workspace with MFA

#### Step 4: Brand & Content Configuration
1. With client context selected (top header), navigate to **Brand & Content**
2. Enable at least one fundraising module (toggle switches)
3. Upload initial brand assets:
   - Logo (PNG/SVG/JPG/WebP, max 25MB)
   - Brand colors (optional)
   - Favicon (optional)
4. Click **"Publish Configuration"**
5. Wait for deployment confirmation

#### Step 5: Client Activation
1. Still in Brand & Content tab, click **"Activate Client"** button
2. Confirm activation in modal dialog
3. Wait for activation (shows progress → success)
4. Verify client state shows `active = true` in client context dropdown

### Phase 2: Impact Relay Tenant Setup (Backend)

#### Step 1: Prepare Environment
1. Ensure Impact Relay repository is available locally
2. Create tenant-specific data directory:
   ```bash
   mkdir -p ./data/org_your_organization
   ```
3. Verify Python environment:
   ```bash
   source .venv/bin/activate  # if using virtualenv
   python -c "import impact_relay; print('Impact Relay available')"
   ```

#### Step 2: Clone Tenant Policy
Execute the tenant cloning script:
```bash
python -c "
from pathlib import Path
from impact_relay.storage.template import clone_tenant_from_hacker_dojo
from impact_relay.storage import open_storage

# Use tenant-specific data directory
store = open_storage(Path('./data/org_your_organization'))

# Clone from Hacker Dojo template
policy = clone_tenant_from_hacker_dojo(
    tenant_id='org_your_organization',  # MUST match FI client_id
    display_name='Your Organization Name',
)

# Register tenant in storage
store.tenants.upsert_from_policy(policy, template_source='org_hacker_dojo')
print('✓ Tenant policy cloned and registered')
"
```

#### Step 3: Verify Tenant Registration
```bash
python -c "
from impact_relay.storage import open_storage
store = open_storage(Path('./data/org_your_organization'))
tenant = store.tenants.get_by_id('org_your_organization')
print(f'Tenant ID: {tenant.tenant_id}')
print(f'Display Name: {tenant.display_name}')
print(f'Template Source: {tenant.meta.get(\"template\")}')
print(f'Role: {tenant.meta.get(\"role\")}')
"
```

### Phase 3: Portfolio Signals Onboarding Pack (Document Collection)

#### Step 1: Access Onboarding Pack
1. In Portfolio Signals workspace, ensure client context is set to `org_your_organization`
2. Navigate to **Onboarding pack** in sidebar menu
3. Verify you see the onboarding pack interface (if not, click "+ New Pack")

#### Step 2: Upload Required Documents
The onboarding pack requires **five** confirmed documents:

| Slot Key | UI Label | Accepted Formats | Description |
|----------|----------|------------------|-------------|
| `org_legal_name_proof` | Legal name / formation | PDF, PNG, JPEG, WebP, SVG, DOCX, TXT | Articles of incorporation, SOS filing |
| `tax_exempt_or_ein` | Tax-exempt / EIN | PDF, PNG, JPEG, WebP, SVG, DOCX, TXT | IRS determination letter, EIN confirmation |
| `governance` | Governance | PDF, PNG, JPEG, WebP, SVG, DOCX, TXT | Bylaws, operating agreement, charter |
| `brand_logo` | Logo | PNG, SVG, JPG, WebP | Organization logo (max 25MB) |
| `primary_contact` | Primary contact card | PDF, DOCX, TXT | Ops contact info (NOT donor list) |

**Upload Process**:
1. Click **"Upload Documents"** or drag files to upload zone
2. Select or drop files (max 25MB each)
3. For each uploaded file:
   - Review auto-suggested document type (classifier sets `suggested_type`)
   - Click to expand file preview
   - Select correct slot from dropdown (or leave as `uncategorized`)
   - Click **"Confirm"** button to assign to slot
4. Repeat until all five required slots show as confirmed

#### Step 3: Handle Optional & Parked Items
- **Optional slots** (w9, board_list, brand_kit, campaign_brief, impact_sample, other): Do not block pack readiness
- **Parked CRM**: `.xlsx`, `.xls`, `.csv` files are accepted but stored separately
  - Confirming parked files to org-proof slots is **blocked** (hard fail)
  - Parked items never count toward pack `ready` status

#### Step 4: Verify Pack Readiness
1. When all five required slots are confirmed, pack status automatically changes to **"ready"**
2. Ready badge appears in pack header
3. If a confirmed required document is replaced without new confirmation, pack reverts to `in_progress`

### Phase 4: Cross-System Verification

#### Step 1: Confirm ID Matching
Verify that both systems use identical identifiers:
- Portfolio Signals: Client ID = `org_your_organization`
- Impact Relay: Tenant ID = `org_your_organization`

#### Step 2: Test Basic Functionality
1. **Portfolio Signals Test**:
   - Navigate to workspace → confirm client shows as active
   - Check that published brand/config is visible (if public pages enabled)
   
2. **Impact Relay Test**:
   ```bash
   # Test durable workflow with new tenant
   python -m impact_relay --durable seed --data-dir ./data/org_your_organization
   python -m impact_relay --durable list --data-dir ./data/org_your_organization
   ```

#### Step 3: Document Isolation Check
Confirm proper data isolation:
1. Verify objects are stored under tenant-specific path:
   - Local: `./data/org_your_organization/objects/...`
   - S3 (if configured): `{prefix}/org_your_organization/...`
2. Confirm Hacker Dojo fixtures remain unaffected (CI should still pass)

## Operator Notes & Best Practices

### MFA Requirements
- All write operations require MFA-enabled session (`mfa_enforced = true`)
- Both master_admin and director roles require MFA for onboarding pack access
- Without enforced MFA, onboarding APIs return 403 Forbidden

### Synthetic Data for Testing
- Use disposable labels for dry-runs: `org_test_org`, `org_demo_nonprofit`
- Never use real donor lists or tax documents in fixtures/git
- Prefer synthetic PDFs/images for testing

### Failure Modes & Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| Pack access forbidden | Missing MFA enforcement | Run set-mfa-enforced.sql, re-login with MFA |
| Upload 403 after deploy | Missing Edge functions | Deploy `upload-onboarding-document` and `onboarding-document-url` |
| Pack never ready | Unconfirmed required slots | Confirm all five required slots (optional don't count) |
| ID mismatch FI vs IR | Different identifier strings | Use identical `org_*` string in both systems |
| Cross-tenant data visible | Isolation regression | Run policy suite: `supabase/tests/014_agi_two_tenant_acceptance.sql` |
| Second tenant marked reference | Incorrect reference_tenant flag | Only Hacker Dojo (`org_hacker_dojo`) should have `reference_tenant = true` |

### Related Documentation
- [OPERATOR-ACCESS-ONBOARDING.md](OPERATOR-ACCESS-ONBOARDING.md) - MFA & people requirements
- [COMMERCIAL-CLIENT-LIFECYCLE.md](COMMERCIAL-CLIENT-LIFECYCLE.md) - Provision → publish → activate
- [CLIENT-CONFIGURATION.md](CLIENT-CONFIGURATION.md) - Brand & content publication
- [IMPORT-RUNBOOK.md](IMPORT-RUNBOOK.md) - Governed import (separate, production BLOCKED)
- [DATA-PLACEMENT.md](DATA-PLACEMENT.md) - Private vs public placement
- Impact Relay: [HACKER-DOJO-INTEGRATION.md](docs/HACKER-DOJO-INTEGRATION.md)
- Impact Relay: [docs/architecture/AGI-SUITE.md](docs/architecture/AGI-SUITE.md)

## Automation Opportunities

While the current process requires human confirmation for document validation, these components could be automated in future versions:

1. **Document Classification**: Enhance ML-based suggested_type accuracy
2. **Policy Cloning**: API endpoint for tenant creation (currently library/tooling only)
3. **Pack Status Webhooks**: Notify when pack becomes ready for downstream processes
4. **Cross-System Triggers**: Auto-provision IR tenant when FI client activated (with approval gates)

## Summary

The complete tenant onboarding process requires coordination between:
1. **Portfolio Signals** (frontend): Client provisioning, branding, document collection
2. **Impact Relay** (backend): Tenant policy cloning, storage registration, workflow isolation
3. **Human Validation**: MFA-authenticated confirmation of legal/organizational documents

Both systems must share the same identifier (`client_id` == `tenant_id`) to maintain data consistency across the autogive.app suite. The process ensures proper isolation while providing a unified experience for nonprofit organizations joining the platform.