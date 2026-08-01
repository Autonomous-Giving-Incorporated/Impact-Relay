const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0
});

function text(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;'
  }[c]));
}

function formatWhen(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  } catch {
    return iso;
  }
}

function progressPercent(raised, target) {
  if (!target || target <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((raised / target) * 100)));
}

function render(state) {
  const { organization, campaign, milestones, notifications, privacy, updatedAt } = state;

  text('orgName', organization.name);
  text('orgTagline', organization.tagline);
  text('campaignName', campaign.name);
  const raisedLabel = campaign.raisedClaimLabel || 'PILOT';
  const raisedSource = campaign.raisedSource || 'pilot_synthetic';
  text('campaignMeta', [
    campaign.eventDate ? `Event ${campaign.eventDate}` : null,
    `Processor ${organization.processor}`,
    campaign.lastReconciledAt
      ? `Reconciled ${formatWhen(campaign.lastReconciledAt)}`
      : 'Not yet reconciled',
    `Raised source: ${raisedSource} (${raisedLabel})`
  ].filter(Boolean).join(' · '));

  const status = document.getElementById('campaignStatus');
  status.textContent = campaign.status.replaceAll('_', ' ');
  status.classList.toggle('is-active', campaign.status === 'active' && raisedSource === 'processor_aggregate');
  status.classList.toggle('is-waiting', campaign.status === 'awaiting_live_reconciliation' || raisedSource === 'pilot_synthetic');

  text('raisedValue', money.format(campaign.raisedPublic || 0));
  text('committedValue', money.format(campaign.committedPublic || 0));
  text('donorCount', String(campaign.donorCountPublic || 0));
  text('minimumTarget', money.format(campaign.minimumTarget || 0));

  const pct = progressPercent(campaign.raisedPublic || 0, campaign.minimumTarget || 0);
  text('progressPct', `${pct}%`);
  document.getElementById('progressFill').style.width = `${pct}%`;
  text(
    'progressCaption',
    `Public raised toward ${money.format(campaign.minimumTarget)} minimum · stretch ${money.format(campaign.stretchTarget)}` +
      (raisedSource === 'pilot_synthetic'
        ? ' · demo pilot totals (not live processor cash)'
        : raisedSource === 'not_available'
          ? ' · live raised not yet available'
          : ' · processor aggregate')
  );

  const donate = document.getElementById('donateLink');
  donate.href = organization.donationUrl;
  donate.textContent = `Donate via ${organization.processor}`;

  document.getElementById('milestoneGrid').innerHTML = milestones.map(m => {
    const reached = m.state === 'reached' || (campaign.raisedPublic || 0) >= m.threshold;
    return `
      <article class="milestone-card ${reached ? 'reached' : ''}">
        <span>${escapeHtml(m.state)}</span>
        <h3>${escapeHtml(m.label)}</h3>
        <p>${escapeHtml(m.impact)}</p>
        <strong>${money.format(m.threshold)}</strong>
      </article>`;
  }).join('');

  document.getElementById('notificationList').innerHTML = (notifications || [])
    .slice()
    .sort((a, b) => String(b.publishedAt).localeCompare(String(a.publishedAt)))
    .map(n => `
      <article class="notification-card ${escapeHtml(n.severity)}">
        <div class="meta">
          <span>${escapeHtml(n.severity)}</span>
          <span>${escapeHtml(formatWhen(n.publishedAt))}</span>
        </div>
        <h3>${escapeHtml(n.title)}</h3>
        <p>${escapeHtml(n.body)}</p>
      </article>`)
    .join('') || '<p class="note">No public notifications yet.</p>';

  text(
    'privacyCopy',
    `Classification: ${privacy.classification}. PII allowed: ${privacy.piiAllowed}. Donor names allowed: ${privacy.donorNamesAllowed}. Individual amounts allowed: ${privacy.individualAmountsAllowed}.`
  );
  text('updatedAt', `Updated ${updatedAt}`);
  document.title = `Impact Relay · ${organization.name}`;
}

