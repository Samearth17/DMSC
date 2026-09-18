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
  related: 'Find Related Coverage',
  profile: 'Setup Profile',
  run: 'Start Audit',
  history: 'Past Audits',
  platforms: 'Platform Results',
  records: 'Search Records',
  events: 'Key Findings',
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
    'complete': 'Complete',
    'failed': 'Failed',
    'partial': 'Partial',
    'running': 'Running',
    'disabled': 'Disabled',
    'CURRENT': 'Current',
    'STALE': 'Old',
    'UNKNOWN_TIME': 'Unknown date',
    'AFTER_WINDOW': 'After window'
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

  instagram: `<div id="ig-session-bar" class="ig-status-bar disconnected"><div class="ig-status-pill"><span class="ig-status-dot"></span><span id="ig-session-text">Session Required</span></div><div class="actions"><button id="ig-test-btn">Test Connection</button><button id="ig-toggle-setup">Setup / Change Session</button></div></div><div id="ig-quick-connect" class="ig-quick-card" hidden><div><p><strong>Local Session File Detected!</strong> We found <code id="ig-quick-filename">session file</code> on your machine.</p><p class="muted">You can connect to Instagram with 1-click without copying cookies or terminal commands.</p></div><button id="ig-quick-btn" class="primary">Connect Local Session</button></div><div id="ig-setup-panel" class="panel" hidden><h2>Instagram Connection Setup</h2><p>Connect your Instagram account using browser cookies. No terminal commands or password storage; cookies remain strictly on this computer.</p><details class="ig-guide"><summary>How to get your cookies in 30 seconds (Click to expand)</summary><ol><li>Open <a href="https://www.instagram.com" target="_blank" rel="noopener">instagram.com</a> and log into your account.</li><li>Press <strong>F12</strong> (or Right-click &rarr; <strong>Inspect</strong>).</li><li>Go to <strong>Application</strong> (or <strong>Storage</strong> in Firefox) &rarr; <strong>Cookies</strong> &rarr; <code>https://www.instagram.com</code>.</li><li>Copy the value of <strong>sessionid</strong> and <strong>csrftoken</strong> and paste them below!</li></ol></details><div class="limit-grid" style="margin-top:14px"><label>Instagram Username<input id="ig-auth-user" placeholder="e.g. jacethepint" autocomplete="off"></label><label>sessionid Cookie<input id="ig-auth-sessionid" type="password" placeholder="Paste sessionid value"></label><label>csrftoken Cookie<input id="ig-auth-csrftoken" type="password" placeholder="Paste csrftoken value"></label></div><div class="actions" style="margin-top:14px"><button id="ig-save-cookies" class="primary">Save & Connect</button><button id="ig-show-file-upload">Or Upload Session File</button></div><div id="ig-file-upload-box" class="actions" style="margin-top:10px" hidden><input id="ig-file-input" type="file" accept=".json"><button id="ig-upload-btn">Upload & Connect</button></div></div><div class="panel"><div class="ig-tabs"><button id="tab-ig-profile" class="ig-tab active">Profile Posts</button><button id="tab-ig-hashtag" class="ig-tab">Hashtag Feed</button><button id="tab-ig-discover" class="ig-tab">Discover Accounts</button></div><div id="ig-mode-profile"><div class="limit-grid"><label style="grid-column:span 2">Instagram Username<input id="ig-target-user" placeholder="e.g. indianarmy.adgpi, defence_mania"></label><label>Post Limit<select id="ig-target-limit"><option value="5">5 posts</option><option value="10" selected>10 posts</option><option value="20">20 posts</option><option value="50">50 posts</option></select></label><label>Timeline / Period<select id="ig-target-time"><option value="all" selected>All recent (by limit)</option><option value="24">Last 24 hours</option><option value="48">Last 48 hours</option><option value="168">Last 7 days</option><option value="720">Last 30 days</option><option value="custom">Custom date range</option></select></label></div><div id="ig-target-custom" class="limit-grid" style="margin-top:10px" hidden><label>From Date<input id="ig-target-since" type="datetime-local"></label><label>To Date<input id="ig-target-until" type="datetime-local"></label></div><div class="ig-chips"><span class="muted" style="font-size:12px;align-self:center">Try:</span><span class="ig-chip" data-chip="indianarmy.adgpi">@indianarmy.adgpi</span><span class="ig-chip" data-chip="defence_academy_dharmshala_">@defence_academy_dharmshala_</span><span class="ig-chip" data-chip="defence_mania">@defence_mania</span></div><div class="actions" style="margin-top:16px"><button id="ig-scrape-btn" class="primary">Scrape Profile Posts</button></div></div><div id="ig-mode-hashtag" hidden><div class="limit-grid"><label style="grid-column:span 2">Hashtag Name<input id="ig-target-tag" placeholder="e.g. indianarmy, defence"></label><label>Post Limit<select id="ig-tag-limit"><option value="5">5 posts</option><option value="10" selected>10 posts</option><option value="20">20 posts</option><option value="50">50 posts</option></select></label><label>Timeline / Period<select id="ig-tag-time"><option value="all" selected>All recent (by limit)</option><option value="24">Last 24 hours</option><option value="48">Last 48 hours</option><option value="168">Last 7 days</option><option value="720">Last 30 days</option><option value="custom">Custom date range</option></select></label></div><div id="ig-tag-custom" class="limit-grid" style="margin-top:10px" hidden><label>From Date<input id="ig-tag-since" type="datetime-local"></label><label>To Date<input id="ig-tag-until" type="datetime-local"></label></div><div class="ig-chips"><span class="muted" style="font-size:12px;align-self:center">Try:</span><span class="ig-chip-tag" data-chip="indianarmy">#indianarmy</span><span class="ig-chip-tag" data-chip="defence">#defence</span><span class="ig-chip-tag" data-chip="indianairforce">#indianairforce</span></div><div class="actions" style="margin-top:16px"><button id="ig-scrape-tag-btn" class="primary">Scrape Hashtag</button></div></div><div id="ig-mode-discover" hidden><div class="limit-grid"><label>Search Keyword<input id="ig-disc-term" placeholder="e.g. defence, army, airforce"></label><label>Min Followers<input id="ig-disc-min" type="number" min="0" placeholder="Optional"></label><label>Max Followers<input id="ig-disc-max" type="number" min="0" placeholder="Optional"></label></div><div class="actions" style="margin-top:16px"><button id="ig-discover-btn" class="primary">Search Accounts</button></div><div id="ig-discover-results" style="margin-top:18px"></div></div></div><div id="ig-scrape-loading" class="ig-loader" hidden><div class="ig-spinner"></div><span id="ig-scrape-status-text">Fetching data from Instagram...</span></div><div id="ig-profile-card"></div><div id="ig-results-toolbar" class="actions" style="justify-content:space-between;margin:18px 0 12px" hidden><h3 id="ig-results-title">Scraped Posts (0)</h3><div class="actions"><button id="ig-export-json">Export JSON</button><button id="ig-export-csv">Export CSV</button><button id="ig-add-source" class="primary">+ Save Account to Profile</button></div></div><div id="ig-posts-container" class="ig-posts-grid"></div>`,

  related: `<div class="panel">
    <h2>Find Related News Coverage</h2>
    <p>Upload a news article or paste news text/URL to discover coverage across all platforms (News, YouTube, Web, Instagram, Facebook/Meta). Watchtower conjoins your distinguishing anchor terms to scrape and calculate coverage similarity.</p>
    <div class="limit-grid">
      <label style="grid-column:span 2">Upload News Text File (.txt or .md)
        <input id="related-file" type="file" accept=".txt,.md,text/plain,text/markdown">
      </label>
      <label style="grid-column:span 2">Or Paste News / Article Text (20–20,000 characters)
        <textarea id="related-text" rows="6" maxlength="20000" placeholder="Paste the news story, article body, or incident report here..."></textarea>
      </label>
      <label style="grid-column:span 2">Original News / Story URL (Optional)
        <input id="related-url" type="url" placeholder="https://example.com/news-story-url">
      </label>
    </div>
    <div style="margin:12px 0">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <label style="margin:0"><strong>Required Anchor Terms (2–8 terms, one per line)</strong></label>
        <button id="related-suggest-btn" type="button" class="small">Auto-Suggest Anchors</button>
      </div>
      <p class="muted" style="margin:0 0 8px;font-size:12px">Key distinguishing names, places, and incident terms. All anchors will be matched to eliminate false positives.</p>
      <textarea id="related-anchors" rows="4" placeholder="Example:&#10;Secunderabad&#10;Defence Cantonment&#10;Bolarum"></textarea>
    </div>
    <h3>Platforms to Scrape</h3>
    <div id="related-platforms" class="platform-grid"></div>
    <label style="margin-top:12px;max-width:320px">Coverage Time Window
      <select id="related-hours">
        <option value="24" selected>Last 24 hours</option>
        <option value="48">Last 48 hours</option>
        <option value="168">Last 7 days</option>
        <option value="720">Last 30 days</option>
      </select>
    </label>
    <div class="actions" style="margin-top:16px">
      <button id="related-preview">Preview Queries</button>
      <button id="related-run" class="primary">Scrape & Find Related Coverage</button>
    </div>
    <div id="related-preview-result" style="margin-top:14px"></div>
  </div>
  <div id="related-results" style="margin-top:18px"></div>`,

  profile: '<div class="section-heading"><p>Set up your monitoring profile — add keywords, enable platforms, and save.</p><div class="actions" style="gap:8px"><button id="clear-all-values-btn" class="small" style="background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;">Clear All Saved Queries</button><button id="save-profile" class="primary">Save Profile</button></div></div><label class="name-field">Profile name<input id="profile-name" maxlength="120" placeholder="e.g. Regional Intel Monitor"></label><div id="dimensions" class="dimension-grid"></div><div class="panel"><h2>Topic & Relevance Filtering</h2><p>Control how Watchtower scores intelligence relevance and suppresses non-target noise.</p><div class="limit-grid"><label style="grid-column:span 2">Relevance Mode<select id="relevance-mode"><option value="keyword_required" selected>Keyword-Required (Strict topic match; requires your keywords/entities)</option><option value="all_categories">All Categories Required (AND - requires entity + keyword + location)</option><option value="any_category">Broad Match (Any matched keyword/hashtag)</option></select></label><label style="grid-column:span 2">Exclude Noise Terms (Comma separated)<input id="relevance-exclude-terms" placeholder="festivals, shopping, lifestyle, retail, promotions, vlogs"></label></div></div><h2>Platforms to Monitor</h2><div id="platform-select" class="platform-grid"></div><div class="panel"><h2>Platform Specific Queries</h2><p>Override global dimensions for specific platforms. These take priority.</p><div id="platform-queries"></div></div><div class="panel"><h2>Saved Accounts & Feeds</h2><p>Add Instagram accounts or RSS news feeds to monitor directly.</p><div id="saved-sources"></div></div>',

  run: '<div class="panel"><h2>Start New Audit</h2><p id="run-summary"></p><p>All enabled platforms will be scanned simultaneously. Results appear in real-time.</p><div class="limit-grid"><label>Time window<select id="window-hours"><option value="1">Last 1 hour</option><option value="6">Last 6 hours</option><option value="12">Last 12 hours</option><option value="24" selected>Last 24 hours</option><option value="48">Last 48 hours</option><option value="168">Last 7 days</option><option value="custom">Custom range</option></select></label><label>Timezone<input id="window-zone" value="Asia/Kolkata" readonly></label></div><div id="custom-window" class="limit-grid" hidden><label>From<input id="window-start" type="datetime-local"></label><label>To<input id="window-end" type="datetime-local"></label></div><div class="actions"><button id="preview-plan">Preview Queries</button><button id="run-audit" class="primary">Run Audit Now</button></div><div id="query-plan"></div></div><div id="live-report"></div>',

  history: '<div class="history-layout"><div id="run-list" class="panel"></div><div id="history-report"></div></div>',

  platforms: '<div id="platform-cards" class="platform-grid"></div><div id="platform-report"></div>',

  records: '<div class="search-guide-box"><div class="guide-header"><strong>Search Tips</strong></div><div class="guide-chips"><span class="guide-chip" id="chip-boolean">Boolean: <code>("Ooty" OR "ऊटी") AND ("Rescue Team")</code></span><span class="guide-chip" id="chip-or">Multi-term: <code>flood or earthquake or landslide</code></span><span class="guide-chip" id="chip-phrase">Exact phrase: <code>"rescue operation"</code></span></div></div><form id="search-form" class="panel"><div id="search-fields" class="limit-grid"></div><p>Search across all past audit results. Supports Boolean queries and exact phrases.</p><button type="submit" class="primary">Search</button></form><div id="record-results"></div>',

  events: '<p>Key findings grouped by similarity. Review each for verification.</p><div id="event-results"></div>',

  settings: '<div class="panel" id="settings-policies-panel"><h2>Collection Settings</h2><p>Adjust how many items to fetch, timeout budgets, and page counts per platform.</p><div id="settings-policies"></div><div class="actions"><button id="save-settings-policies" class="primary">Save Settings</button></div></div><div class="panel" id="settings-transcription-panel"><h2>Video & Audio Transcription (WhisperFlow / Whisper)</h2><p>Extract spoken audio dialogue from YouTube videos and Instagram reels to evaluate keyword and entity relevance.</p><div id="transcription-status-box" class="notice-banner" style="background:#f0fdf4;border:1px solid #bbf7d0;border-left:4px solid #22c55e;color:#166534;margin:12px 0;padding:12px 16px;border-radius:8px;"><strong id="transcription-status-badge">Local Engine: Installed (openai-whisper)</strong><p id="transcription-status-notes" style="margin:4px 0 0;font-size:13px;"></p></div><div class="notice-banner" style="background:#f8fafc;border:1px solid #cbd5e1;border-left:4px solid #0284c7;color:#0f172a;margin:14px 0 12px;padding:12px 16px;border-radius:8px;"><strong>System Protection: Strictly On-Demand Video Processing</strong><p style="margin:4px 0 0;font-size:13px;line-height:1.45;color:#334155;">Audits and general scrapes <strong>never</strong> download or transcribe videos in bulk. That would freeze your system and exhaust RAM/disk. Instead, Watchtower only collects lightweight text metadata. Audio transcription runs <strong>strictly for your desired video only</strong> when you click <strong>\'Transcribe Audio\'</strong> on that specific card, or inspect a single desired video below.</p></div><div class="limit-grid"><label>Engine Mode<select id="transcribe-mode"><option value="whisper">Local Whisper (Runs on this Mac)</option><option value="whisperflow_api">WhisperFlow / OpenAI Cloud API</option></select></label><label>Local Whisper Model<select id="transcribe-model"><option value="tiny">tiny (Fastest, low memory)</option><option value="base" selected>base (Recommended)</option><option value="small">small (Higher accuracy)</option><option value="medium">medium (Best accuracy)</option></select></label><label id="transcribe-key-wrap" style="grid-column:span 2">WhisperFlow / OpenAI API Key (Optional for Cloud Mode)<input id="transcribe-api-key" type="password" placeholder="Enter API key (sk-...) for cloud transcription"></label><label id="transcribe-endpoint-wrap" style="grid-column:span 2">API Endpoint URL (Optional)<input id="transcribe-api-endpoint" placeholder="https://api.openai.com/v1/audio/transcriptions"></label></div><div class="actions" style="margin-top:14px"><button id="save-transcription-btn" class="primary">Save Transcription Settings</button></div><details open style="margin-top:16px;background:#f8fafc;padding:14px 16px;border-radius:8px;border:1px solid #e2e8f0"><summary style="cursor:pointer;font-weight:700;color:var(--blue)">Inspect & Transcribe Single Video Target</summary><p style="margin:6px 0 10px;font-size:13px;color:#475569;">Extract dialogue, threat/relevance scores, and intelligence from <strong>one single desired video</strong> without scraping unrelated feeds.</p><div class="limit-grid" style="margin-top:8px"><label style="grid-column:span 2">Desired Video URL (YouTube, Instagram Reel, etc.)<input id="test-transcribe-url" placeholder="https://www.youtube.com/watch?v=... or https://www.instagram.com/reel/..."></label></div><div class="actions" style="margin-top:10px;display:flex;gap:8px;"><button id="test-transcribe-btn">Transcribe Desired Video</button><button id="save-transcribe-video-btn" class="primary">Transcribe & Save to Records</button></div><div id="test-transcribe-result" style="margin-top:12px" hidden></div></details></div><div class="panel"><h2>Instagram Connection</h2><p>Import your Instaloader session file to enable Instagram monitoring.</p><div class="limit-grid"><label>Username<input id="ig-username" autocomplete="off" placeholder="your_username"></label><label>Session file<input id="ig-session" type="file"></label></div><div class="actions"><button id="ig-configure">Import Session</button><button id="ig-test">Test Connection</button></div><p id="ig-status"></p></div><div class="panel"><h2>Find Instagram Profiles</h2><p>Search public profiles to add them for monitoring.</p><div class="limit-grid"><label>Search<input id="ig-search" placeholder="e.g. kashmir news"></label><label>Min followers<input id="ig-min" type="number" min="0"></label><label>Max followers<input id="ig-max" type="number" min="0"></label></div><button id="ig-find">Search</button><div id="ig-results"></div></div><div class="panel"><h2>Scheduled Audits</h2><p>Automatically run audits at regular intervals in the background.</p><div class="limit-grid"><label class="check" style="grid-column:span 2"><input id="schedule-enabled" type="checkbox"> Enable auto-schedule</label><label style="grid-column:span 2">Frequency<select id="schedule-frequency"><option value="360">Every 6 hours</option><option value="720">Every 12 hours</option><option value="1440" selected>Once daily (every 24 hours)</option><option value="2880">Every 2 days (48 hours)</option><option value="10080">Weekly (7 days)</option><option value="custom">Custom interval</option></select></label><label id="schedule-custom-wrap" style="grid-column:span 2" hidden>Custom interval (minutes)<input id="schedule-minutes" type="number" min="5" max="10080" value="1440"></label></div><div class="actions" style="margin-top:12px"><button id="save-schedule" class="primary">Save Schedule</button></div><div id="schedule-status-card" class="notice-banner" style="margin-top:14px;display:flex;align-items:center;gap:12px;padding:12px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"><span id="schedule-status-dot" class="status-dot"></span><div><strong id="schedule-status-title">Schedule Inactive</strong><p id="schedule-next" style="margin:2px 0 0;font-size:13px;color:var(--text-muted);"></p></div></div></div><div class="panel"><h2>Database & History Maintenance</h2><p>Purge previously collected records, past audits, and irrelevant historical scrapes to start clean.</p><button id="purge-past-records-btn" style="background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;padding:8px 14px;border-radius:6px;font-weight:600;cursor:pointer;">Purge All Past Audit Records & History</button><p class="muted" style="margin:6px 0 0;font-size:12px;">This permanently clears past records from SQLite without resetting your profile settings or keywords.</p></div>'
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
  if (view === 'related') renderRelatedPlatforms();
  if (view === 'instagram') await initInstagramView();
  if (view === 'history') await history();
  if (view === 'records') await search();
  if (view === 'events') renderEvents($('event-results'), await api('/api/incidents'));
  if (view === 'settings') { await instagramStatus(); renderSettingsPolicies(); await renderTranscriptionSettings(); }
  if (view === 'run') runSummary();
}

