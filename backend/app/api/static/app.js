'use strict';
const $ = id => document.getElementById(id);
const state = { profile: null, status: null, latest: null, selectedRun: null, view: 'dashboard', values: {}, polling: false };

const names = {
  geography: 'Geography', entities: 'Entities', keywords: 'Keywords', hashtags: 'Hashtags',
  incident_types: 'Incident types', youtube: 'YouTube', instagram: 'Instagram', news: 'News',
  x: 'X', reddit: 'Reddit', meta: 'Facebook / Meta', web: 'Web'
};

// User-friendly navigation labels
const views = {
  dashboard: 'Dashboard',
  profile: 'Setup Profile',
  run: 'Start Audit',
  history: 'Past Audits',
  platforms: 'Platform Results',
  records: 'Search Records',
  events: 'Key Findings',
  sources: 'Monitored Sources',
  alerts: 'Alerts',
  settings: 'Settings'
};

// Only the metrics we actually show to users
const userMetrics = {
  items_checked: 'Items scanned',
  relevant_items: 'Relevant items',
  sources_discovered: 'Sources found',
  errors: 'Issues'
};

const errorMessages = {
  instagram_not_configured: 'Instagram not configured. Go to Settings to import your session.',
  instagram_session_expired: 'Instagram session expired. Please re-import in Settings.',
  instagram_rate_limited: 'Instagram rate limited. Wait a few minutes and try again.',
  youtube_timeout: 'YouTube took too long. Try reducing the time window.',
  youtube_extraction_failed: 'YouTube could not extract data. Try again later.',
  no_enabled_values: 'No search terms enabled. Add keywords in Setup Profile.',
  application_interrupted: 'Audit was interrupted. Please run a new one.'
};