function renderUseOfFunds(exportDoc) {
  if (!exportDoc) {
    text('uofTotal', '—');
    document.getElementById('uofList').innerHTML =
      '<p class="note">No public use-of-funds receipts published yet.</p>';
    return;
  }

  if (exportDoc.privacy?.piiAllowed || exportDoc.privacy?.donorNamesAllowed) {
    throw new Error('Use-of-funds privacy contract violation.');
  }

  const total = Number(exportDoc.summary?.totalAttributed || 0);
  text('uofTotal', money.format(total));

  const rows = exportDoc.receipts || [];
  document.getElementById('uofList').innerHTML = rows.map(r => `
    <article class="uof-card">
      <div class="meta">
        <span>${escapeHtml(r.verificationState)}</span>
        <span>${escapeHtml(r.purchaseDate)}</span>
      </div>
      <h3>${escapeHtml(r.allocationName)}</h3>
      <p>${escapeHtml(r.description)}</p>
      <div class="uof-facts">
        <div><span class="metric-label">Attributed</span><strong>${money.format(Number(r.attributedAmount || 0))}</strong></div>
        <div><span class="metric-label">Category</span><strong>${escapeHtml(r.category)}</strong></div>
        <div><span class="metric-label">Method</span><strong>${escapeHtml(r.attributionMethod)}</strong></div>
        <div><span class="metric-label">Remaining fund</span><strong>${money.format(Number(r.remainingDesignatedBalance || 0))}</strong></div>
      </div>
      <p class="note">Vendor: ${escapeHtml(r.vendor)} · Receipt ${escapeHtml(r.receiptId)}</p>
    </article>`).join('') || '<p class="note">No public use-of-funds receipts published yet.</p>';
}

function renderImpactOutcomes(doc) {
  if (!doc) {
    text('impactParticipants', '—');
    document.getElementById('impactOutcomeList').innerHTML =
      '<p class="note">No public impact outcomes published yet.</p>';
    return;
  }
  if (doc.privacy?.piiAllowed || doc.privacy?.donorNamesAllowed) {
    throw new Error('Impact outcomes privacy contract violation.');
  }
  text('impactParticipants', String(doc.summary?.totalParticipantsPublic ?? 0));
  const rows = doc.outcomes || [];
  document.getElementById('impactOutcomeList').innerHTML = rows.map(o => `
    <article class="digest-card">
      <div class="meta">
        <span>${escapeHtml(o.evidenceState)}</span>
        <span>${escapeHtml(o.eventDate)}</span>
      </div>
      <h3>${escapeHtml(o.programName)} — ${escapeHtml(o.eventType)}</h3>
      <p>${escapeHtml(o.description || '')}</p>
      <div class="uof-facts">
        <div><span class="metric-label">Participants</span><strong>${escapeHtml(o.participantsPublic)}</strong></div>
        <div><span class="metric-label">Fund</span><strong>${escapeHtml(o.allocationName)}</strong></div>
        <div><span class="metric-label">Method</span><strong>${escapeHtml(o.attributionMethod)}</strong></div>
      </div>
      <p class="note">Outcome ${escapeHtml(o.publicId)}</p>
    </article>`).join('') || '<p class="note">No public impact outcomes published yet.</p>';
}

