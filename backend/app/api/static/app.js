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
  instagram: 'Instagram Scraper',
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

function showRaw(title, data) {
  $('dialog-title').textContent = title;
  const body = $('dialog-body');
  body.replaceChildren();
  const pre = node('pre');
  pre.textContent = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  body.append(pre);
  if (!$('detail-dialog').open) $('detail-dialog').showModal();
}

/* ── Templates ── */
const templates = {
  dashboard: '<div id="overview"></div><h2>Platform Overview</h2><div id="dashboard-platforms" class="platform-grid"></div><h2>Recent Findings</h2><div id="latest-events"></div>',

  instagram: `<div id="ig-session-bar" class="ig-status-bar disconnected"><div class="ig-status-pill"><span class="ig-status-dot"></span><span id="ig-session-text">Session Required</span></div><div class="actions"><button id="ig-test-btn">Test Connection</button><button id="ig-toggle-setup">Setup / Change Session</button></div></div><div id="ig-quick-connect" class="ig-quick-card" hidden><div><p><strong>Local Session File Detected!</strong> We found <code id="ig-quick-filename">session file</code> on your machine.</p><p class="muted">You can connect to Instagram with 1-click without copying cookies or terminal commands.</p></div><button id="ig-quick-btn" class="primary">Connect Local Session</button></div><div id="ig-setup-panel" class="panel" hidden><h2>Instagram Connection Setup</h2><p>Connect your Instagram account using browser cookies. No terminal commands or password storage; cookies remain strictly on this computer.</p><details class="ig-guide"><summary>📖 How to get your cookies in 30 seconds (Click to expand)</summary><ol><li>Open <a href="https://www.instagram.com" target="_blank" rel="noopener">instagram.com</a> and log into your account.</li><li>Press <strong>F12</strong> (or Right-click &rarr; <strong>Inspect</strong>).</li><li>Go to <strong>Application</strong> (or <strong>Storage</strong> in Firefox) &rarr; <strong>Cookies</strong> &rarr; <code>https://www.instagram.com</code>.</li><li>Copy the value of <strong>sessionid</strong> and <strong>csrftoken</strong> and paste them below!</li></ol></details><div class="limit-grid" style="margin-top:14px"><label>Instagram Username<input id="ig-auth-user" placeholder="e.g. jacethepint" autocomplete="off"></label><label>sessionid Cookie<input id="ig-auth-sessionid" type="password" placeholder="Paste sessionid value"></label><label>csrftoken Cookie<input id="ig-auth-csrftoken" type="password" placeholder="Paste csrftoken value"></label></div><div class="actions" style="margin-top:14px"><button id="ig-save-cookies" class="primary">Save & Connect</button><button id="ig-show-file-upload">Or Upload Session File</button></div><div id="ig-file-upload-box" class="actions" style="margin-top:10px" hidden><input id="ig-file-input" type="file" accept=".json"><button id="ig-upload-btn">Upload & Connect</button></div></div><div class="panel"><div class="ig-tabs"><button id="tab-ig-profile" class="ig-tab active">👤 Profile Posts</button><button id="tab-ig-hashtag" class="ig-tab"># Hashtag Feed</button><button id="tab-ig-discover" class="ig-tab">🔍 Discover Accounts</button></div><div id="ig-mode-profile"><div class="limit-grid"><label style="grid-column:span 2">Instagram Username<input id="ig-target-user" placeholder="e.g. indianarmy.adgpi, defence_mania"></label><label>Post Limit<select id="ig-target-limit"><option value="5">5 posts</option><option value="10" selected>10 posts</option><option value="20">20 posts</option><option value="50">50 posts</option></select></label></div><div class="ig-chips"><span class="muted" style="font-size:12px;align-self:center">Try:</span><span class="ig-chip" data-chip="indianarmy.adgpi">@indianarmy.adgpi</span><span class="ig-chip" data-chip="defence_academy_dharmshala_">@defence_academy_dharmshala_</span><span class="ig-chip" data-chip="defence_mania">@defence_mania</span></div><div class="actions" style="margin-top:16px"><button id="ig-scrape-btn" class="primary">Scrape Profile Posts</button></div></div><div id="ig-mode-hashtag" hidden><div class="limit-grid"><label style="grid-column:span 2">Hashtag Name<input id="ig-target-tag" placeholder="e.g. indianarmy, defence"></label><label>Post Limit<select id="ig-tag-limit"><option value="5">5 posts</option><option value="10" selected>10 posts</option><option value="20">20 posts</option><option value="50">50 posts</option></select></label></div><div class="ig-chips"><span class="muted" style="font-size:12px;align-self:center">Try:</span><span class="ig-chip-tag" data-chip="indianarmy">#indianarmy</span><span class="ig-chip-tag" data-chip="defence">#defence</span><span class="ig-chip-tag" data-chip="indianairforce">#indianairforce</span></div><div class="actions" style="margin-top:16px"><button id="ig-scrape-tag-btn" class="primary">Scrape Hashtag</button></div></div><div id="ig-mode-discover" hidden><div class="limit-grid"><label>Search Keyword<input id="ig-disc-term" placeholder="e.g. defence, army, airforce"></label><label>Min Followers<input id="ig-disc-min" type="number" min="0" placeholder="Optional"></label><label>Max Followers<input id="ig-disc-max" type="number" min="0" placeholder="Optional"></label></div><div class="actions" style="margin-top:16px"><button id="ig-discover-btn" class="primary">Search Accounts</button></div><div id="ig-discover-results" style="margin-top:18px"></div></div></div><div id="ig-scrape-loading" class="ig-loader" hidden><div class="ig-spinner"></div><span id="ig-scrape-status-text">Fetching data from Instagram...</span></div><div id="ig-profile-card"></div><div id="ig-results-toolbar" class="actions" style="justify-content:space-between;margin:18px 0 12px" hidden><h3 id="ig-results-title">Scraped Posts (0)</h3><div class="actions"><button id="ig-export-json">Export JSON</button><button id="ig-export-csv">Export CSV</button><button id="ig-add-source" class="primary">+ Add to Monitored Sources</button></div></div><div id="ig-posts-container" class="ig-posts-grid"></div>`,

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
  if (view === 'instagram') await initInstagramView();
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
  const platformIcons = { youtube: '📺', instagram: '📷', news: '📰', meta: '👥', web: '🌐' };
  for (const platform of ['youtube', 'instagram', 'news', 'meta', 'web']) {
    const queries = state.profile.platform_queries?.[platform] || [];
    const card = node('article', undefined, 'dimension pq-card');
    const head = node('header');
    const icon = platformIcons[platform] || '🔍';
    head.append(node('label', `${icon} ${names[platform]} Queries`, 'check'));
    card.append(head);

    const tagWrap = node('div', undefined, 'pq-tag-list');
    if (queries.length === 0) {
      tagWrap.append(node('p', 'No custom queries yet. Add one below.', 'muted'));
    } else {
      for (const value of queries) {
        const tag = node('span', undefined, 'pq-tag');
        tag.append(node('span', value));
        const removeBtn = document.createElement('button');
        removeBtn.className = 'pq-tag-remove';
        removeBtn.textContent = '✕';
        removeBtn.title = 'Remove query';
        removeBtn.addEventListener('click', () => {
          state.profile.platform_queries[platform] = state.profile.platform_queries[platform].filter(v => v !== value);
          renderPlatformQueries();
          notice('Save profile to apply this change.');
        });
        tag.append(removeBtn);
        tagWrap.append(tag);
      }
    }
    card.append(tagWrap);

    const count = node('p', `${queries.length} ${queries.length === 1 ? 'query' : 'queries'}`, 'muted');
    card.append(count);

    const inputRow = node('div', undefined, 'pq-input-row');
    const input = document.createElement('input');
    input.placeholder = `Add ${names[platform].toLowerCase()} query — e.g. "exact phrase" or keyword`;
    input.maxLength = 500;
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') addBtn.click();
    });
    const addBtn = action('+ Add', () => {
      const value = input.value.trim();
      if (!value) throw new Error('Enter a query');
      if (!state.profile.platform_queries) state.profile.platform_queries = {};
      state.profile.platform_queries[platform] = [...new Set([...(state.profile.platform_queries[platform] || []), value])];
      input.value = '';
      renderPlatformQueries();
      notice('Query added! Click Save Profile to keep it.');
    });
    inputRow.append(input, addBtn);
    card.append(inputRow);

    $('platform-queries').append(card);
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

