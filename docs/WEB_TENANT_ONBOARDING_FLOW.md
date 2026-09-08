# Web-Based Tenant Onboarding Process for autogive.app

This document describes how to implement the tenant onboarding process as a web-based flow with tooltips, dropdowns, and guided steps that can be followed directly through the Portfolio Signals and Impact Relay interfaces.

## Web-Based Onboarding Flow Overview

The complete tenant onboarding can be accomplished through the web interface with these phases:

### Phase 1: Portfolio Signals Setup (Web UI Only)
### Phase 2: Impact Relay Setup (Web API Calls via Admin Panel)
### Phase 3: Document Collection (Web UI Only)

## Implementation: Step-by-Step Web Process

### 🔐 Phase 0: Prerequisites (Web)
**Location**: Portfolio Signals Workspace
1. Login to https://autogive.app/portfolio-signals/workspace with MFA
2. Verify master admin role in user dropdown (top-right)
3. Confirm MFA enforced status in Settings → Security

### 🏢 Phase 1: Client Provisioning (Web UI - Portfolio Signals)
**Location**: Workspace → Clients Management

**Step 1: Open Client Management**
- Click client context dropdown (top-left of workspace header)
- Select "Manage Clients" → opens client management modal
- [Tooltip: "View and manage all nonprofit clients on the platform"]

**Step 2: Create New Client**
- Click "+ New Client" button (floating action button)
- Form appears with inline validation:
  - **Client ID** [tooltip: "Unique identifier, format: org_[a-z0-9_]+, must match Impact Relay tenant_id"]
    - Input: `org_` [autocomplete suggests: org_hacker_dojo, org_other_makerspace]
    - Validation: Real-time regex check `/^org_[a-z0-9_]+$/`
  - **Slug** [tooltip: "URL-friendly identifier for public pages"]
    - Input: auto-generated from Client ID (org_ → removed)
    - Example: `org_community_arts` → slug: `community-arts`
  - **Display Name** [tooltip: "Full legal name of the organization"]
    - Input: "Community Arts Organization"
  - **Initial Director** [tooltip: "User who will manage this client"]
    - Dropdown: [Current User] + [Search users]
    - [Info: "Director will need MFA enabled for document uploads"]

**Step 3: Provision Client**
- Click "Provision Client" button [disabled until form valid]
- Shows progress spinner with message: "Creating client and setting up initial resources..."
- Success: Toast notification "Client org_community_arts provisioned successfully"
- Error: Inline form validation with specific error messages

### 🎨 Phase 2: Brand Configuration (Web UI - Portfolio Signals)
**Location**: Workspace → Brand & Content (with client context selected)

**Step 1: Enable Fundraising Modules**
- Toggle switches for desired modules:
  - [ ] Donation Management
  - [ ] Grant Tracking  
  - [ ] Event Ticketing
  - [ ] Membership Dues
- [Tooltip: "Enable at least one module to proceed"]
- Real-time validation: "Please enable at least one fundraising module"

**Step 2: Upload Brand Assets**
- Drag & drop area or click to browse:
  - **Logo** [tooltip: "PNG, SVG, JPG, WebP - Max 25MB"]
    - Shows preview thumbnail after upload
    - [Info: "Recommended: Square aspect ratio, transparent background"]
  - **Favicon** [tooltip: "ICO or PNG - 32x32px recommended"]
    - Optional field
- Upload button shows progress: "Uploading and optimizing assets..."

**Step 3: Publish & Activate**
- Two-button group:
  - [Publish Configuration] [secondary button]
  - [Activate Client] [primary button - disabled until publish]
- Click Publish → shows "Configuration published to edge network" toast
- Click Activate → confirmation modal:
  ```
  Activate Client?
  
  This will make the client live and accessible to directors.
  
  [Cancel]     [Activate]
  ```
- Success: Client status badge changes to "● Active" (green)
- Error: Specific error with retry option

### 📁 Phase 3: Impact Relay Tenant Setup (Web Admin Panel)
**Location**: Dedicated admin panel or workspace settings → Tenant Management

**Note**: This requires exposing Impact Relay tenant operations through a secure web interface

**Step 1: Access Tenant Management**
- Navigation: Settings → Platform → Tenant Management
- [Badge: "Requires master_admin role + MFA enforced"]
- Shows table of existing tenants with columns:
  - Tenant ID | Display Name | Status | Template Source | Actions

**Step 2: Clone Tenant from Template**
- Click "+ New Tenant" button
- Form appears:
  - **Tenant ID** [tooltip: "Must match Portfolio Signals Client ID"]
    - Prefilled: `org_` [read-only after first character]
    - Validation: Matches pattern `/^org_[a-z0-9_]+$/`
    - [Info: "Enter the same ID used in Portfolio Signals client provisioning"]
  - **Display Name** [tooltip: "Human-readable name for the organization"]
    - Input: "Community Arts Organization"
  - **Template Source** [tooltip: "Base configuration to clone from"]
    - Dropdown: 
      - [✓] Hacker Dojo (Recommended) - org_hacker_dojo
      - [ ] Other existing tenants (if any)
  - **Advanced Options** [collapsible section]:
    - [ ] Skip policy validation (for testing only)
    - [ ] Copy fixture data (NOT RECOMMENDED for production)