function renderPublicEvidence(doc) {
  if (!doc) {
    text('evidenceContributions', '—');
    document.getElementById('evidence990').innerHTML =
      '<p class="note">No public evidence package published yet.</p>';
    document.getElementById('evidenceHistorical').innerHTML = '';
    return;
  }
  if (doc.privacy?.piiAllowed || doc.privacy?.donorNamesAllowed) {
    throw new Error('Public evidence privacy contract violation.');
  }

  text(
    'evidenceContributions',
    money.format(Number(doc.summary?.form990ContributionsTotal || 0))
  );
  text(
    'evidenceNote',
    [
      doc.sourcePage ? `Source: ${doc.sourcePage}` : null,
      doc.researchCutoff ? `Research cutoff ${doc.researchCutoff}` : null,
      doc.campaignTargets?.liveRaisedState
        ? `Live campaign raised: ${doc.campaignTargets.liveRaisedState}`
        : null,
      doc.note || null,
    ].filter(Boolean).join(' · ')
  );

  const rows = doc.form990Contributions || [];
  document.getElementById('evidence990').innerHTML = `
    <table class="workspace-table">
      <thead>
        <tr>
          <th>FY</th>
          <th>Contributions</th>
          <th>Total revenue</th>
          <th>Net assets</th>
          <th>Label</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(r => `
          <tr>
            <td>${escapeHtml(r.fiscalYear)}</td>
            <td>${money.format(Number(r.contributions || 0))}</td>
            <td>${money.format(Number(r.totalRevenue || 0))}</td>
            <td>${money.format(Number(r.netAssets || 0))}</td>
            <td>${escapeHtml(r.claimLabel)}</td>
          </tr>`).join('')}
      </tbody>
    </table>`;

  const historical = doc.historicalCampaigns || [];
  document.getElementById('evidenceHistorical').innerHTML = historical.map(h => `
    <article class="digest-card">
      <div class="meta">
        <span>${escapeHtml(h.claimLabel)}</span>
        <span>${escapeHtml(h.id)}</span>
      </div>
      <h3>${escapeHtml(h.label)}</h3>
      <p>${escapeHtml(h.useOfFundsSummary || '')}</p>
      <div class="uof-facts">
        <div><span class="metric-label">Raised (approx.)</span><strong>${money.format(Number(h.raisedApproximate || 0))}</strong></div>
        <div><span class="metric-label">Backers (approx.)</span><strong>${escapeHtml(h.backerCountApproximate ?? '—')}</strong></div>
      </div>
    </article>`).join('');
}

function renderDigests(doc) {
  if (!doc) {
    text('digestAttendance', '—');
    document.getElementById('digestList').innerHTML =
      '<p class="note">No public impact digests published yet.</p>';
    return;
  }
  if (doc.privacy?.piiAllowed || doc.privacy?.attendeeNamesAllowed) {
    throw new Error('Digest privacy contract violation.');
  }
  text('digestAttendance', String(doc.summary?.totalAttendancePublic ?? 0));
  const events = doc.events || [];
  document.getElementById('digestList').innerHTML = events.map(e => `
    <article class="digest-card">
      <div class="meta">
        <span>${escapeHtml(e.class)}</span>
        <span>${escapeHtml(e.occurredOn)}</span>
      </div>
      <h3>${escapeHtml(e.title)}</h3>
      <p>${escapeHtml(e.impactSummary)}</p>
      <div class="uof-facts">
        <div><span class="metric-label">Attendance</span><strong>${escapeHtml(e.attendeeCountPublic)}</strong></div>
        <div><span class="metric-label">Location</span><strong>${escapeHtml(e.locationLabel || '—')}</strong></div>
        <div><span class="metric-label">Linked fund</span><strong>${escapeHtml(e.linkedAllocationName || '—')}</strong></div>
      </div>
    </article>`).join('') || '<p class="note">No public impact digests published yet.</p>';
}

async function loadJson(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) {
    if (response.status === 404) return null;
    throw new Error(`Failed to load ${path} (${response.status})`);
  }
  return response.json();
}

async function boot() {
  try {
    const state = await loadJson('data/impact-state.json');
    if (!state) throw new Error('impact-state.json missing');
    if (state.privacy?.piiAllowed || state.privacy?.donorNamesAllowed) {
      throw new Error('Privacy contract violation: personal data flags must remain false.');
    }
    render(state);

    const uof = await loadJson('data/use-of-funds-public.json');
    renderUseOfFunds(uof);

    const digests = await loadJson('data/impact-digests-public.json');
    renderDigests(digests);

    const evidence = await loadJson('data/public-evidence.json');
    renderPublicEvidence(evidence);

    const impactOutcomes = await loadJson('data/public-impact.json');
    renderImpactOutcomes(impactOutcomes);
  } catch (error) {
    console.error(error);
    text('campaignName', 'Unable to load impact state');
    text('campaignMeta', error.message || String(error));
  }
}

boot();