/* ── Dedicated Instagram Scraper & Session Wizard ── */
let igScrapedData = { profile: null, records: [] };
let igInitialized = false;

async function initInstagramView() {
  await refreshInstagramStatus();
  if (!igInitialized) {
    setupInstagramEventListeners();
    igInitialized = true;
  }
}

async function refreshInstagramStatus() {
  try {
    const s = await api('/api/instagram');
    const bar = $('ig-session-bar');
    const text = $('ig-session-text');
    if (s.configured) {
      bar.className = 'ig-status-bar connected';
      text.textContent = `Connected as @${s.username}${s.status ? ' (' + s.status + ')' : ''}`;
      if ($('ig-quick-connect')) $('ig-quick-connect').hidden = true;
    } else {
      bar.className = 'ig-status-bar disconnected';
      text.textContent = 'Instagram Session Required';
      if (s.has_local_file && $('ig-quick-connect')) {
        $('ig-quick-connect').hidden = false;
        if ($('ig-quick-filename') && s.local_filename) $('ig-quick-filename').textContent = s.local_filename;
        if ($('ig-quick-btn')) $('ig-quick-btn').textContent = `Connect ${s.detected_username ? '@' + s.detected_username : 'Local Session'}`;
      }
    }
    if (s.username && $('ig-auth-user') && !$('ig-auth-user').value) $('ig-auth-user').value = s.username;
  } catch (e) {
    notice('Could not check Instagram session: ' + e.message);
  }
}