**Step 3: Execute Clone Operation**
- Click "Clone Tenant" button [shows loading state]
- Backend executes:
  ```python
  # This happens server-side when button clicked
  from impact_relay.storage.template import clone_tenant_from_hacker_dojo
  from impact_relay.storage import open_storage
  
  store = open_storage(get_tenant_data_dir(tenant_id))  # Isolated per tenant
  policy = clone_tenant_from_hacker_dojo(
      tenant_id=form.tenant_id,
      display_name=form.display_name,
  )
  store.tenants.upsert_from_policy(policy, template_source="org_hacker_dojo")
  ```
- Progress shows:
  1. "Validating tenant ID format..."
  2. "Loading Hacker Dojo template..."
  3. "Cloning policy configuration..."
  4. "Registering tenant in storage..."
  5. "Creating isolated storage directory..."
- Success: New row appears in tenants table with status "● Ready"
- Error: Specific error with troubleshooting suggestions

**Step 4: Verify Tenant Isolation**
- New tenant row shows:
  - **Actions** dropdown:
    - [View Details]
    - [Manage Storage]
    - [Run Diagnostics]
    - [Delete Tenant] [requires confirmation]
- Click "View Details" shows modal:
  ```
  Tenant Details: org_community_arts
  
  Tenant ID: org_community_arts
  Display Name: Community Arts Organization
  Template Source: org_hacker_dojo
  Status: ● Ready
  Storage Path: ./data/org_community_arts/
  
  Isolation Checks:
  ✓ Tenant ID matches Pattern
  ✓ Storage directory isolated
  ✓ Policy cloned from template
  ✓ No cross-tenant access detected
  ```

### 📄 Phase 4: Document Collection (Web UI - Portfolio Signals)
**Location**: Workspace → Onboarding Pack (with client context selected)

**Step 1: Access Onboarding Pack**
- Sidebar navigation: Onboarding Pack [icon: 📁]
- [Badge: "Visible to directors and master_admins with MFA"]
- Empty state shows:
  ```
  Ready to collect organizational verification documents
  
  [Upload Documents]   or   Drag files here
  
  Required: 5/5 documents
  Status: ○ In Progress
  ```

**Step 2: Upload Documents**
- Drag & drop or click to browse:
  - Accepts: PDF, PNG, JPEG, WebP, SVG, DOCX, TXT
  - Max size: 25MB per file
  - Multiple file selection enabled
- Upload shows progress per file:
  - [filename] ▰▰▰▰▰ 100% ✓
  - [filename] ▰▰▰▰▱ 60% ⏳
- Failed uploads show retry button with error reason

**Step 3: Document Classification & Confirmation**
For each uploaded file, a card appears:
```
[FILE PREVIEW THUMBNAIL]
filename.pdf
Size: 2.4 MB | Uploaded: 2 min ago

🤖 Suggested Type: tax_exempt_or_ein
[Confidence: 92%]

▼ Select Slot:
  ○ org_legal_name_proof   (Legal name / formation)
  ● tax_exempt_or_ein      (Tax-exempt / EIN) ← Selected
  ○ governance             (Governance)
  ○ brand_logo             (Logo)
  ○ primary_contact        (Primary contact card)
  ○ w9                     (W-9) [Optional]
  ○ board_list             (Board list) [Optional]
  ○ brand_kit              (Brand kit / style) [Optional]
  ○ campaign_brief         (Campaign / program brief) [Optional]
  ○ impact_sample          (Sample impact / annual PDF) [Optional]
  ○ other                  (Other) [Optional]
  ○ uncategorized          (Type not confirmed)

[Confirm Assignment]   [Replace File]   [Delete]
```
- [Tooltip: "Confirm assigns this document to the selected slot"]
- [Tooltip: "Replace keeps the slot assignment but swaps the file"]
- [Tooltip: "Delete removes the upload entirely"]

**Step 4: Track Progress**
- Progress bar shows: "Required: 3/5 documents confirmed"
- Slot status indicators:
  - ✓ Confirmed (green checkmark)
  - ○ Pending (empty circle)
  - △ Optional confirmed (blue checkmark in optional section)
- Required slots must all be ✓ for pack readiness

**Step 5: Handle Special File Types**
- When .xlsx, .xls, or .csv uploaded:
  - Shows banner: "📄 Detected spreadsheet - stored as parked CRM data"
  - [Info: "Parked CRM data cannot confirm to org-proof slots but is available for import quarantine"] 
  - Slot selection dropdown excludes org-proof options for these files
  - Confirm button shows: "Confirm as parked CRM" (does not affect readiness)

**Step 6: Pack Readiness**
When all 5 required slots confirmed:
- Status badge changes to: "● Ready" (green)
- Toast notification: "Onboarding pack is ready! All required documents confirmed."
- Pack header shows:
  ```
  Onboarding Pack: Ready
  Confirmed: 5/5 required | 2/7 optional
  Last updated: Today, 2:30 PM
  
  [Download Confirmation PDF]   [Request Re-verification]
  ```