/* ── Profile Management ── */
function renderDimension(category) {
  const d = state.profile.dimensions[category];
  // Auto-enable if dimension has active values configured
  if (d.values && d.values.length > 0 && !d.enabled) {
    d.enabled = true;
  }
  const card = node('article', undefined, 'dimension'),
        head = node('header'),
        label = node('label', names[category] || category, 'check'),
        enabled = document.createElement('input');
  enabled.type = 'checkbox';
  enabled.checked = d.enabled;
  label.prepend(enabled);

  const statusBadge = node('span', '', 'dim-status-badge');
  function updateBadge() {
    if (d.enabled && d.values.length > 0) {
      statusBadge.textContent = 'Active';
      statusBadge.className = 'dim-status-badge active';
      card.classList.remove('dim-card-paused');
    } else if (d.values.length > 0 && !d.enabled) {
      statusBadge.textContent = 'Paused';
      statusBadge.className = 'dim-status-badge paused';
      card.classList.add('dim-card-paused');
    } else {
      statusBadge.textContent = 'Empty';
      statusBadge.className = 'dim-status-badge empty';
      card.classList.remove('dim-card-paused');
    }
  }
  updateBadge();

  enabled.addEventListener('change', () => {
    d.enabled = enabled.checked;
    updateBadge();
    draw();
  });
  head.append(label, statusBadge);
  card.append(head);

  const toolbar = node('div', undefined, 'dim-toolbar');
  const count = node('span', '', 'dim-count');
  const filter = document.createElement('input');
  filter.type = 'search';
  filter.className = 'dim-filter';
  filter.placeholder = `Filter ${names[category].toLowerCase()}…`;
  toolbar.append(filter);

  const list = node('div', undefined, 'values');
  const selAll = node('button', 'Select All', 'small');
  selAll.type = 'button';
  selAll.onclick = () => {
    d.values = state.values[category].map(v => v.value);
    if (d.values.length > 0) {
      d.enabled = true;
      enabled.checked = true;
    }
    updateBadge();
    draw();
    notice('All selected. Click "Save Profile" to apply.');
  };
  const clearAll = node('button', 'Clear All', 'small');
  clearAll.type = 'button';
  clearAll.onclick = () => {
    d.values = [];
    updateBadge();
    draw();
    notice('Cleared all. Click "Save Profile" to apply.');
  };
  const toolsRight = node('div', undefined, 'actions');
  toolsRight.style.gap = '6px';
  toolsRight.append(selAll, clearAll);
  toolbar.append(count, toolsRight);

  function draw() {
    list.replaceChildren();
    if (!d.enabled && d.values.length > 0) {
      const pausedNotice = node('div', undefined, 'dim-paused-banner');
      const pText = node('span');
      pText.innerHTML = `<strong>${names[category]} is paused.</strong> Category is unchecked in header.`;
      const activateBtn = node('button', 'Activate This Category', 'small');
      activateBtn.type = 'button';
      activateBtn.style.cssText = 'align-self:flex-start;background:var(--blue);color:#fff;border:none;border-radius:4px;cursor:pointer;padding:4px 8px;font-weight:600;margin-top:4px;';
      activateBtn.onclick = () => {
        d.enabled = true;
        enabled.checked = true;
        updateBadge();
        draw();
        notice(`${names[category]} activated. Click "Save Profile" to save.`);
      };
      pausedNotice.append(pText, activateBtn);
      list.append(pausedNotice);
    }
    for (const value of state.values[category].filter(v => v.value.toLowerCase().includes(filter.value.toLowerCase()))) {
      const row = node('div', undefined, 'value-row'),
            l = node('label', value.value, 'check'),
            check = document.createElement('input');
      check.type = 'checkbox';
      check.checked = d.values.includes(value.value);
      if (check.checked) {
        row.style.background = '#f0fdf4';
      }
      check.addEventListener('change', () => {
        if (check.checked) {
          d.values = [...new Set([...d.values, value.value])];
          // Auto-enable category when user activates an item
          d.enabled = true;
          enabled.checked = true;
        } else {
          d.values = d.values.filter(v => v !== value.value);
        }
        updateBadge();
        draw();
      });
      l.prepend(check);
      row.append(l, action('Remove', async () => {
        await api(`/api/values/${category}/${value.id}`, undefined, 'DELETE');
        d.values = d.values.filter(v => v !== value.value);
        state.values[category] = await api('/api/values/' + category);
        updateBadge();
        draw();
      }, 'small'));
      list.append(row);
    }
    if (!list.children.length) list.append(node('p', 'No values yet. Add one below.', 'muted'));
    count.textContent = `${d.values.length} of ${state.values[category].length} active`;
  }
  filter.addEventListener('input', draw);
  draw();

  const add = document.createElement('input');
  add.placeholder = 'Add new ' + names[category].toLowerCase() + '…';
  add.maxLength = 200;
  add.addEventListener('keydown', e => {
    if (e.key === 'Enter') addAction.click();
  });
  const addAction = action('+ Add', async () => {
    const val = add.value.trim();
    if (!val) return;
    await api('/api/values/' + category, { value: val });
    state.values[category] = await api('/api/values/' + category);
    if (!d.values.includes(val)) d.values.push(val);
    d.enabled = true;
    enabled.checked = true;
    add.value = '';
    updateBadge();
    draw();
    notice(`Added and selected "${val}". Click "Save Profile" to save your profile.`);
  });
  card.append(toolbar, list, add, addAction);
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
  const rel = p.relevance || { mode: 'keyword_required', exclude_terms: [] };
  const modeVal = rel.mode === 'defense_focus' ? 'keyword_required' : (rel.mode || 'keyword_required');
  if ($('relevance-mode')) $('relevance-mode').value = modeVal;
  if ($('relevance-exclude-terms')) $('relevance-exclude-terms').value = (rel.exclude_terms || []).join(', ');
  runSummary();
}

