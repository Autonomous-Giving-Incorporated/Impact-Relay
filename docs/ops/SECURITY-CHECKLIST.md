# Security review checklist (pre v1.0)

- [ ] No agent can approve L3 without human ApprovalReceipt
- [ ] Cross-tenant isolation tests green
- [ ] Privacy Sentinel on all public exports
- [ ] Object keys tenant-scoped; SSE on S3 in production
- [ ] OIDC principal required for production approve (`require_principal_for_approve=True`)
- [ ] SoD: no self-approve on corrections / expense approve
- [ ] Secrets not in git (`.env` gitignored)
- [ ] SMTP uses STARTTLS/SSL; Postmark uses the default HTTPS endpoint; credentials come from host secrets; donor resolution remains host-owned
- [ ] Production notification tests confirm missing consent performs no recipient lookup or network call
- [ ] Backup restore dry-run documented
- [ ] Incident contacts filled for Hacker Dojo tenant
- [ ] Dependency audit (`pip` / supply chain)
