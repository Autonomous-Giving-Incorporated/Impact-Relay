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
  text('campaignMeta', [
    campaign.eventDate ? `Event ${campaign.eventDate}` : null,
    `Processor ${organization.processor}`,
    campaign.lastReconciledAt
      ? `Reconciled ${formatWhen(campaign.lastReconciledAt)}`
      : 'Not yet reconciled'
  ].filter(Boolean).join(' · '));

  const status = document.getElementById('campaignStatus');
  status.textContent = campaign.status.replaceAll('_', ' ');
  status.classList.toggle('is-active', campaign.status === 'active');
  status.classList.toggle('is-waiting', campaign.status === 'awaiting_live_reconciliation');

  text('raisedValue', money.format(campaign.raisedPublic || 0));
  text('committedValue', money.format(campaign.committedPublic || 0));
  text('donorCount', String(campaign.donorCountPublic || 0));
  text('minimumTarget', money.format(campaign.minimumTarget || 0));

  const pct = progressPercent(campaign.raisedPublic || 0, campaign.minimumTarget || 0);
  text('progressPct', `${pct}%`);
  document.getElementById('progressFill').style.width = `${pct}%`;
  text(
    'progressCaption',
    `Public raised toward ${money.format(campaign.minimumTarget)} minimum · stretch ${money.format(campaign.stretchTarget)}`
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

async function boot() {
  try {
    const response = await fetch('data/impact-state.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Failed to load impact state (${response.status})`);
    const state = await response.json();
    if (state.privacy?.piiAllowed || state.privacy?.donorNamesAllowed) {
      throw new Error('Privacy contract violation: personal data flags must remain false.');
    }
    render(state);
  } catch (error) {
    console.error(error);
    text('campaignName', 'Unable to load impact state');
    text('campaignMeta', error.message || String(error));
  }
}

boot();