/* ── Helpers ── */
function node(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function empty(text) { return node('p', text, 'empty'); }
function notice(text) { $('notice').textContent = text; }

function formatDate(v) {
  if (!v) return '—';
  try {
    return new Intl.DateTimeFormat('en-IN', {
      dateStyle: 'medium', timeStyle: 'short',
      timeZone: 'Asia/Kolkata'
    }).format(new Date(v));
  } catch { return v; }
}

function pill(status, extraCls) {
  const cls = extraCls ? `pill ${extraCls}` : `pill ${status || ''}`;
  const label = {
    'complete': '✅ Complete',
    'failed': '❌ Failed',
    'partial': '⚠️ Partial',
    'running': '⏳ Running',
    'disabled': '—',
    'CURRENT': '🕐 Current',
    'STALE': '📅 Old',
    'UNKNOWN_TIME': '❓ Unknown date',
    'AFTER_WINDOW': '⏭️ After window'
  }[status] || status || 'Not audited';
  return node('span', label, cls);
}

async function api(path, data, method) {
  const r = await fetch(path, {
    method: method || (data === undefined ? 'GET' : 'POST'),
    headers: {
      'X-Watchtower-Token': document.querySelector('meta[name=watchtower-token]').content,
      'Content-Type': 'application/json'
    },
    body: data === undefined ? undefined : JSON.stringify(data)
  });
  const result = await r.json();
  if (!r.ok) throw new Error(result.error || 'Request failed');
  return result;
}

function action(text, callback, cls) {
  const b = node('button', text, cls);
  b.type = 'button';
  b.addEventListener('click', async () => {
    b.disabled = true;
    try { await callback(); } catch (e) { notice(e.message); } finally { b.disabled = false; }
  });
  return b;
}

function bind(id, callback) {
  const el = $(id);
  if (!el) return;
  el.addEventListener('click', async () => {
    el.disabled = true;
    try { await callback(); } catch (e) { notice(e.message); } finally { el.disabled = false; }
  });
}

function link(text, url) {
  const e = node('a', text);
  try {
    const u = new URL(url);
    if (['https:', 'http:'].includes(u.protocol)) { e.href = u.href; e.target = '_blank'; e.rel = 'noopener noreferrer'; }
  } catch {}
  return e;
}

function table(rows) {
  const wrap = node('div', undefined, 'table-wrap'), t = node('table');
  for (const [k, v] of rows) {
    const tr = node('tr');
    tr.append(node('th', k), node('td', v === null || v === undefined ? '—' : String(v)));
    t.append(tr);
  }
  wrap.append(t); return wrap;
}

function details(title, child, open) {
  const e = node('details', undefined, 'panel');
  if (open) e.setAttribute('open', '');
  e.append(node('summary', title), child);
  return e;
}

/* ── Templates ── */
const templates = {
  dashboard: '<div id="overview"></div><h2>Platform Overview</h2><div id="dashboard-platforms" class="platform-grid"></div><h2>Recent Findings</h2><div id="latest-events"></div>',

  profile: '<div class="section-heading"><p>Set up your monitoring profile — add keywords, enable platforms, and save.</p><button id="save-profile" class="primary">💾 Save Profile</button></div><label class="name-field">Profile name<input id="profile-name" maxlength="120" placeholder="e.g. Kashmir Intel Monitor"></label><div id="dimensions" class="dimension-grid"></div><h2>Platforms to Monitor</h2><div id="platform-select" class="platform-grid"></div><div class="panel"><h2>Platform Specific Queries</h2><p>Override global dimensions for specific platforms. These take priority.</p><div id="platform-queries"></div></div><div class="panel"><h2>Saved Accounts & Feeds</h2><p>Add Instagram accounts or RSS news feeds to monitor directly.</p><div id="saved-sources"></div></div>',

  run: '<div class="panel"><h2>🚀 Start New Audit</h2><p id="run-summary"></p><p>All enabled platforms will be scanned simultaneously. Results appear in real-time.</p><div class="limit-grid"><label>Time window<select id="window-hours"><option value="1">Last 1 hour</option><option value="6">Last 6 hours</option><option value="12">Last 12 hours</option><option value="24" selected>Last 24 hours</option><option value="48">Last 48 hours</option><option value="168">Last 7 days</option><option value="custom">Custom range</option></select></label><label>Timezone<input id="window-zone" value="Asia/Kolkata" readonly></label></div><div id="custom-window" class="limit-grid" hidden><label>From<input id="window-start" type="datetime-local"></label><label>To<input id="window-end" type="datetime-local"></label></div><div class="actions"><button id="preview-plan">👁️ Preview Queries</button><button id="run-audit" class="primary">▶️ Run Audit Now</button></div><div id="query-plan"></div></div><div id="live-report"></div>',

  history: '<div class="history-layout"><div id="run-list" class="panel"></div><div id="history-report"></div></div>',

  platforms: '<div id="platform-cards" class="platform-grid"></div><div id="platform-report"></div>',

  records: '<div class="search-guide-box"><div class="guide-header"><strong>🔍 Search Tips</strong></div><div class="guide-chips"><span class="guide-chip" id="chip-boolean">Boolean: <code>("Ooty" OR "ऊटी") AND ("Indian Army")</code></span><span class="guide-chip" id="chip-or">Multi-term: <code>flood or earthquake or landslide</code></span><span class="guide-chip" id="chip-phrase">Exact phrase: <code>"rescue operation"</code></span></div></div><form id="search-form" class="panel"><div id="search-fields" class="limit-grid"></div><p>Search across all past audit results. Supports Boolean queries and exact phrases.</p><button type="submit" class="primary">🔍 Search</button></form><div id="record-results"></div>',

  events: '<p>Key findings grouped by similarity. Review each for verification.</p><div id="event-results"></div>',

  sources: '<p>Accounts and feeds that returned records in past audits.</p><div id="source-results"></div>',

  alerts: '<p>High-relevance matches requiring your attention.</p><div id="alert-results"></div>',

  settings: '<div class="panel" id="settings-policies-panel"><h2>⚙️ Collection Settings</h2><p>Adjust how many items to fetch, timeout budgets, and page counts per platform.</p><div id="settings-policies"></div><div class="actions"><button id="save-settings-policies" class="primary">💾 Save Settings</button></div></div><div class="panel"><h2>📸 Instagram Connection</h2><p>Import your Instaloader session file to enable Instagram monitoring.</p><div class="limit-grid"><label>Username<input id="ig-username" autocomplete="off" placeholder="your_username"></label><label>Session file<input id="ig-session" type="file"></label></div><div class="actions"><button id="ig-configure">Import Session</button><button id="ig-test">Test Connection</button></div><p id="ig-status"></p></div><div class="panel"><h2>🔎 Find Instagram Profiles</h2><p>Search public profiles to add them for monitoring.</p><div class="limit-grid"><label>Search<input id="ig-search" placeholder="e.g. kashmir news"></label><label>Min followers<input id="ig-min" type="number" min="0"></label><label>Max followers<input id="ig-max" type="number" min="0"></label></div><button id="ig-find">Search</button><div id="ig-results"></div></div><div class="panel"><h2>⏰ Scheduled Audits</h2><p>Automatically run audits at regular intervals.</p><label class="check"><input id="schedule-enabled" type="checkbox">Enable auto-schedule</label><label>Run every (minutes)<input id="schedule-minutes" type="number" min="5" max="10080" value="60"></label><button id="save-schedule">Save Schedule</button><p id="schedule-next"></p></div>'
};

/* ── Build navigation & views ── */
for (const [key, title] of Object.entries(views)) {
  const b = action(title, () => navigate(key), 'nav');
  b.dataset.view = key;
  $('navigation').append(b);
  const section = node('section', undefined, 'view');
  section.id = 'view-' + key;
  section.hidden = key !== 'dashboard';
  section.innerHTML = templates[key];
  $('views').append(section);
}

async function navigate(view) {
  state.view = view;
  for (const s of document.querySelectorAll('.view')) s.hidden = s.id !== 'view-' + view;
  for (const b of document.querySelectorAll('.nav')) b.classList.toggle('active', b.dataset.view === view);
  $('view-title').textContent = views[view];
  if (view === 'history') await history();
  if (view === 'records') await search();
  if (view === 'events') renderEvents($('event-results'), await api('/api/incidents'));
  if (view === 'sources') await sources();
  if (view === 'alerts') await alerts();
  if (view === 'settings') { await instagramStatus(); renderSettingsPolicies(); }
  if (view === 'run') runSummary();
}

/* ── Profile Management ── */
function renderDimension(category) {
  const d = state.profile.dimensions[category],
        card = node('article', undefined, 'dimension'),
        head = node('header'),
        label = node('label', names[category], 'check'),
        enabled = document.createElement('input');
  enabled.type = 'checkbox';
  enabled.checked = d.enabled;
  enabled.addEventListener('change', () => { d.enabled = enabled.checked; notice('Changes not saved yet — click Save Profile.'); });
  label.prepend(enabled);
  head.append(label);
  card.append(head);

  const filter = document.createElement('input');
  filter.type = 'search';
  filter.placeholder = 'Filter ' + names[category].toLowerCase() + '…';
  card.append(filter);

  const list = node('div', undefined, 'value-list'), count = node('p', '', 'muted');

  function draw() {
    list.replaceChildren();
    for (const value of state.values[category].filter(v => v.value.toLowerCase().includes(filter.value.toLowerCase()))) {
      const row = node('div', undefined, 'value-row'),
            l = node('label', value.value, 'check'),
            check = document.createElement('input');
      check.type = 'checkbox';
      check.checked = d.values.includes(value.value);
      check.addEventListener('change', () => {
        d.values = check.checked ? [...new Set([...d.values, value.value])] : d.values.filter(v => v !== value.value);
        count.textContent = `${d.values.length} selected`;
      });
      l.prepend(check);
      row.append(l, action('Remove', async () => {
        await api(`/api/values/${category}/${value.id}`, undefined, 'DELETE');
        d.values = d.values.filter(v => v !== value.value);
        state.values[category] = await api('/api/values/' + category);
        draw();
      }, 'small'));
      list.append(row);
    }
    if (!list.children.length) list.append(node('p', 'No values yet. Add one below.', 'muted'));
    count.textContent = `${d.values.length} selected`;
  }
  filter.addEventListener('input', draw);
  draw();

  const add = document.createElement('input');
  add.placeholder = 'Add new ' + names[category].toLowerCase() + '…';
  add.maxLength = 200;
  card.append(list, count, add, action('+ Add', async () => {
    await api('/api/values/' + category, { value: add.value });
    state.values[category] = await api('/api/values/' + category);
    add.value = '';
    draw();
    notice('Value added! Select it and save your profile to use it.');
  }));
  return card;
}

function renderProfile() {
  const p = state.profile;
  $('profile-name').value = p.name;
  $('dimensions').replaceChildren(...Object.keys(p.dimensions).map(renderDimension));
  $('platform-select').replaceChildren();
  for (const [platform, enabled] of Object.entries(p.platforms)) {
    const c = node('article', undefined, 'platform'),
          l = node('label', names[platform], 'check'),
          check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = enabled;
    check.disabled = ['x', 'reddit'].includes(platform);
    check.addEventListener('change', () => { p.platforms[platform] = check.checked; runSummary(); });
    l.prepend(check);
    const desc = check.disabled ? 'Coming soon' : platform === 'instagram' ? 'Requires session in Settings' : 'Ready to use';
    c.append(l, node('p', desc));
    $('platform-select').append(c);
  }
  renderSaved();
  renderPlatformQueries();
  const w = p.time_window;
  $('window-hours').value = w.hours === null ? 'custom' : w.hours;
  $('window-zone').value = w.timezone || 'Asia/Kolkata';
  $('custom-window').hidden = w.hours !== null;
  if (w.start_time) $('window-start').value = localInput(w.start_time);
  if (w.end_time) $('window-end').value = localInput(w.end_time);
  runSummary();
}

function localInput(v) {
  const d = new Date(v);
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function renderPlatformQueries() {
  $('platform-queries').replaceChildren();
  for (const platform of ['youtube', 'instagram', 'news', 'meta', 'web']) {
    const box = node('div', undefined, 'panel');
    box.append(node('h3', names[platform] + ' Queries'));
    for (const value of state.profile.platform_queries?.[platform] || []) {
      const row = node('div', undefined, 'actions');
      row.append(node('span', value), action('✕', () => {
        state.profile.platform_queries[platform] = state.profile.platform_queries[platform].filter(v => v !== value);
        renderPlatformQueries();
      }, 'small'));
      box.append(row);
    }
    const input = document.createElement('input');
    input.placeholder = 'e.g. "exact phrase" or keyword';
    box.append(input, action('+ Add', () => {
      const value = input.value.trim();
      if (!value) throw new Error('Enter a query');
      if (!state.profile.platform_queries) state.profile.platform_queries = {};
      state.profile.platform_queries[platform] = [...new Set([...(state.profile.platform_queries[platform] || []), value])];
      renderPlatformQueries();
      notice('Save profile to keep this change.');
    }));
    $('platform-queries').append(box);
  }
}

function renderSaved() {
  $('saved-sources').replaceChildren();
  for (const platform of ['instagram', 'news']) {
    const box = node('div', undefined, 'panel');
    box.append(node('h3', names[platform] + ' Sources'));
    for (const value of state.profile.saved_sources[platform] || []) {
      const row = node('div', undefined, 'actions');
      row.append(node('span', value), action('✕', () => {
        state.profile.saved_sources[platform] = state.profile.saved_sources[platform].filter(v => v !== value);
        renderSaved();
      }, 'small'));
      box.append(row);
    }
    const input = document.createElement('input');
    input.placeholder = platform === 'instagram' ? 'username (without @)' : 'https://example.com/rss';
    box.append(input, action('+ Add', () => {
      const value = input.value.trim();
      if (!value) throw new Error('Enter a source');
      state.profile.saved_sources[platform] = [...new Set([...(state.profile.saved_sources[platform] || []), value])];
      renderSaved();
      notice('Save profile to keep this change.');
    }));
    $('saved-sources').append(box);
  }
}

function renderSettingsPolicies() {
  const target = $('settings-policies');
  if (!target) return;
  target.replaceChildren();
  for (const [platform, p] of Object.entries(state.profile.policies)) {
    if (['x', 'reddit'].includes(platform)) continue;
    const grid = node('div', undefined, 'limit-grid');
    for (const [key, label, min, max] of [
      ['items_per_query', 'Items per search', 1, 100],
      ['timeout_seconds', 'Timeout (seconds)', 5, 300],
      ['pages_per_query', 'Pages to fetch', 0, 20],
      ['cache_ttl_seconds', 'Cache duration (seconds)', 0, 86400]
    ]) {
      const l = node('label', label), input = document.createElement('input');
      input.type = 'number'; input.min = min; input.max = max; input.value = p[key];
      input.addEventListener('change', () => { p[key] = Number(input.value); });
      l.append(input); grid.append(l);
    }
    target.append(details(names[platform], grid));
  }
}

function collectProfile() {
  const p = structuredClone(state.profile);
  p.name = $('profile-name').value;
  const h = $('window-hours').value;
  p.time_window = { hours: h === 'custom' ? null : Number(h), timezone: 'Asia/Kolkata' };
  if (h === 'custom') {
    const start = new Date($('window-start').value), end = new Date($('window-end').value);
    if (isNaN(start) || isNaN(end)) throw new Error('Choose both start and end dates');
    p.time_window.start_time = start.toISOString();
    p.time_window.end_time = end.toISOString();
  }
  p.platform_queries = state.profile.platform_queries || {};
  return p;
}

async function saveProfile() {
  const saved = await api('/api/profile', collectProfile());
  state.profile.time_window = saved.time_window;
  state.profile.name = saved.name;
  runSummary();
  notice('✅ Profile saved successfully!');
}

function runSummary() {
  if (state.profile) {
    const platforms = Object.entries(state.profile.platforms).filter(([, v]) => v).map(([p]) => names[p]).join(', ');
    $('run-summary').textContent = `${state.profile.name} · ${platforms || 'No platforms selected'}`;
  }
}

bind('save-profile', saveProfile);
bind('save-settings-policies', async () => { await saveProfile(); renderSettingsPolicies(); });
$('window-hours').addEventListener('change', () => $('custom-window').hidden = $('window-hours').value !== 'custom');

bind('preview-plan', async () => {
  await saveProfile();
  const plan = await api('/api/plan');
  $('query-plan').replaceChildren();
  for (const [p, queries] of Object.entries(plan)) {
    if (!queries.length) continue;
    const list = node('ol');
    queries.forEach(q => list.append(node('li', q.text)));
    $('query-plan').append(details(`${names[p]} — ${queries.length} queries`, list));
  }
});

bind('run-audit', async () => {
  await saveProfile();
  const r = await api('/api/run', {});
  state.selectedRun = r.run_id;
  notice('🚀 Audit started! All platforms running in parallel. Results will appear below.');
  await poll();
});

/* ── Dashboard & Reports ── */
function summaryCard(report) {
  const box = node('div', undefined, 'panel');
  if (!report?.platforms) {
    box.append(empty('No audits yet. Go to Setup Profile to get started.'));
    return box;
  }
  box.append(node('h2', `Audit — ${formatDate(report.started_at)}`), pill(report.status));
  const w = report.time_window;
  if (w) box.append(node('p', `${formatDate(w.start_time)} → ${formatDate(w.end_time)} (IST)`));
  box.append(table([
    ['Duration', report.duration_seconds == null ? 'Still running…' : report.duration_seconds + ' seconds'],
    ['Items scanned', report.metrics?.items_checked],
    ['Relevant items', report.metrics?.relevant_items],
    ['Sources found', report.metrics?.sources_discovered],
    ['Findings', report.event_count]
  ]));

  const exportRow = node('div', undefined, 'actions');
  exportRow.append(
    action('📄 Download CSV', () => download(report.id, 'normalized', 'csv')),
    action('🖨️ Print / Save PDF', () => { window.print(); })
  );
  box.append(exportRow);
  return box;
}

function platformCards(target, report) {
  target.replaceChildren();
  for (const platform of ['youtube', 'instagram', 'news', 'x', 'reddit', 'meta', 'web']) {
    const a = report?.platforms?.[platform], card = node('article', undefined, 'platform');
    const status = a?.status || 'disabled';
    const statusLabel = { complete: '✅', failed: '❌', partial: '⚠️', running: '⏳', disabled: '—' }[status] || '';
    card.append(
      node('h3', `${statusLabel} ${names[platform]}`),
      node('p', `${a?.metrics?.items_checked ?? 0} items · ${a?.metrics?.relevant_items ?? 0} relevant`),
      action('View details', async () => {
        await navigate('platforms');
        state.selectedRun = report?.id;
        if (report) await platformReport(report.id, platform);
        else $('platform-report').replaceChildren(empty('No data for this platform.'));
      })
    );
    target.append(card);
  }
}

async function platformReport(runId, platform) {
  const a = await api(`/api/audits/${runId}/platforms/${platform}`),
        box = node('article', undefined, 'panel');

  const header = node('div', undefined, 'dashboard-header');
  header.style.cssText = 'display: flex; align-items: center; gap: 16px; margin-bottom: 8px;';
  header.append(
    node('h2', names[platform] + ' Dashboard'),
    pill(a.status)
  );
  box.append(header);
  box.append(node('p', `${formatDate(a.time_window?.start_time)} → ${formatDate(a.time_window?.end_time)} (IST)`, 'muted'));

  const statGrid = node('div', undefined, 'platform-grid');
  statGrid.append(
    statCard('Items Scanned', a.metrics.items_checked, '📊'),
    statCard('Relevant Items', a.metrics.relevant_items, '🎯'),
    statCard('Sources Found', a.metrics.sources_discovered, '🔍'),
    statCard('Duration', a.duration_seconds + 's', '⏱️')
  );
  box.append(statGrid);

  if (a.errors?.length) {
    const issueBox = node('div', undefined, 'notice-banner');
    issueBox.style.cssText = 'background:#fef2f2;border:1px solid #fecaca;border-left:4px solid #ef4444;color:#991b1b;margin:12px 0;padding:12px 16px;border-radius:8px;';
    issueBox.textContent = '⚠️ ' + a.errors.map(e => errorMessages[e] || e).join(' · ');
    box.append(issueBox);
  }

  if (platform === 'web' && a.records?.length > 0) {
    const snippets = a.records.filter(r => r.event?.metadata?.collection_scope === 'search_snippet_only');
    if (snippets.length > 0) {
      const banner = node('div');
      banner.style.cssText = 'background:#fffbeb;border:1px solid #fde68a;border-left:4px solid #f59e0b;color:#92400e;margin:12px 0;padding:12px 16px;border-radius:8px;font-size:14px;';
      banner.textContent = `ℹ️ ${snippets.length} of ${a.records.length} web results are short search snippets. Increase "Pages to fetch" in Settings to get full article text.`;
      box.append(banner);
    }
  }

  const exportRow = node('div', undefined, 'actions');
  exportRow.append(
    action('📄 Download CSV', () => download(runId, 'normalized', 'csv')),
    action('🖨️ Print / Save PDF', () => { window.print(); })
  );
  box.append(exportRow);

  box.append(node('h3', 'Top Relevant Records'));
  const recordsGrid = node('div', undefined, 'dimension-grid');
  renderRecords(recordsGrid, a.records, true);
  box.append(recordsGrid);

  $('platform-report').replaceChildren(box);
}

function statCard(label, value, icon) {
  const card = node('div', undefined, 'panel stat-card');
  card.style.cssText = 'text-align: center; padding: 20px; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 1px solid #e2e8f0; background: #fafafa;';
  const val = node('div', value, 'stat-value');
  val.style.cssText = 'font-size: 28px; font-weight: 800; margin: 8px 0; color: #0f172a;';
  card.append(node('div', icon, 'stat-icon'), val, node('div', label, 'stat-label'));
  return card;
}

/* ── Record Cards (simplified, no raw JSON) ── */
function recordCard(item) {
  const e = item.event, a = item.analysis, card = node('article', undefined, 'result');
  const title = node('h3');
  title.append(link(e.title || e.metadata?.title || e.content?.slice(0, 120) || e.item_id, e.url));

  // Platform & account row
  const topRow = node('div', undefined, 'result-top');
  const platformIcon = { youtube: '▶️', instagram: '📷', news: '📰', web: '🌐', meta: '👤' }[e.platform] || '📌';
  topRow.textContent = `${platformIcon} ${names[e.platform] || e.platform} · ${e.account || e.source_id}`;
  card.append(topRow, title);

  // Status pills
  card.append(pill(a.time_classification, a.time_classification));
  if (a.relevant) card.append(node('span', '🎯 Relevant', 'pill complete'));

  // Snippet vs full-text badge for web
  if (e.platform === 'web') {
    const scope = e.metadata?.collection_scope;
    if (scope === 'search_snippet_only') card.append(node('span', '🔍 Snippet only', 'pill snippet'));
    else if (scope === 'public_page_text') card.append(node('span', '📄 Full article', 'pill fulltext'));
  }

  // Transcript badge
  if (e.metadata?.transcript_text) {
    card.append(node('span', '🎙️ Has spoken transcript', 'pill transcript'));
  }

  // Content preview
  const content = (e.content || '').slice(0, 600);
  if (content) card.append(node('p', content));

  // Transcript preview
  if (e.metadata?.transcript_text) {
    const tBox = node('div', undefined, 'transcript-box');
    const preview = e.metadata.transcript_text.length > 250 ? e.metadata.transcript_text.slice(0, 250) + '…' : e.metadata.transcript_text;
    tBox.textContent = '🎙️ Transcript: ' + preview;
    card.append(tBox);
  }

  // Date & relevance summary
  card.append(node('p', `Published: ${formatDate(e.published_at)} · Collected: ${formatDate(e.collected_at)}`, 'muted'));

  // Matched terms (simplified)
  const matchedParts = Object.entries(a.matches || {}).filter(([, v]) => Array.isArray(v) && v.length > 0).map(([k, v]) => `${names[k]}: ${v.join(', ')}`);
  if (matchedParts.length) {
    card.append(node('p', '🎯 Matched: ' + matchedParts.join(' · '), 'muted'));
  }

  // Only "Open original" link — no raw JSON or analysis details
  card.append(action('🔗 Open original', () => { window.open(e.url, '_blank'); }));

  return card;
}

function renderRecords(target, items, append = false) {
  if (!append) target.replaceChildren();
  if (!items || !items.length) target.append(empty('No records found.'));
  else items.forEach(i => target.append(recordCard(i)));
}

function renderEvents(target, events) {
  target.replaceChildren();
  if (!events?.length) { target.append(empty('No key findings yet. Run an audit first.')); return; }
  for (const e of events) {
    const c = node('article', undefined, 'result');
    c.append(
      node('h3', e.title),
      pill(e.evidence_level),
      node('p', e.summary),
      node('p', `${e.source_count} sources · ${e.platforms.map(p => names[p]).join(', ')} · First seen: ${formatDate(e.first_seen_at)}`, 'muted'),
      action('View supporting records', async () => {
        const items = await api('/api/records?' + new URLSearchParams({ run_id: e.run_id }));
        $('dialog-title').textContent = 'Supporting Records';
        renderRecords($('dialog-body'), items.filter(i => e.record_ids.includes(i.id)));
        $('detail-dialog').showModal();
      })
    );
    target.append(c);
  }
}

/* ── History ── */
async function history() {
  const runs = await api('/api/audits');
  $('run-list').replaceChildren();
  if (!runs.length) $('run-list').append(empty('No past audits.'));
  for (const run of runs) {
    const statusIcon = { complete: '✅', failed: '❌', partial: '⚠️' }[run.status] || '📋';
    $('run-list').append(action(`${statusIcon} ${formatDate(run.started_at)}`, async () => {
      state.selectedRun = run.id;
      await historyReport(run.id);
    }));
  }
  if (state.selectedRun) await historyReport(state.selectedRun);
}

async function historyReport(id) {
  const r = await api('/api/audits/' + id), box = summaryCard(r);
  if (!r.platforms) return;
  for (const [p, a] of Object.entries(r.platforms)) {
    const statusIcon = { complete: '✅', failed: '❌', partial: '⚠️', disabled: '—' }[a.status] || '';
    box.append(action(`${statusIcon} ${names[p]} — ${a.metrics?.relevant_items ?? 0} relevant`, async () => {
      await navigate('platforms');
      await platformReport(id, p);
    }));
  }
  $('history-report').replaceChildren(box);
}

/* ── Search ── */
for (const [key, label, choices] of [
  ['q', 'Search text'],
  ['platform', 'Platform', ['', 'youtube', 'instagram', 'news', 'meta', 'web']],
  ['source', 'Source / account'],
  ['classification', 'Time period', ['CURRENT', 'STALE', 'UNKNOWN_TIME', 'AFTER_WINDOW', '']],
  ['entities', 'Entity / phrase'],
  ['keywords', 'Keyword'],
  ['hashtags', 'Hashtag'],
  ['geography', 'Location'],
  ['incident_types', 'Incident type'],
  ['start_time', 'From date'],
  ['end_time', 'To date']
]) {
  const l = node('label', label), input = document.createElement(choices ? 'select' : 'input');
  input.name = key;
  if (key === 'q') { input.id = 'search-q'; input.placeholder = 'e.g. "rescue operation" or flood or earthquake'; }
  else if (key === 'entities') { input.placeholder = '"United Nations" or exact phrase'; }
  if (choices) {
    for (const v of choices) {
      const displayText = { '': 'All', 'CURRENT': 'Current (within window)', 'STALE': 'Old / stale', 'UNKNOWN_TIME': 'Unknown date', 'AFTER_WINDOW': 'After window' }[v] || (names[v] || v);
      const o = node('option', displayText);
      o.value = v;
      input.append(o);
    }
  } else {
    input.type = key.endsWith('_time') ? 'datetime-local' : 'search';
  }
  l.append(input);
  $('search-fields').append(l);
}

// Bind search chips
setTimeout(() => {
  const q = $('search-q');
  if (q) {
    const c1 = $('chip-boolean'); if (c1) c1.onclick = () => { q.value = '("Ooty" OR "ऊटी") AND ("Indian Army") -filter:retweets'; q.focus(); };
    const c2 = $('chip-or'); if (c2) c2.onclick = () => { q.value = 'flood or earthquake or landslide'; q.focus(); };
    const c3 = $('chip-phrase'); if (c3) c3.onclick = () => { q.value = '"rescue operation"'; q.focus(); };
  }
}, 50);

async function search() {
  const p = new URLSearchParams();
  for (const [k, v] of new FormData($('search-form'))) {
    if (v) p.set(k, k.endsWith('_time') ? new Date(v).toISOString() : v);
  }
  renderRecords($('record-results'), await api('/api/search?' + p));
}

$('search-form').addEventListener('submit', e => { e.preventDefault(); search().catch(e => notice(e.message)); });

/* ── Sources ── */
async function sourceDetail(platform, id) {
  const hist = await api('/api/source-history?' + new URLSearchParams({ platform, source_id: id })),
        body = $('dialog-body');
  body.replaceChildren();
  for (const s of hist) {
    const card = node('article', undefined, 'panel');
    card.append(
      node('h3', 'Audit — ' + formatDate(s.last_audited)),
      pill(s.status),
      table([['Checked', s.items_checked], ['Relevant', s.relevant_items], ['New', s.new_items]])
    );
    body.append(card);
  }
  $('dialog-title').textContent = names[platform] + ' · ' + id;
  if (!$('detail-dialog').open) $('detail-dialog').showModal();
}

async function sources() {
  const items = await api('/api/sources');
  $('source-results').replaceChildren();
  if (!items.length) $('source-results').append(empty('No sources found yet. Run an audit first.'));
  for (const s of items) {
    const card = node('article', undefined, 'panel');
    card.append(
      node('h3', `${names[s.platform]} · ${s.source_id}`),
      table([['Last seen', formatDate(s.last_seen_at)], ['Failures', s.failure_count]]),
      action('View history', () => sourceDetail(s.platform, s.source_id))
    );
    $('source-results').append(card);
  }
}

async function alerts() {
  const items = await api('/api/alerts');
  $('alert-results').replaceChildren();
  if (!items.length) $('alert-results').append(empty('No alerts right now.'));
  for (const a of items) {
    const card = node('article', undefined, 'panel');
    card.append(
      node('h3', '🚨 Relevance Alert'),
      pill(a.evidence_level),
      node('p', formatDate(a.created_at)),
      action('Review', async () => {
        const items = await api('/api/records?run_id=' + a.run_id);
        $('dialog-title').textContent = 'Alert Record';
        renderRecords($('dialog-body'), items.filter(i => i.id === a.record_id));
        $('detail-dialog').showModal();
      })
    );
    $('alert-results').append(card);
  }
}

/* ── Export (CSV + Print-to-PDF) ── */
async function download(runId, kind, format) {
  const r = await fetch('/api/export?' + new URLSearchParams({ run_id: runId, kind, format }), {
    headers: { 'X-Watchtower-Token': document.querySelector('meta[name=watchtower-token]').content }
  });
  if (!r.ok) throw new Error('Export failed');
  const u = URL.createObjectURL(await r.blob()), a = document.createElement('a');
  a.href = u; a.download = `watchtower-report-${runId.slice(0, 8)}.${format}`; a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}

/* ── Instagram Settings ── */
async function instagramStatus() {
  const s = await api('/api/instagram');
  $('ig-username').value = s.username;
  $('ig-status').textContent = s.error ? (errorMessages[s.error] || s.error) : (s.status || 'Not connected');
}

bind('ig-configure', async () => {
  const file = $('ig-session').files[0];
  if (!file) throw new Error('Select a session file first.');
  if (file.size > 1024 * 1024) throw new Error('File too large (max 1 MB).');
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  await api('/api/instagram/configure', { username: $('ig-username').value, session_data: btoa(binary) });
  $('ig-session').value = '';
  await instagramStatus();
  notice('✅ Instagram session imported! Test the connection to verify.');
});

bind('ig-test', async () => {
  $('ig-status').textContent = 'Testing…';
  const r = await api('/api/instagram/test', {});
  $('ig-status').textContent = r.error ? (errorMessages[r.error] || r.error) : '✅ ' + r.status;
});

bind('ig-find', async () => {
  const r = await api('/api/instagram/search', {
    search: $('ig-search').value,
    minimum: $('ig-min').value === '' ? null : Number($('ig-min').value),
    maximum: $('ig-max').value === '' ? null : Number($('ig-max').value)
  });
  $('ig-results').replaceChildren();
  if (r.error) { $('ig-results').append(empty(errorMessages[r.error] || r.error)); return; }
  if (!r.profiles?.length) { $('ig-results').append(empty('No public profiles found.')); return; }
  for (const p of r.profiles) {
    const c = node('article', undefined, 'result');
    c.append(
      link('@' + p.username + ' · ' + p.display_name, p.url),
      node('p', p.biography),
      table([['Followers', p.followers?.toLocaleString('en-IN')], ['Posts', p.post_count]]),
      action('➕ Monitor this account', async () => {
        state.profile.saved_sources.instagram = [...new Set([...(state.profile.saved_sources.instagram || []), p.username])];
        await saveProfile();
        renderSaved();
        notice(`✅ @${p.username} added to monitoring!`);
      })
    );
    $('ig-results').append(c);
  }
});

bind('save-schedule', async () => {
  const s = await api('/api/schedule', {
    enabled: $('schedule-enabled').checked,
    interval_minutes: Number($('schedule-minutes').value)
  });
  $('schedule-next').textContent = s.next_run_at ? 'Next run: ' + formatDate(new Date(s.next_run_at * 1000).toISOString()) : 'Schedule disabled';
  notice('✅ Schedule saved.');
});

$('close-dialog').addEventListener('click', () => $('detail-dialog').close());

/* ── Polling ── */
async function poll() {
  if (state.polling) return;
  state.polling = true;
  try {
    state.status = await api('/api/status');
    $('run-state').textContent = state.status.running ? '⏳ Audit running' : '✅ Ready';
    $('run-state').className = 'pill ' + (state.status.running ? 'running' : 'complete');
    $('run-audit').disabled = state.status.running;
    const runs = await api('/api/audits');
    if (runs.length) {
      state.latest = await api('/api/audits/' + runs[0].id);
      $('overview').replaceChildren(summaryCard(state.latest));
      platformCards($('dashboard-platforms'), state.latest);
      platformCards($('platform-cards'), state.latest);
      renderEvents($('latest-events'), await api('/api/incidents?run_id=' + runs[0].id));
      if (state.view === 'run') {
        $('live-report').replaceChildren(summaryCard(state.latest));
        if (state.latest.platforms) {
          for (const [p, a] of Object.entries(state.latest.platforms)) {
            const icon = { complete: '✅', failed: '❌', partial: '⚠️', running: '⏳' }[a.status] || '';
            $('live-report').append(node('p', `${icon} ${names[p]}: ${a.metrics.items_checked} items, ${a.metrics.relevant_items} relevant`));
          }
        }
      }
    } else {
      $('overview').replaceChildren(empty('Welcome! Go to Setup Profile to create your first monitoring profile.'));
      platformCards($('dashboard-platforms'), null);
      platformCards($('platform-cards'), null);
    }
  } catch (e) {
    notice('Could not refresh: ' + e.message);
  } finally {
    state.polling = false;
  }
}

async function init() {
  state.profile = await api('/api/profile');
  state.capabilities = await api('/api/platforms');
  for (const category of Object.keys(state.profile.dimensions))
    state.values[category] = await api('/api/values/' + category);
  renderProfile();
  await poll();
  if (state.status) {
    $('schedule-enabled').checked = state.status.schedule.enabled;
    $('schedule-minutes').value = state.status.schedule.interval_minutes;
  }
  setInterval(poll, 2500);
}

init().catch(e => notice('Could not load: ' + e.message));