function localInput(v) {
  const d = new Date(v);
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function renderPlatformQueries() {
  $('platform-queries').replaceChildren();
  for (const platform of ['youtube', 'instagram', 'news', 'meta', 'web']) {
    const queries = state.profile.platform_queries?.[platform] || [];
    const card = node('article', undefined, 'dimension pq-card');
    const head = node('header');
    head.append(node('label', `${names[platform]} Queries`, 'check'));
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
        removeBtn.textContent = '×';
        removeBtn.title = 'Remove query';
        removeBtn.addEventListener('click', async () => {
          state.profile.platform_queries[platform] = state.profile.platform_queries[platform].filter(v => v !== value);
          renderPlatformQueries();
          await saveProfile();
          notice(`Removed query from ${names[platform] || platform}.`);
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
    const addBtn = action('+ Add', async () => {
      const value = input.value.trim();
      if (!value) throw new Error('Enter a query');
      if (!state.profile.platform_queries) state.profile.platform_queries = {};
      state.profile.platform_queries[platform] = [...new Set([...(state.profile.platform_queries[platform] || []), value])];
      input.value = '';
      renderPlatformQueries();
      await saveProfile();
      notice(`Custom query added for ${names[platform] || platform}.`);
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
      row.append(node('span', value), action('×', () => {
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
  // Resilience: ensure any dimension that has active values is enabled if nothing is enabled
  const anyActive = Object.values(p.dimensions).some(d => d.enabled && d.values && d.values.length > 0);
  if (!anyActive) {
    for (const d of Object.values(p.dimensions)) {
      if (d.values && d.values.length > 0) {
        d.enabled = true;
      }
    }
  }
  const h = $('window-hours').value;
  p.time_window = { hours: h === 'custom' ? null : Number(h), timezone: 'Asia/Kolkata' };
  if (h === 'custom') {
    const start = new Date($('window-start').value), end = new Date($('window-end').value);
    if (isNaN(start) || isNaN(end)) throw new Error('Choose both start and end dates');
    p.time_window.start_time = start.toISOString();
    p.time_window.end_time = end.toISOString();
  }
  p.platform_queries = state.profile.platform_queries || {};
  const relMode = $('relevance-mode') ? $('relevance-mode').value : 'keyword_required';
  const relExcludes = $('relevance-exclude-terms') && $('relevance-exclude-terms').value
    ? $('relevance-exclude-terms').value.split(',').map(s => s.trim()).filter(Boolean)
    : [];
  p.relevance = { mode: relMode, exclude_terms: relExcludes };
  return p;
}

async function saveProfile() {
  const saved = await api('/api/profile', collectProfile());
  state.profile = saved;
  runSummary();
  notice('Profile saved successfully.');
}

function runSummary() {
  if (state.profile) {
    const platforms = Object.entries(state.profile.platforms).filter(([, v]) => v).map(([p]) => names[p]).join(', ');
    const pqCounts = Object.entries(state.profile.platform_queries || {})
      .filter(([plat, qlist]) => state.profile.platforms[plat] && qlist && qlist.length > 0)
      .map(([plat, qlist]) => `${names[plat] || plat}: ${qlist.length} custom ${qlist.length === 1 ? 'query' : 'queries'}`);
    const pqText = pqCounts.length ? ` · Custom queries: [${pqCounts.join(' · ')}]` : '';
    $('run-summary').textContent = `${state.profile.name} · ${platforms || 'No platforms selected'}${pqText}`;
  }
}

bind('save-profile', saveProfile);
bind('save-settings-policies', async () => { await saveProfile(); renderSettingsPolicies(); });
bind('purge-past-records-btn', async () => {
  if (!confirm('Are you sure you want to delete all past audit runs and collected records from the database? This cannot be undone.')) return;
  await api('/api/records/purge', {});
  notice('All past records and audit history have been purged from the database.');
  if (state.view === 'history') await history();
  if (state.view === 'records') await search();
});
$('window-hours').addEventListener('change', () => $('custom-window').hidden = $('window-hours').value !== 'custom');

let planQueriesOpen = false;
bind('preview-plan', async () => {
  const container = $('query-plan');
  const btn = $('preview-plan');
  if (planQueriesOpen) {
    container.replaceChildren();
    planQueriesOpen = false;
    btn.textContent = 'Preview Queries';
    return;
  }
  await saveProfile();
  const plan = await api('/api/plan');
  container.replaceChildren();
  let totalQueries = 0;
  for (const [p, queries] of Object.entries(plan)) {
    if (!queries.length) continue;
    totalQueries += queries.length;
    const list = node('ol');
    queries.forEach(q => {
      const li = node('li');
      const textSpan = node('span', q.text);
      if (q.dimension === 'platform_query') {
        const badge = node('span', 'platform', 'pq-badge');
        li.append(textSpan, ' ', badge);
      } else if (q.dimension === 'saved_source') {
        const badge = node('span', 'source', 'pq-badge source-badge');
        li.append(textSpan, ' ', badge);
      } else {
        li.append(textSpan, node('span', ` (${q.dimension})`, 'muted'));
      }
      list.append(li);
    });
    container.append(details(`${names[p]} — ${queries.length} queries`, list));
  }
  if (totalQueries === 0) {
    const emptyBox = node('div', undefined, 'empty-plan-notice');
    emptyBox.style.cssText = 'padding:12px 14px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;margin:8px 0;display:flex;align-items:center;justify-content:space-between;gap:12px;';
    const msg = node('p', 'No queries generated. Please ensure at least one platform and category (e.g. Keywords) has active values in Setup Profile.');
    msg.style.cssText = 'margin:0;color:#92400e;font-size:13px;';
    const goBtn = node('button', 'Setup Profile', 'small primary');
    goBtn.type = 'button';
    goBtn.onclick = () => navigate('profile');
    emptyBox.append(msg, goBtn);
    container.append(emptyBox);
  }
  planQueriesOpen = true;
  btn.textContent = 'Hide Queries';
});

bind('run-audit', async () => {
  planQueriesOpen = false;
  $('query-plan').replaceChildren();
  $('preview-plan').textContent = 'Preview Queries';
  await saveProfile();
  const r = await api('/api/run', {});
  state.selectedRun = r.run_id;
  notice('Audit started. All platforms running in parallel. Results will appear below.');
  await poll();
});

/* ── Related Coverage Search ── */
function renderRelatedPlatforms() {
  const box = $('related-platforms');
  if (!box || box.childElementCount) return;
  for (const p of ['news', 'youtube', 'web', 'meta', 'instagram']) {
    const label = node('label', names[p], 'check'), input = document.createElement('input');
    input.type = 'checkbox';
    input.value = p;
    input.checked = ['news', 'web', 'youtube'].includes(p);
    label.prepend(input);
    box.append(label);
  }
}

function relatedPayload() {
  const platforms = {};
  if ($('related-platforms')) {
    $('related-platforms').querySelectorAll('input').forEach(i => { platforms[i.value] = i.checked; });
  }
  const text = $('related-text') ? $('related-text').value.trim() : '';
  const url = $('related-url') ? $('related-url').value.trim() : '';
  const anchors = $('related-anchors') ? $('related-anchors').value.split('\n').map(t => t.trim()).filter(Boolean) : [];
  return {
    seed: { text, url, anchors },
    platforms,
    time_window: { hours: Number($('related-hours')?.value || 24), timezone: 'Asia/Kolkata' }
  };
}

bind('clear-all-values-btn', async () => {
  if (!confirm('Are you sure you want to clear all saved keywords, hashtags, and values? This will give you a fresh, blank profile.')) return;
  await api('/api/values/clear-all', {}, 'POST');
  state.profile = await api('/api/profile');
  state.values = {
    geography: await api('/api/values/geography'),
    entities: await api('/api/values/entities'),
    keywords: await api('/api/values/keywords'),
    hashtags: await api('/api/values/hashtags'),
    incident_types: await api('/api/values/incident_types')
  };
  renderProfile();
  notice('All saved queries cleared. You now have a fresh, blank profile.');
});

bind('related-suggest-btn', async () => {
  const text = $('related-text').value.trim();
  if (!text || text.length < 20) {
    notice('Please paste or upload at least 20 characters of news text first to suggest anchors.');
    return;
  }
  try {
    const res = await api('/api/related/suggest-anchors', { text });
    if (res.anchors && res.anchors.length) {
      $('related-anchors').value = res.anchors.slice(0, 6).join('\n');
      notice(`Auto-suggested ${res.anchors.length} anchor terms from the news text.`);
    } else {
      notice('Could not extract distinguishing anchors. Please type 2-8 anchor terms manually.');
    }
  } catch (e) {
    notice('Error suggesting anchors: ' + e.message);
  }
});

bind('related-preview', async () => {
  const payload = relatedPayload();
  if (!payload.seed.text || payload.seed.text.length < 20) {
    notice('Paste or upload at least 20 characters of news text.');
    return;
  }
  if (payload.seed.anchors.length < 2) {
    notice('Enter at least 2 distinguishing anchor terms (names, places, incident).');
    return;
  }
  try {
    const result = await api('/api/related/preview', payload);
    const box = $('related-preview-result');
    box.replaceChildren(node('p', result.scope, 'muted'));
    let count = 0;
    Object.entries(result.queries || {}).forEach(([p, queries]) => {
      if (queries.length) {
        count += queries.length;
        box.append(node('h4', `${names[p] || p} (${queries.length} queries)`), ...queries.map(q => node('p', q.text)));
      }
    });
    if (count === 0) {
      box.append(node('p', 'No queries generated. Please select at least one platform.'));
    }
  } catch (e) {
    notice(e.message);
  }
});

bind('related-run', async () => {
  const payload = relatedPayload();
  if (!payload.seed.text || payload.seed.text.length < 20) {
    notice('Paste or upload at least 20 characters of news text.');
    return;
  }
  if (payload.seed.anchors.length < 2) {
    notice('Enter at least 2 distinguishing anchor terms (names, places, incident).');
    return;
  }
  try {
    const result = await api('/api/related/run', payload);
    state.selectedRun = result.run_id;
    $('related-results').replaceChildren();
    const loadingCard = node('div', undefined, 'panel');
    loadingCard.innerHTML = '<h3>Scraping all platforms for related coverage...</h3><p class="muted">Scanning News, YouTube, Web, and social sources for matching anchor terms...</p>';
    $('related-results').append(loadingCard);
    notice('Related coverage search started. Scraping platforms now...');

    const pollRelated = async () => {
      if (!document.contains($('related-results'))) return;
      try {
        const report = await api('/api/audits/' + result.run_id);
        const box = $('related-results');
        box.replaceChildren(
          node('h2', 'Related Coverage Results'),
          pill(report.status),
          table(Object.entries(report.platforms).map(([p, a]) => [names[p] || p, `${a.status} · ${a.metrics.items_checked} scanned · ${a.metrics.relevant_items} matched`]))
        );
        if (report.status === 'running') {
          setTimeout(pollRelated, 2000);
          return;
        }
        const records = await api('/api/records?run_id=' + encodeURIComponent(result.run_id));
        const relevant = records.filter(i => i.analysis.relevant).sort((a, b) => (b.analysis.relevance_score || 0) - (a.analysis.relevance_score || 0));
        box.append(node('p', `Found ${relevant.length} related candidates (${records.length - relevant.length} records filtered out).`));
        if (relevant.length === 0) {
          box.append(node('p', 'No related candidates found matching all anchors across selected platforms.', 'muted'));
        } else {
          relevant.forEach(i => box.append(recordCard(i)));
        }
        if (records.length > relevant.length) {
          const det = node('details');
          det.style.marginTop = '14px';
          det.append(node('summary', `Filtered records (${records.length - relevant.length}) — Click to expand`));
          records.filter(i => !i.analysis.relevant).forEach(i => det.append(recordCard(i)));
          box.append(det);
        }
      } catch (e) {
        notice(e.message);
      }
    };
    pollRelated();
  } catch (e) {
    notice(e.message);
  }
});

// File upload for related news
setTimeout(() => {
  const fileInput = $('related-file');
  if (fileInput) {
    fileInput.addEventListener('change', async () => {
      const file = fileInput.files[0];
      if (!file) return;
      if (file.size > 80000 || !/\.(txt|md)$/i.test(file.name)) {
        notice('Upload a UTF-8 .txt or .md file up to 80 KB.');
        return;
      }
      const text = (await file.text()).slice(0, 20000);
      $('related-text').value = text;
      try {
        const res = await api('/api/related/suggest-anchors', { text });
        if (res.anchors && res.anchors.length) {
          $('related-anchors').value = res.anchors.slice(0, 6).join('\n');
          notice(`Loaded "${file.name}" and auto-suggested ${res.anchors.length} anchors.`);
        } else {
          notice(`Loaded "${file.name}". Please enter 2-8 anchor terms below.`);
        }
      } catch {
        notice(`Loaded "${file.name}". Please enter 2-8 anchor terms below.`);
      }
    });
  }
}, 500);


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
    action('Download CSV', () => download(report.id, 'normalized', 'csv')),
    action('Print / Save PDF', () => { window.print(); })
  );
  box.append(exportRow);
  return box;
}

function platformCards(target, report) {
  target.replaceChildren();
  for (const platform of ['youtube', 'instagram', 'news', 'x', 'reddit', 'meta', 'web']) {
    const a = report?.platforms?.[platform], card = node('article', undefined, 'platform');
    const status = a?.status || 'disabled';
    const header = node('div', undefined, 'platform-card-header');
    header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;';
    header.append(node('h3', names[platform]), pill(status));
    card.append(
      header,
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
    statCard('Items Scanned', a.metrics.items_checked),
    statCard('Relevant Items', a.metrics.relevant_items),
    statCard('Sources Found', a.metrics.sources_discovered),
    statCard('Duration', a.duration_seconds + 's')
  );
  box.append(statGrid);

  if (a.errors?.length) {
    const issueBox = node('div', undefined, 'notice-banner');
    issueBox.style.cssText = 'background:#fef2f2;border:1px solid #fecaca;border-left:4px solid #ef4444;color:#991b1b;margin:12px 0;padding:12px 16px;border-radius:8px;';
    issueBox.textContent = a.errors.map(e => errorMessages[e] || e).join(' · ');
    box.append(issueBox);
  }

  if (platform === 'web' && a.records?.length > 0) {
    const snippets = a.records.filter(r => r.event?.metadata?.collection_scope === 'search_snippet_only');
    if (snippets.length > 0) {
      const banner = node('div');
      banner.style.cssText = 'background:#fffbeb;border:1px solid #fde68a;border-left:4px solid #f59e0b;color:#92400e;margin:12px 0;padding:12px 16px;border-radius:8px;font-size:14px;';
      banner.textContent = `${snippets.length} of ${a.records.length} web results are short search snippets. Increase "Pages to fetch" in Settings to get full article text.`;
      box.append(banner);
    }
  }

  const exportRow = node('div', undefined, 'actions');
  exportRow.append(
    action('Download CSV', () => download(runId, 'normalized', 'csv')),
    action('Print / Save PDF', () => { window.print(); })
  );
  box.append(exportRow);

  const relevant = (a.records || []).filter(r => r.analysis?.relevant);
  const filteredOut = (a.records || []).filter(r => !r.analysis?.relevant);

  if (relevant.length > 0) {
    box.append(node('h3', `Relevant Records (${relevant.length})`));
    const recordsGrid = node('div', undefined, 'dimension-grid');
    renderRecords(recordsGrid, relevant, true);
    box.append(recordsGrid);
  } else {
    box.append(empty('No records met your relevance criteria in this time window.'));
  }

  if (filteredOut.length > 0) {
    const details = document.createElement('details');
    details.style.cssText = 'margin-top:20px;padding:14px 16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;';
    const summary = document.createElement('summary');
    summary.style.cssText = 'cursor:pointer;font-weight:600;color:#475569;';
    summary.textContent = `Other Scanned Items (${filteredOut.length}) — Filtered Out as Old / Non-Relevant`;
    details.append(summary);
    details.append(node('p', 'These items were scanned by the collector but were evaluated as Old / Stale or lacking sufficient keyword relevance.', 'muted'));
    const filteredGrid = node('div', undefined, 'dimension-grid');
    renderRecords(filteredGrid, filteredOut, true);
    details.append(filteredGrid);
    box.append(details);
  }

  $('platform-report').replaceChildren(box);
}

function statCard(label, value) {
  const card = node('div', undefined, 'panel stat-card');
  card.style.cssText = 'text-align: center; padding: 20px; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 1px solid #e2e8f0; background: #fafafa; border-radius: 10px;';
  const val = node('div', value, 'stat-value');
  val.style.cssText = 'font-size: 28px; font-weight: 800; margin: 4px 0 6px; color: #0f172a;';
  const lbl = node('div', label, 'stat-label');
  lbl.style.cssText = 'font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #64748b;';
  card.append(val, lbl);
  return card;
}

/* ── Record Cards (simplified, no raw JSON) ── */
function recordCard(item) {
  const e = item.event, a = item.analysis, card = node('article', undefined, 'result');
  const title = node('h3');
  title.append(link(e.title || e.metadata?.title || e.content?.slice(0, 120) || e.item_id, e.url));

  // Platform & account row
  const topRow = node('div', undefined, 'result-top');
  topRow.textContent = `${names[e.platform] || e.platform} · ${e.account || e.source_id}`;
  card.append(topRow, title);

  // Status pills
  card.append(pill(a.time_classification, a.time_classification));
  if (a.relevant) card.append(node('span', 'Relevant', 'pill complete'));

  // Snippet vs full-text badge for web
  if (e.platform === 'web') {
    const scope = e.metadata?.collection_scope;
    if (scope === 'search_snippet_only') card.append(node('span', 'Snippet only', 'pill snippet'));
    else if (scope === 'public_page_text') card.append(node('span', 'Full article', 'pill fulltext'));
  }

  // Transcript badge
  if (e.metadata?.transcript_text) {
    card.append(node('span', 'Spoken transcript', 'pill transcript'));
  }

  // Content preview
  const content = (e.content || '').slice(0, 600);
  if (content) card.append(node('p', content));

  // Transcript preview
  if (e.metadata?.transcript_text) {
    const tBox = node('div', undefined, 'transcript-box');
    const preview = e.metadata.transcript_text.length > 250 ? e.metadata.transcript_text.slice(0, 250) + '…' : e.metadata.transcript_text;
    tBox.textContent = 'Transcript: ' + preview;
    card.append(tBox);
  }

  // Date & relevance summary
  card.append(node('p', `Published: ${formatDate(e.published_at)} · Collected: ${formatDate(e.collected_at)}`, 'muted'));

  // Matched terms (simplified)
  const matchedParts = Object.entries(a.matches || {}).filter(([, v]) => Array.isArray(v) && v.length > 0).map(([k, v]) => `${names[k]}: ${v.join(', ')}`);
  if (matchedParts.length) {
    card.append(node('p', 'Matched: ' + matchedParts.join(' · '), 'muted'));
  }

  if (a.related) {
    const relBox = node('div', undefined, 'notice-banner');
    relBox.style.cssText = 'background:#f0fdf4;border:1px solid #bbf7d0;border-left:4px solid #22c55e;color:#166534;margin:8px 0;padding:8px 12px;border-radius:6px;font-size:12.5px;';
    relBox.innerHTML = `<strong>Related Coverage Score: ${a.related.score}</strong> · <em>${a.related.relationship}</em><br>${(a.reasons || []).join(' · ')}`;
    card.append(relBox);
  }

  // Actions row
  const cardActions = node('div', undefined, 'actions');
  cardActions.style.marginTop = '10px';
  cardActions.append(
    action('Open original', () => { window.open(e.url, '_blank'); }),
    action('Print Record / PDF', () => printRecordDossier(item))
  );

  const isVideoRecord = e.platform === 'youtube' || e.media?.[0]?.type === 'video' || e.metadata?.is_video;
  if (isVideoRecord && !e.metadata?.transcript_text) {
    const transcribeBtn = action('Transcribe Audio', async () => {
      transcribeBtn.disabled = true;
      transcribeBtn.textContent = 'Transcribing...';
      try {
        const res = await api('/api/transcription/transcribe', { event_id: e.id, url: e.url });
        if (res.status === 'collected' && res.text) {
          e.metadata = e.metadata || {};
          e.metadata.transcript_text = res.text;
          e.metadata.transcript_status = 'collected';
          transcribeBtn.textContent = 'Transcribed';
          const tBox = node('div', undefined, 'transcript-box');
          tBox.textContent = 'Transcript: ' + (res.text.length > 250 ? res.text.slice(0, 250) + '…' : res.text);
          card.insertBefore(tBox, cardActions);
          notice('Spoken audio transcribed and relevance updated.');
        } else {
          transcribeBtn.disabled = false;
          transcribeBtn.textContent = 'Transcribe Audio';
          notice(res.error || 'Could not transcribe');
        }
      } catch (err) {
        transcribeBtn.disabled = false;
        transcribeBtn.textContent = 'Transcribe Audio';
        notice('Error: ' + err.message);
      }
    });
    cardActions.append(transcribeBtn);
  }
  card.append(cardActions);

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
    const btn = document.createElement('button');
    btn.className = 'history-item-btn' + (state.selectedRun === run.id ? ' active' : '');
    btn.style.cssText = 'width:100%;display:flex;align-items:center;justify-content:space-between;padding:10px 14px;margin-bottom:6px;text-align:left;border-radius:8px;';
    const dateSpan = node('span', formatDate(run.started_at));
    const statusPill = pill(run.status);
    btn.append(dateSpan, statusPill);
    btn.onclick = async () => {
      state.selectedRun = run.id;
      for (const b of $('run-list').querySelectorAll('button')) b.classList.remove('active');
      btn.classList.add('active');
      await historyReport(run.id);
    };
    $('run-list').append(btn);
  }
  if (state.selectedRun) await historyReport(state.selectedRun);
}

async function historyReport(id) {
  const r = await api('/api/audits/' + id), box = summaryCard(r);
  if (!r.platforms) return;
  const platGrid = node('div', undefined, 'platform-grid');
  platGrid.style.marginTop = '14px';
  for (const [p, a] of Object.entries(r.platforms)) {
    const btn = document.createElement('button');
    btn.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:12px 14px;';
    btn.append(node('span', `${names[p] || p} (${a.metrics?.relevant_items ?? 0} relevant)`), pill(a.status));
    btn.onclick = async () => {
      await navigate('platforms');
      await platformReport(id, p);
    };
    platGrid.append(btn);
  }
  box.append(platGrid);
  $('history-report').replaceChildren(box);
}

/* ── Search ── */
for (const [key, label, choices] of [
  ['q', 'Search text'],
  ['platform', 'Platform', ['', 'youtube', 'instagram', 'news', 'meta', 'web']],
  ['source', 'Source / account'],
  ['classification', 'Time period', ['', 'CURRENT', 'STALE', 'UNKNOWN_TIME', 'AFTER_WINDOW']],
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
    const val = typeof v === 'string' ? v.trim() : v;
    if (val) {
      if (k.endsWith('_time')) {
        try {
          const d = new Date(val);
          if (!isNaN(d.getTime())) p.set(k, d.toISOString());
        } catch (_) {}
      } else {
        p.set(k, val);
      }
    }
  }
  renderRecords($('record-results'), await api('/api/search?' + p));
}

$('search-form').addEventListener('submit', e => { e.preventDefault(); search().catch(e => notice(e.message)); });

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

function printRecordDossier(item) {
  const dossier = $('print-dossier');
  if (!dossier) return;
  dossier.replaceChildren();

  const e = item.event || {}, a = item.analysis || {};
  const platformName = names[e.platform] || e.platform || 'General';

  // Header
  const header = node('div', undefined, 'dossier-header');
  const titleBox = node('div', undefined, 'dossier-title');
  titleBox.append(
    node('h1', 'WATCHTOWER INTELLIGENCE RECORD DOSSIER'),
    node('p', `Platform: ${platformName.toUpperCase()} · Verified Source Record`)
  );
  const stampBox = node('div', undefined, 'dossier-stamp');
  stampBox.innerHTML = `<div style="text-align:right;font-size:8pt;color:#64748b;">RECORD ID<br><strong style="font-family:monospace;font-size:9pt;color:#0f172a;">${e.id || e.item_id || 'UNKNOWN'}</strong></div>`;
  header.append(titleBox, stampBox);
  dossier.append(header);

  // Metadata Grid
  const metaGrid = node('div', undefined, 'dossier-meta-grid');
  const addMeta = (label, val) => {
    const it = node('div', undefined, 'dossier-meta-item');
    it.append(node('span', label, 'label'), node('span', val || '—', 'value'));
    metaGrid.append(it);
  };
  addMeta('Platform', platformName);
  addMeta('Source / Account', e.account || e.source_id || 'Public Broadcast');
  addMeta('Published Time (IST)', formatDate(e.published_at));
  addMeta('Collection Time (IST)', formatDate(e.collected_at));
  addMeta('Classification', a.time_classification || 'UNKNOWN');
  addMeta('Relevance Status', a.relevant ? 'Relevant' : 'Non-relevant');
  addMeta('Original URL', e.url);
  addMeta('Evidence Score / Level', a.evidence_level || (a.relevant ? 'MATCHED' : 'LOW'));
  dossier.append(metaGrid);

  // Matched Dimensions
  const matchedParts = Object.entries(a.matches || {}).filter(([, v]) => Array.isArray(v) && v.length > 0);
  if (matchedParts.length) {
    const matchSec = node('div', undefined, 'dossier-section');
    matchSec.append(node('div', 'Matched Intelligence Dimensions', 'dossier-section-title'));
    const pills = node('div', undefined, 'dossier-pills');
    for (const [dim, vals] of matchedParts) {
      for (const v of vals) {
        pills.append(node('span', `${names[dim] || dim}: ${v}`, 'dossier-badge'));
      }
    }
    matchSec.append(pills);
    dossier.append(matchSec);
  }

  // Captured Content
  const contentSec = node('div', undefined, 'dossier-section');
  contentSec.append(node('div', 'Captured Content / Text', 'dossier-section-title'));
  const contentBox = node('div', e.content || e.title || 'No textual content extracted.', 'dossier-content-box');
  contentSec.append(contentBox);
  dossier.append(contentSec);

  // Spoken Transcript (WhisperFlow / Subtitles)
  if (e.metadata?.transcript_text) {
    const transSec = node('div', undefined, 'dossier-section');
    transSec.append(node('div', 'Spoken Audio Transcript (WhisperFlow / Subtitles)', 'dossier-section-title'));
    const transBox = node('div', e.metadata.transcript_text, 'dossier-transcript-box');
    transSec.append(transBox);
    dossier.append(transSec);
  }

  // Footer
  const footer = node('div', undefined, 'dossier-footer');
  footer.append(
    node('span', 'Watchtower Intelligence Platform v0.3 · Strictly Local Provenance'),
    node('span', `Printed: ${formatDate(new Date().toISOString())} IST`)
  );
  dossier.append(footer);

  document.body.classList.add('printing-record');
  window.print();
  window.addEventListener('afterprint', () => document.body.classList.remove('printing-record'), { once: true });
}

function printScrapedPost(post) {
  const dossier = $('print-dossier');
  if (!dossier) return;
  dossier.replaceChildren();

  // Header
  const header = node('div', undefined, 'dossier-header');
  const titleBox = node('div', undefined, 'dossier-title');
  titleBox.append(
    node('h1', 'INSTAGRAM DISCOVERY RECORD DOSSIER'),
    node('p', `Account: @${post.username || 'unknown'} · Shortcode: ${post.shortcode || ''}`)
  );
  const stampBox = node('div', undefined, 'dossier-stamp');
  stampBox.innerHTML = `<div style="text-align:right;font-size:8pt;color:#64748b;">POST ID<br><strong style="font-family:monospace;font-size:9pt;color:#0f172a;">${post.id || post.shortcode || 'UNKNOWN'}</strong></div>`;
  header.append(titleBox, stampBox);
  dossier.append(header);

  // Meta Grid
  const metaGrid = node('div', undefined, 'dossier-meta-grid');
  const addMeta = (label, val) => {
    const it = node('div', undefined, 'dossier-meta-item');
    it.append(node('span', label, 'label'), node('span', val || '—', 'value'));
    metaGrid.append(it);
  };
  addMeta('Platform', 'Instagram');
  addMeta('Username', `@${post.username || ''}`);
  addMeta('Published Date (IST)', formatDate(post.published_at));
  addMeta('Discovery Method', post.discovery_method || 'Profile Scraper');
  addMeta('Likes', (post.engagement?.likes ?? 0).toLocaleString());
  addMeta('Comments', (post.engagement?.comments ?? 0).toLocaleString());
  addMeta('URL', `https://www.instagram.com/p/${post.shortcode}/`);
  addMeta('Media Type', post.media?.[0]?.type || 'photo');
  dossier.append(metaGrid);

  // Post Caption
  const contentSec = node('div', undefined, 'dossier-section');
  contentSec.append(node('div', 'Post Caption / Text', 'dossier-section-title'));
  const contentBox = node('div', post.caption || 'No caption provided.', 'dossier-content-box');
  contentSec.append(contentBox);
  dossier.append(contentSec);

  // Footer
  const footer = node('div', undefined, 'dossier-footer');
  footer.append(
    node('span', 'Watchtower Intelligence Platform v0.3 · Instagram Public Collection'),
    node('span', `Printed: ${formatDate(new Date().toISOString())} IST`)
  );
  dossier.append(footer);

  document.body.classList.add('printing-record');
  window.print();
  window.addEventListener('afterprint', () => document.body.classList.remove('printing-record'), { once: true });
}

/* ── Transcription Settings & Test ── */
async function renderTranscriptionSettings() {
  const s = await api('/api/transcription');
  const badge = $('transcription-status-badge');
  const notes = $('transcription-status-notes');
  const banner = $('transcription-status-box');

  if (badge && banner) {
    if (s.local_installed) {
      badge.textContent = `Local Whisper Engine: Installed (openai-whisper)` + (s.ffmpeg_installed ? ' · ffmpeg Ready' : ' · (ffmpeg needed for local audio; or use Cloud API)');
      banner.style.background = s.ffmpeg_installed ? '#f0fdf4' : '#fffbeb';
      banner.style.borderColor = s.ffmpeg_installed ? '#bbf7d0' : '#fde68a';
      banner.style.color = s.ffmpeg_installed ? '#166534' : '#92400e';
    } else {
      badge.textContent = `Local Whisper not installed · Using Cloud API or Subtitles`;
      banner.style.background = '#fffbeb';
      banner.style.borderColor = '#fde68a';
      banner.style.color = '#92400e';
    }
  }

  if (notes && s.notes?.length) {
    notes.textContent = s.notes.join(' · ');
  }

  if ($('transcribe-mode')) $('transcribe-mode').value = s.provider || 'whisper';
  if ($('transcribe-model')) $('transcribe-model').value = s.model || 'base';
  if ($('transcribe-api-key') && s.api_key_masked) $('transcribe-api-key').placeholder = `Configured (${s.api_key_masked}) — enter new key to replace`;
  if ($('transcribe-api-endpoint')) $('transcribe-api-endpoint').value = s.api_endpoint || '';
}

bind('save-transcription-btn', async () => {
  const provider = $('transcribe-mode').value;
  const model = $('transcribe-model').value;
  const keyVal = $('transcribe-api-key').value.trim();
  const endpoint = $('transcribe-api-endpoint').value.trim();

  const payload = { provider, model, api_endpoint: endpoint, auto_transcribe: false };
  if (keyVal) payload.api_key = keyVal;

  await api('/api/transcription/configure', payload);
  await renderTranscriptionSettings();
  notice('Transcription settings saved (Strict On-Demand Mode).');
});

async function runSingleVideoTranscription(saveToRecords) {
  const url = $('test-transcribe-url').value.trim();
  if (!url) throw new Error('Enter a video or audio URL first');
  const resDiv = $('test-transcribe-result');
  resDiv.hidden = false;
  resDiv.replaceChildren(node('p', 'Processing and transcribing audio for desired video (may take 10-30s)...', 'muted'));
  try {
    const res = await api('/api/transcription/transcribe', { url, save: saveToRecords });
    resDiv.replaceChildren();
    if (res.status === 'collected' && res.text) {
      const box = node('div', undefined, 'transcript-box');
      box.textContent = 'Transcript: ' + res.text;
      
      const successMsg = saveToRecords 
        ? 'Transcribed & Saved to Watchtower Records (' + (res.provider || 'Whisper') + ')'
        : 'Transcription successful (' + (res.provider || 'Whisper') + ')';
      
      resDiv.append(node('p', successMsg, 'status'), box);
      
      if (res.analysis) {
        const scoreBadge = node('div', undefined, 'notice-banner');
        scoreBadge.style.cssText = 'margin-top:8px;padding:8px 12px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;font-size:13px;';
        const scoreVal = res.analysis.score !== undefined ? res.analysis.score : (res.analysis.threat_score || 0);
        scoreBadge.innerHTML = `<strong>Intelligence Score:</strong> ${scoreVal} · <strong>Matches:</strong> ${(res.analysis.matches || []).join(', ') || 'None'}`;
        resDiv.append(scoreBadge);
      }

      if (saveToRecords) {
        const viewBtn = action('View in Records', () => navigate('records'), 'primary');
        viewBtn.style.marginTop = '8px';
        resDiv.append(viewBtn);
      }
      notice('Desired video transcribed successfully.');
    } else {
      resDiv.append(node('p', (res.error || 'No transcript generated'), 'empty'));
      notice(res.error || 'No transcript generated');
    }
  } catch (err) {
    resDiv.replaceChildren(node('p', 'Error: ' + err.message, 'empty'));
    notice('Error: ' + err.message);
  }
}

bind('test-transcribe-btn', () => runSingleVideoTranscription(false));
bind('save-transcribe-video-btn', () => runSingleVideoTranscription(true));

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
  notice('Instagram session imported. Test the connection to verify.');
});

bind('ig-test', async () => {
  $('ig-status').textContent = 'Testing…';
  const r = await api('/api/instagram/test', {});
  $('ig-status').textContent = r.error ? (errorMessages[r.error] || r.error) : 'Connected: ' + r.status;
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
      action('Monitor this account', async () => {
        state.profile.saved_sources.instagram = [...new Set([...(state.profile.saved_sources.instagram || []), p.username])];
        await saveProfile();
        renderSaved();
        notice(`@${p.username} added to monitoring.`);
      })
    );
    $('ig-results').append(c);
  }
});

function updateScheduleDisplay(s) {
  if (!s) return;
  const dot = $('schedule-status-dot');
  const title = $('schedule-status-title');
  const next = $('schedule-next');
  if (s.enabled) {
    if (dot) dot.className = 'status-dot active';
    if (title) title.textContent = 'Auto-Schedule Active';
    if (next) next.textContent = s.next_run_at ? 'Next run scheduled for: ' + formatDate(new Date(s.next_run_at * 1000).toISOString()) : 'Waiting for next run cycle';
  } else {
    if (dot) dot.className = 'status-dot inactive';
    if (title) title.textContent = 'Auto-Schedule Disabled';
    if (next) next.textContent = 'Audits will only run when initiated manually.';
  }
}

if ($('schedule-frequency')) {
  $('schedule-frequency').addEventListener('change', () => {
    const isCustom = $('schedule-frequency').value === 'custom';
    $('schedule-custom-wrap').hidden = !isCustom;
    if (!isCustom) {
      $('schedule-minutes').value = $('schedule-frequency').value;
    }
  });
}

bind('save-schedule', async () => {
  const enabled = $('schedule-enabled').checked;
  const freq = $('schedule-frequency') ? $('schedule-frequency').value : '1440';
  let minutes = 1440;
  if (freq === 'custom') {
    minutes = Number($('schedule-minutes').value);
  } else {
    minutes = Number(freq);
  }
  if (isNaN(minutes) || minutes < 5 || minutes > 10080) {
    notice('Interval must be between 5 and 10080 minutes.');
    return;
  }
  const s = await api('/api/schedule', {
    enabled,
    interval_minutes: minutes
  });
  updateScheduleDisplay(s);
  notice('Schedule saved successfully.');
});

$('close-dialog').addEventListener('click', () => $('detail-dialog').close());

/* ── Polling ── */
async function poll() {
  if (state.polling) return;
  state.polling = true;
  try {
    state.status = await api('/api/status');
    $('run-state').textContent = state.status.running ? 'Audit running' : 'Ready';
    $('run-state').className = 'pill ' + (state.status.running ? 'running' : 'ready');
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
            $('live-report').append(node('p', `${names[p]}: ${a.metrics.items_checked} items, ${a.metrics.relevant_items} relevant`));
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
  if (state.status?.schedule) {
    const s = state.status.schedule;
    if ($('schedule-enabled')) $('schedule-enabled').checked = s.enabled;
    const minutes = s.interval_minutes || 1440;
    if ($('schedule-minutes')) $('schedule-minutes').value = minutes;
    const presets = ['360', '720', '1440', '2880', '10080'];
    if ($('schedule-frequency')) {
      if (presets.includes(String(minutes))) {
        $('schedule-frequency').value = String(minutes);
        if ($('schedule-custom-wrap')) $('schedule-custom-wrap').hidden = true;
      } else {
        $('schedule-frequency').value = 'custom';
        if ($('schedule-custom-wrap')) $('schedule-custom-wrap').hidden = false;
      }
    }
    updateScheduleDisplay(s);
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

  $('ig-target-time')?.addEventListener('change', () => {
    if ($('ig-target-custom')) $('ig-target-custom').hidden = $('ig-target-time').value !== 'custom';
  });
  $('ig-tag-time')?.addEventListener('change', () => {
    if ($('ig-tag-custom')) $('ig-tag-custom').hidden = $('ig-tag-time').value !== 'custom';
  });

  bind('ig-scrape-btn', async () => {
    const target = $('ig-target-user').value.trim();
    const limit = Number($('ig-target-limit').value || 10);
    if (!target) throw new Error('Enter an Instagram username to scrape');

    const timeChoice = $('ig-target-time')?.value || 'all';
    let hours = null, since = null, until = null;
    if (timeChoice === 'custom') {
      const s = $('ig-target-since')?.value, u = $('ig-target-until')?.value;
      if (s) since = new Date(s).toISOString();
      if (u) until = new Date(u).toISOString();
    } else if (timeChoice !== 'all') {
      hours = Number(timeChoice);
    }

    $('ig-scrape-loading').hidden = false;
    $('ig-scrape-status-text').textContent = `Scraping posts for @${target}...`;
    try {
      const res = await api('/api/instagram/scrape', { type: 'profile', target, limit, hours, since, until });
      if (res.error) throw new Error(errors[res.error] || res.error);
      igScrapedData = res;
      renderScrapedProfile(res.profile);
      renderScrapedPosts(res.records || []);
      const timeNote = hours ? ` (last ${hours}h)` : since ? ` (filtered by date)` : '';
      notice(`Scraped ${res.records?.length || 0} posts from @${target}${timeNote}!`);
    } finally {
      $('ig-scrape-loading').hidden = true;
    }
  });

  bind('ig-scrape-tag-btn', async () => {
    const target = $('ig-target-tag').value.trim();
    const limit = Number($('ig-tag-limit').value || 10);
    if (!target) throw new Error('Enter a hashtag to scrape');

    const timeChoice = $('ig-tag-time')?.value || 'all';
    let hours = null, since = null, until = null;
    if (timeChoice === 'custom') {
      const s = $('ig-tag-since')?.value, u = $('ig-tag-until')?.value;
      if (s) since = new Date(s).toISOString();
      if (u) until = new Date(u).toISOString();
    } else if (timeChoice !== 'all') {
      hours = Number(timeChoice);
    }

    $('ig-scrape-loading').hidden = false;
    $('ig-scrape-status-text').textContent = `Scraping posts for #${target}...`;
    $('ig-profile-card').replaceChildren();
    try {
      const res = await api('/api/instagram/scrape', { type: 'hashtag', target, limit, hours, since, until });
      if (res.error) throw new Error(errors[res.error] || res.error);
      igScrapedData = res;
      renderScrapedPosts(res.records || []);
      const timeNote = hours ? ` (last ${hours}h)` : since ? ` (filtered by date)` : '';
      notice(`Scraped ${res.records?.length || 0} posts for #${target}${timeNote}!`);
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
    notice(`@${username} successfully saved to monitoring profile!`);
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
    const v = node('span', 'Verified', 'pill complete');
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
      preview.append(node('span', isVideo ? 'Video' : 'Photo', 'muted'));
    }
    preview.append(node('span', isVideo ? 'Video' : 'Photo', 'ig-badge'));
    const body = node('div', undefined, 'ig-post-body');
    const meta = node('div', undefined, 'ig-post-meta');
    meta.append(
      link(post.shortcode, `https://www.instagram.com/p/${post.shortcode}/`),
      node('span', formatDate(post.published_at))
    );
    const caption = node('p', post.caption || 'No caption text', 'ig-post-caption');
    const eng = node('div', undefined, 'ig-post-engagement');
    eng.innerHTML = `<span><strong>${(post.engagement?.likes ?? 0).toLocaleString()}</strong> likes</span> · <span><strong>${(post.engagement?.comments ?? 0).toLocaleString()}</strong> comments</span>`;
    const postActions = node('div', undefined, 'actions');
    postActions.style.marginTop = '10px';
    postActions.append(
      action('Print / PDF', () => printScrapedPost(post)),
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