function setupInstagramEventListeners() {
  const tabs = {
    'tab-ig-profile': 'ig-mode-profile',
    'tab-ig-hashtag': 'ig-mode-hashtag',
    'tab-ig-discover': 'ig-mode-discover'
  };
  for (const [tabId, modeId] of Object.entries(tabs)) {
    const tabElem = $(tabId);
    if (!tabElem) continue;
    tabElem.addEventListener('click', () => {
      for (const t of Object.keys(tabs)) {
        $(t)?.classList.toggle('active', t === tabId);
        const m = $(tabs[t]);
        if (m) m.hidden = t !== tabId;
      }
    });
  }

  $('ig-toggle-setup')?.addEventListener('click', () => {
    const p = $('ig-setup-panel');
    if (p) p.hidden = !p.hidden;
  });

  document.querySelectorAll('.ig-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      if ($('ig-target-user')) $('ig-target-user').value = chip.dataset.chip;
    });
  });

  document.querySelectorAll('.ig-chip-tag').forEach(chip => {
    chip.addEventListener('click', () => {
      if ($('ig-target-tag')) $('ig-target-tag').value = chip.dataset.chip;
    });
  });

  bind('ig-quick-btn', async () => {
    notice('Connecting local session...');
    const res = await api('/api/instagram/configure', { use_local_file: true });
    await refreshInstagramStatus();
    notice(`Connected successfully as @${res.username || 'user'}!`);
  });

  bind('ig-test-btn', async () => {
    notice('Testing connection to Instagram…');
    const r = await api('/api/instagram/test', {});
    if (r.status === 'Connected') {
      notice('Instagram connection active & verified!');
    } else {
      notice('Connection issue: ' + (errors[r.error] || r.error || 'Check session'));
    }
    await refreshInstagramStatus();
  });

  bind('ig-save-cookies', async () => {
    const username = $('ig-auth-user').value.trim();
    const sessionid = $('ig-auth-sessionid').value.trim();
    const csrftoken = $('ig-auth-csrftoken').value.trim();
    if (!username) throw new Error('Enter your Instagram username');
    if (!sessionid || !csrftoken) throw new Error('Both sessionid and csrftoken cookies are required');
    notice('Saving cookies...');
    await api('/api/instagram/configure', { username, sessionid, csrftoken });
    $('ig-auth-sessionid').value = '';
    $('ig-auth-csrftoken').value = '';
    if ($('ig-setup-panel')) $('ig-setup-panel').hidden = true;
    await refreshInstagramStatus();
    notice('Instagram cookies configured successfully!');
  });

  $('ig-show-file-upload')?.addEventListener('click', () => {
    const b = $('ig-file-upload-box');
    if (b) b.hidden = !b.hidden;
  });

  bind('ig-upload-btn', async () => {
    const file = $('ig-file-input')?.files?.[0];
    const username = $('ig-auth-user').value.trim();
    if (!username) throw new Error('Enter your Instagram username first');
    if (!file) throw new Error('Choose an Instaloader JSON session file');
    if (file.size > 1024 * 1024) throw new Error('File must be 1MB or smaller');
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
    await api('/api/instagram/configure', { username, session_data: btoa(binary) });
    if ($('ig-setup-panel')) $('ig-setup-panel').hidden = true;
    await refreshInstagramStatus();
    notice('Session file uploaded and configured!');
  });

  bind('ig-scrape-btn', async () => {
    const target = $('ig-target-user').value.trim();
    const limit = Number($('ig-target-limit').value || 10);
    if (!target) throw new Error('Enter an Instagram username to scrape');
    $('ig-scrape-loading').hidden = false;
    $('ig-scrape-status-text').textContent = `Scraping posts for @${target}...`;
    try {
      const res = await api('/api/instagram/scrape', { type: 'profile', target, limit });
      if (res.error) throw new Error(errors[res.error] || res.error);
      igScrapedData = res;
      renderScrapedProfile(res.profile);
      renderScrapedPosts(res.records || []);
      notice(`Scraped ${res.records?.length || 0} posts from @${target}!`);
    } finally {
      $('ig-scrape-loading').hidden = true;
    }
  });

  bind('ig-scrape-tag-btn', async () => {
    const target = $('ig-target-tag').value.trim();
    const limit = Number($('ig-tag-limit').value || 10);
    if (!target) throw new Error('Enter a hashtag to scrape');
    $('ig-scrape-loading').hidden = false;
    $('ig-scrape-status-text').textContent = `Scraping posts for #${target}...`;
    $('ig-profile-card').replaceChildren();
    try {
      const res = await api('/api/instagram/scrape', { type: 'hashtag', target, limit });
      if (res.error) throw new Error(errors[res.error] || res.error);
      igScrapedData = res;
      renderScrapedPosts(res.records || []);
      notice(`Scraped ${res.records?.length || 0} posts for #${target}!`);
    } finally {
      $('ig-scrape-loading').hidden = true;
    }
  });

  bind('ig-discover-btn', async () => {
    const search = $('ig-disc-term').value.trim();
    const minVal = $('ig-disc-min').value;
    const maxVal = $('ig-disc-max').value;
    if (!search) throw new Error('Enter a search keyword');
    const container = $('ig-discover-results');
    container.replaceChildren(node('p', 'Searching Instagram accounts...', 'muted'));
    const res = await api('/api/instagram/search', {
      search,
      minimum: minVal === '' ? null : Number(minVal),
      maximum: maxVal === '' ? null : Number(maxVal)
    });
    container.replaceChildren();
    if (res.error) {
      container.append(empty(errors[res.error] || res.error));
      return;
    }
    if (!res.profiles?.length) {
      container.append(empty('No matching public profiles discovered.'));
      return;
    }
    for (const p of res.profiles) {
      const card = node('article', undefined, 'result');
      card.append(link(`@${p.username} · ${p.display_name || ''}`, p.url));
      if (p.biography) card.append(node('p', p.biography));
      card.append(table([
        ['Followers', Number(p.followers || 0).toLocaleString()],
        ['Following', Number(p.following || 0).toLocaleString()],
        ['Posts', Number(p.post_count || 0).toLocaleString()]
      ]));
      const actionsDiv = node('div', undefined, 'actions');
      actionsDiv.append(
        action('Scrape This Account', () => {
          $('tab-ig-profile').click();
          $('ig-target-user').value = p.username;
          $('ig-scrape-btn').click();
        }, 'primary'),
        action('+ Monitor in Profile', async () => {
          state.profile.saved_sources.instagram = [...new Set([...(state.profile.saved_sources.instagram || []), p.username])];
          await saveProfile();
          renderSaved();
          notice(`@${p.username} added to saved sources!`);
        })
      );
      card.append(actionsDiv);
      container.append(card);
    }
  });

  $('ig-export-json')?.addEventListener('click', () => {
    if (!igScrapedData.records?.length) return;
    const blob = new Blob([JSON.stringify(igScrapedData, null, 2)], { type: 'application/json' });
    downloadBlob(blob, `instagram-scraped-${Date.now()}.json`);
  });

  $('ig-export-csv')?.addEventListener('click', () => {
    if (!igScrapedData.records?.length) return;
    const rows = [['Shortcode', 'URL', 'Username', 'Published At', 'Likes', 'Comments', 'Caption']];
    for (const r of igScrapedData.records) {
      rows.push([
        r.shortcode || '',
        `https://www.instagram.com/p/${r.shortcode}/`,
        r.username || '',
        r.published_at || '',
        r.engagement?.likes ?? 0,
        r.engagement?.comments ?? 0,
        (r.caption || '').replace(/"/g, '""').replace(/\n/g, ' ')
      ]);
    }
    const csv = rows.map(r => r.map(c => `"${c}"`).join(',')).join('\n');
    downloadBlob(new Blob([csv], { type: 'text/csv;charset=utf-8;' }), `instagram-scraped-${Date.now()}.csv`);
  });

  $('ig-add-source')?.addEventListener('click', async () => {
    const username = igScrapedData.profile?.username || igScrapedData.records?.[0]?.username;
    if (!username) return;
    state.profile.saved_sources.instagram = [...new Set([...(state.profile.saved_sources.instagram || []), username])];
    await saveProfile();
    renderSaved();
    notice(`@${username} successfully added to Watchtower Monitored Sources!`);
  });
}