- [Download Confirmation PDF] generates summary of all confirmed documents
- [Request Re-verification] resets pack to in_progress state (requires re-confirmation)

### 🔄 Phase 5: Cross-System Verification (Web UI)
**Location**: Workspace → Settings → Platform Health

**Step 1: Run Tenant Health Check**
- Button: "Verify Tenant Isolation" [in Platform Health section]
- [Tooltip: "Confirms proper data isolation between Portfolio Signals and Impact Relay"]
- Click shows progress: "Running verification checks..."
- Results displayed in expandable sections:

```
✓ Portfolio Signals Check
  - Client org_community_arts exists: ACTIVE
  - Brand configuration published: YES
  - Onboarding pack status: READY

✓ Impact Relay Check  
  - Tenant org_community_arts registered: YES
  - Storage isolated: ./data/org_community_arts/
  - Policy source: org_hacker_dojo
  - No cross-tenant access detected

✓ ID Matching Check
  - FI Client ID: org_community_arts
  - IR Tenant ID: org_community_arts
  - Match: VALID
  
Overall Status: ● ALL SYSTEMS GO
```

**Step 2: Test Basic Operations**
- Button: "Test Tenant Workflow" [appears after health check passes]
- Runs safe, non-destructive test:
  1. Creates temporary workflow in tenant's isolated storage
  2. Verifies ledger operations work correctly
  3. Cleans up test data
- Shows results: "✓ Tenant workflow test passed - ledger operations functional"

### 📱 Responsive Design & Accessibility Notes

**Mobile Experience**:
- All forms stack vertically on narrow screens
- Upload area becomes tap target with "Choose Files" button
- Document cards use swipe gestures for actions on touch devices
- Progress bars remain visible in collapsed sections

**Accessibility**:
- All form fields have associated labels
- Color contrast meets WCAG AA standards
- Keyboard navigation: Tab through fields, Enter to submit, Escape to cancel
- Screen reader friendly: Live regions announce upload progress and status changes
- Alt text for all icons and previews

**Tooltips & Guidance**:
- Inline tooltips on all form fields with [?] icons
- Contextual help collapsible panels in complex sections
- Validation messages appear inline with specific guidance
- Empty states show clear call-to-action buttons
- Error states provide actionable resolution steps

### 🛡️ Security & Validation

**Client-Side Validation**:
- Real-time format checking for IDs and slugs
- File type validation before upload (extension + MIME sniffing)
- Size validation shows progress: "2.1/25 MB"
- Duplicate file detection warns before upload

**Server-Side Validation** (implicit in API calls):
- Tenant ID format and uniqueness
- MFA enforcement verification for all write operations
- Role-based access control (master_admin/director only)
- Rate limiting on upload and clone operations
- Input sanitization and SQL injection prevention
- File virus scanning (ClamAV) on upload
- Path traversal prevention in file storage

### 📋 Complete Flow Summary

```
[Master Admin Login] 
        ↓
[Provision Client in Portfolio Signals] → [Enter org_* ID, name, enable module] 
        ↓
[Configure Brand & Activate] → [Upload logo, publish, activate] 
        ↓
[Clone Tenant in Impact Relay Admin] → [Enter matching org_* ID, select template] 
        ↓
[Verify Tenant Health] → [Run isolation and ID matching checks] 
        ↓
[Collect Documents in Onboarding Pack] → [Upload & confirm 5 required docs] 
        ↓
[Pack Ready Status] → [Download confirmation or request re-verification]
```

### 🎯 User Experience Goals

1. **Clarity**: Each step has clear purpose and outcome
2. **Guidance**: Tooltips, validation, and examples prevent errors
3. **Feedback**: Immediate response to user actions
4. **Progress**: Clear indication of completion status
5. **Safety**: Prevents invalid operations through UI constraints
6. **Efficiency**: Minimizes steps while maintaining compliance
7. **Confidence**: Verification steps confirm correct setup

### 📝 Implementation Notes for Developers

**Frontend (Portfolio Signals)**:
- Use existing Supabase auth with MFA enforcement checks
- Form libraries: React Hook Form or Formik with Yup validation
- Upload handling: Chunked uploads with progress tracking
- UI framework: Existing Design System components
- State management: React Query or Redux Toolkit

**Backend Integration**:
- Secure API endpoints for Impact Relay operations:
  - POST /api/tenant/clone - clones from template
  - GET /api/tenant/{id}/verify - runs health checks
  - POST /api/tenant/{id}/test-workflow - safe functionality test
- All endpoints require:
  - Valid Supabase JWT with MFA claim
  - Master admin or director role for target client
  - Audit logging of all operations

**Data Flow**:
1. Client provisioning → Creates Supabase row in `clients` table
2. Tenant cloning → Creates Impact Relay storage entry
3. Document uploads → Stored in Supabase `campaign-private` bucket
4. Verification → Cross-checks IDs and storage paths
5. Readiness → Triggers webhook or updates pack status

This web-based flow transforms the previously backend-only process into a guided, tooltip-assisted experience that organization administrators can follow entirely through the autogive.app web interface.