function downloadBlob(blob, filename) {
  const u = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = u;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}

function renderScrapedProfile(p) {
  const container = $('ig-profile-card');
  container.replaceChildren();
  if (!p) return;
  const card = node('div', undefined, 'ig-profile-header');
  const avatar = node('div', (p.display_name || p.username || 'IG').slice(0, 2).toUpperCase(), 'ig-avatar');
  const info = node('div', undefined, 'ig-profile-info');
  const nameHeading = node('h2', p.display_name || p.username, 'ig-profile-name');
  nameHeading.append(link(` @${p.username}`, p.url));
  if (p.verified_account) {
    const v = node('span', ' ✔ Verified', 'pill complete');
    v.style.marginLeft = '8px';
    nameHeading.append(v);
  }
  const statsRow = node('div', undefined, 'ig-stats-row');
  statsRow.innerHTML = `<span><strong>${Number(p.followers || 0).toLocaleString()}</strong> followers</span><span><strong>${Number(p.following || 0).toLocaleString()}</strong> following</span><span><strong>${Number(p.post_count || 0).toLocaleString()}</strong> posts</span>`;
  info.append(nameHeading, statsRow, node('p', p.biography || ''));
  card.append(avatar, info);
  container.append(card);
}

function renderScrapedPosts(records) {
  const container = $('ig-posts-container');
  container.replaceChildren();
  $('ig-results-toolbar').hidden = !records?.length;
  $('ig-results-title').textContent = `Scraped Posts (${records?.length || 0})`;
  if (!records?.length) {
    container.append(empty('No posts found for this query.'));
    return;
  }
  for (const post of records) {
    const card = node('article', undefined, 'ig-post-card');
    const preview = node('div', undefined, 'ig-post-preview');
    const imgUrl = post.media?.[0]?.url;
    const isVideo = post.media?.[0]?.type === 'video' || post.raw_node?.is_video;
    if (imgUrl) {
      const img = document.createElement('img');
      img.src = imgUrl;
      img.alt = post.caption?.slice(0, 60) || 'Post media';
      img.loading = 'lazy';
      img.referrerPolicy = 'no-referrer';
      preview.append(img);
    } else {
      preview.append(node('span', isVideo ? '🎬 Video' : '📷 Photo', 'muted'));
    }
    preview.append(node('span', isVideo ? '🎬 Video' : '📷 Photo', 'ig-badge'));
    const body = node('div', undefined, 'ig-post-body');
    const meta = node('div', undefined, 'ig-post-meta');
    meta.append(
      link(`🔗 ${post.shortcode}`, `https://www.instagram.com/p/${post.shortcode}/`),
      node('span', date(post.published_at))
    );
    const caption = node('p', post.caption || 'No caption text', 'ig-post-caption');
    const eng = node('div', undefined, 'ig-post-engagement');
    eng.innerHTML = `<span>❤️ ${(post.engagement?.likes ?? 0).toLocaleString()} likes</span><span>💬 ${(post.engagement?.comments ?? 0).toLocaleString()} comments</span>`;
    const postActions = node('div', undefined, 'actions');
    postActions.style.marginTop = '10px';
    postActions.append(
      action('Inspect Raw', () => showRaw(`Post ${post.shortcode}`, post)),
      action('Copy Link', () => {
        navigator.clipboard.writeText(`https://www.instagram.com/p/${post.shortcode}/`);
        notice('Copied post URL to clipboard!');
      })
    );
    body.append(meta, caption, eng, postActions);
    card.append(preview, body);
    container.append(card);
  }
}
