'use strict';

// ---------- Settings ----------
// `GET /api/settings` answers with the workspace in plain words; `POST /api/settings` saves one setting and answers with the fresh view and a message.
const SCOPE_KINDS = [['personal', 'Personal'], ['employer', 'Employer'], ['client', 'Client']];
const settingsEdits = new Map(); // setting key -> {draft, busy, error}: what is being typed, kept while the view is redrawn
const settingsNotes = new Map(); // setting key -> message of the last save
function settingsRows(rows) {
  const list = element('dl', 'settings-dl');
  for (const [label, value] of rows) {
    if (value === '' || value === null || value === undefined) continue;
    list.append(element('dt', '', label), element('dd', '', value));
  }
  return list;
}
function settingsBadge(text, tone = '') {
  return element('span', `settings-badge${tone ? ` is-${tone}` : ''}`, text);
}
function settingsSection(title, note, ...children) {
  const section = element('section', 'settings-section');
  const head = element('div', 'settings-section-head');
  head.append(element('h2', '', title));
  if (note) head.append(element('p', '', note));
  section.append(head, ...children);
  return section;
}
function settingsCard(tone, ...children) {
  const card = element('div', 'settings-card');
  if (tone) card.dataset.tone = tone;
  card.append(...children);
  return card;
}
function settingsFailure(section) {
  return section && section.error ? element('p', 'error-note settings-error', section.error) : null;
}
function settingsStack(nodes) {
  const stack = element('div', 'settings-stack');
  stack.append(...nodes);
  return stack;
}
function optionLabel(options, name) { return options.find(option => option.name === name)?.label || name; }
function scopeKindLabel(slug) { return SCOPE_KINDS.find(([value]) => value === slug)?.[1] || (slug ? `Other (${slug})` : ''); }
function settingDisplay(field) {
  if (field.input === 'brain') return field.value ? optionLabel(field.options, field.value) : '';
  if (field.input === 'brains') return field.value.map(name => optionLabel(field.options, name)).join(', ');
  if (field.input === 'scope') return scopeKindLabel(field.value);
  return field.value || '';
}
function scopeSlug(text) { return text.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''); }
// The input that edits one setting; `change` receives the new draft (text, a brain name, a list of brain names or a kind).
function settingControl(field, draft, label, change) {
  if (field.input === 'brain') {
    const select = element('select');
    select.setAttribute('aria-label', label);
    if (!field.options.some(option => option.name === draft)) select.append(new Option('Choose a brain…', ''));
    for (const option of field.options) select.append(new Option(option.label, option.name));
    select.value = draft;
    select.addEventListener('change', () => change(select.value));
    return select;
  }
  if (field.input === 'brains') {
    const group = element('div', 'settings-checks');
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', label);
    const chosen = new Set(draft);
    for (const option of field.options) {
      const row = element('label', 'settings-check');
      const box = element('input');
      box.type = 'checkbox';
      box.checked = chosen.has(option.name);
      box.addEventListener('change', () => {
        if (box.checked) chosen.add(option.name); else chosen.delete(option.name);
        change(field.options.filter(entry => chosen.has(entry.name)).map(entry => entry.name));
      });
      row.append(box, element('span', '', option.present ? option.label : `${option.label} (not on this computer yet)`));
      group.append(row);
    }
    return group;
  }
  if (field.input === 'scope') {
    const wrap = element('div', 'settings-scope');
    const kind = element('select');
    kind.setAttribute('aria-label', label);
    if (!draft) kind.append(new Option('Choose a kind…', ''));
    for (const [value, text] of SCOPE_KINDS) kind.append(new Option(text, value));
    kind.append(new Option('Other', 'other'));
    const known = SCOPE_KINDS.some(([value]) => value === draft);
    kind.value = known ? draft : draft ? 'other' : '';
    const other = element('input');
    other.type = 'text';
    other.maxLength = 40;
    other.placeholder = 'A short word, such as supplier';
    other.setAttribute('aria-label', `${label}: other kind`);
    other.value = known ? '' : draft;
    other.hidden = kind.value !== 'other';
    kind.addEventListener('change', () => {
      other.hidden = kind.value !== 'other';
      change(kind.value === 'other' ? scopeSlug(other.value) : kind.value);
      if (kind.value === 'other') other.focus();
    });
    other.addEventListener('input', () => change(scopeSlug(other.value)));
    wrap.append(kind, other);
    return wrap;
  }
  const area = field.input === 'textarea';
  const control = element(area ? 'textarea' : 'input');
  if (area) { control.rows = 3; control.maxLength = 500; } else control.type = 'text';
  control.placeholder = field.placeholder || '';
  control.setAttribute('aria-label', label);
  control.value = draft;
  control.addEventListener('input', () => change(control.value));
  return control;
}
// One setting. `always` shows its input at once (to complete); otherwise the value is read until Edit.
function settingField(field, {label, always = false, hasDefault = false, badge = null}) {
  const wrap = element('div', 'settings-field');
  wrap.append(element('div', 'settings-field-label', label));
  const slot = always ? `to-complete:${field.key}` : field.key; // the same setting may be asked above and shown below
  let edit = settingsEdits.get(slot);
  if (always && !edit) { edit = {draft: field.value, busy: false, error: ''}; settingsEdits.set(slot, edit); }
  if (edit) {
    const row = element('div', 'settings-edit');
    row.append(settingControl(field, edit.draft, label, draft => { edit.draft = draft; }));
    const actions = element('div', 'settings-actions');
    const save = element('button', 'button button-small button-primary', edit.busy ? 'Saving…' : 'Save');
    save.type = 'button';
    save.addEventListener('click', () => saveSetting(slot, field.key, edit.draft, false));
    actions.append(save);
    if (always && hasDefault) {
      const reset = element('button', 'button button-small', 'Use the default');
      reset.type = 'button';
      reset.addEventListener('click', () => saveSetting(slot, field.key, null, true));
      actions.append(reset);
    }
    if (!always) {
      const cancel = element('button', 'button button-small', 'Cancel');
      cancel.type = 'button';
      cancel.addEventListener('click', () => { settingsEdits.delete(slot); renderSettings(); });
      actions.append(cancel);
    }
    row.append(actions);
    if (edit.busy) for (const control of row.querySelectorAll('input, select, textarea, button')) control.disabled = true;
    row.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target.tagName === 'INPUT' && event.target.type === 'text' && !edit.busy) { event.preventDefault(); saveSetting(slot, field.key, edit.draft, false); }
    });
    wrap.append(row);
    if (edit.error) {
      const problem = element('p', 'error-note settings-error', edit.error);
      problem.setAttribute('role', 'alert');
      wrap.append(problem);
    }
  } else {
    const row = element('div', 'settings-read');
    const shown = settingDisplay(field);
    row.append(element('span', shown ? 'settings-value' : 'settings-value is-empty', shown || 'Not set yet'));
    if (badge) row.append(settingsBadge(badge, 'ok'));
    const change = element('button', 'button button-small', 'Edit');
    change.type = 'button';
    change.setAttribute('aria-label', `Edit: ${label}`);
    change.addEventListener('click', () => {
      settingsNotes.delete(field.key);
      settingsEdits.set(field.key, {draft: field.value, busy: false, error: ''});
      renderSettings();
    });
    row.append(change);
    wrap.append(row);
    for (const text of field.warnings || []) wrap.append(element('p', 'settings-warning', text));
    if (field.note) wrap.append(element('p', 'settings-note', field.note));
    const saved = settingsNotes.get(field.key);
    if (saved) wrap.append(element('p', 'settings-saved', saved));
  }
  return wrap;
}
async function saveSetting(slot, key, value, useDefault) {
  const edit = settingsEdits.get(slot);
  if (!edit || edit.busy) return;
  edit.busy = true;
  edit.error = '';
  renderSettings();
  try {
    const {message, ...fresh} = await updatePost('/api/settings', useDefault ? {key, default: true} : {key, value});
    settingsData = fresh;
    settingsEdits.delete(slot);
    settingsEdits.delete(key);
    settingsNotes.set(key, message);
    showToast(message);
  } catch (error) {
    edit.busy = false;
    edit.error = error.message;
  }
  renderSettings();
}
function renderSettingsTodo(setup) {
  const failure = settingsFailure(setup);
  if (failure) return settingsSection('To complete', '', failure);
  const nodes = setup.todo.map(item => settingsCard('warn', settingField(item, {label: item.label, always: true, hasDefault: item.has_default})));
  if (setup.technical_missing) nodes.push(element('p', 'settings-note', 'A few technical settings are missing: your agent will ask for them at the start of your next conversation.'));
  if (!setup.todo.length && !setup.technical_missing) nodes.push(element('p', 'settings-note', 'Nothing to complete: everything is set.'));
  return settingsSection('To complete', setup.todo.length ? 'Answer these questions to finish setting up your workspace.' : '', settingsStack(nodes));
}
function renderSettingsAgent(setup) {
  if (setup.error || !setup.agent.length) return null;
  const list = element('ul', 'settings-tasks');
  for (const task of setup.agent) {
    const item = element('li');
    item.append(element('span', '', task.title), element('span', 'settings-note', 'Ask your agent to take care of it.'));
    list.append(item);
  }
  return settingsSection('Needs your agent', 'These cannot be done from this page.', settingsCard('info', list));
}
function renderSettingsWorkspace(workspace) {
  const failure = settingsFailure(workspace);
  if (failure) return settingsSection('Workspace', '', failure);
  const {default_brain: brain, artifacts, transcripts, needed_brains: needed} = workspace;
  const parts = [
    settingField({...brain, input: 'brain'}, {label: 'Default brain'}),
    settingField({...artifacts, input: 'text', placeholder: 'A folder name, or the full path of a synced folder'}, {label: 'Deliverables folder', badge: artifacts.status}),
    settingField({...transcripts, input: 'text', placeholder: 'For example Documents/Transcripts'}, {label: 'Meeting transcripts folder'}),
    settingField({...needed, input: 'brains'}, {label: 'Brains every computer must have'})
  ];
  if (brain.problem) parts.splice(1, 0, element('p', 'error-note settings-error', brain.problem));
  return settingsSection('Workspace', 'Where your work lives on this computer.', settingsCard('', ...parts));
}
function renderSettingsBrains(brains) {
  const failure = settingsFailure(brains);
  if (failure) return settingsSection('Brains', '', failure);
  const cards = brains.brains.map(brain => {
    const head = element('div', 'settings-card-head');
    head.append(element('strong', 'settings-key', brain.label));
    if (brain.default) head.append(settingsBadge('Default', 'info'));
    const parts = [head,
      settingField({key: `${brain.name}.description`, input: 'textarea', value: brain.description, placeholder: 'What it holds, and what it must never hold'}, {label: 'What it holds'}),
      settingField({key: `${brain.name}.owner`, input: 'text', value: brain.owner, placeholder: 'First and last name'}, {label: 'Owner of the actions'}),
      settingField({key: `${brain.name}.scope`, input: 'scope', value: brain.scope}, {label: 'Kind'})];
    if (brain.problem) parts.push(element('p', 'error-note settings-error', brain.problem));
    return settingsCard('', ...parts);
  });
  return settingsSection('Brains', 'Each brain is a separate memory, with its own content and its own owner.', settingsStack(cards));
}
function renderSettingsSkills(skills) {
  const failure = settingsFailure(skills);
  if (failure) return settingsSection('Skills', '', failure);
  const nodes = [];
  if (skills.needs_refresh) nodes.push(settingsCard('warn', element('p', 'settings-note', 'Your agent needs to refresh the skills: ask it to update the workspace.')));
  for (const group of skills.groups) {
    const card = element('div', 'settings-card');
    card.append(element('h3', 'settings-subhead', group.title));
    const list = element('ul', 'settings-skills');
    for (const skill of group.skills) {
      const item = element('li');
      item.append(element('strong', '', skill.name));
      if (skill.summary) item.append(element('span', 'settings-skill-detail', skill.summary));
      list.append(item);
    }
    card.append(list);
    nodes.push(card);
  }
  if (!skills.groups.length) nodes.push(element('p', 'settings-note', 'No skill is turned on.'));
  if (skills.turned_off.length) {
    const card = element('div', 'settings-card');
    card.append(element('h3', 'settings-subhead', 'Turned off on this computer'), element('p', 'settings-note', skills.turned_off.join(', ')));
    nodes.push(card);
  }
  return settingsSection('Skills', 'What your agent can do. Read-only.', settingsStack(nodes));
}
function renderSettingsVersion() {
  const info = updateInfo;
  const newer = updateNewer(info);
  const blocked = newer && info.state === 'blocked';
  const head = element('div', 'settings-card-head');
  head.append(element('strong', '', info?.state ? (info.current || 'Unreleased') : 'Not checked yet'));
  if (info?.state) {
    const [label, tone] = blocked ? ['Cannot update', 'warn'] : newer ? ['A new version is available', 'info'] : info.state === 'error' ? ['Could not check', 'warn'] : ['Up to date', 'ok'];
    head.append(settingsBadge(label, tone));
  }
  const checkedAt = info?.checked_at ? new Date(info.checked_at).toLocaleString(LOCALE, {dateStyle: 'medium', timeStyle: 'short'}) : '';
  const rows = settingsRows([
    ['Version in use', info?.state ? (info.current || 'unreleased') : ''],
    ['Latest version', info?.state && info.state !== 'error' ? (info.latest || 'none published yet') : ''],
    ['Cannot update', blocked ? (info.reasons || []).join('; ') : ''],
    ['Could not check', info?.state === 'error' ? (info.error || 'unknown reason') : ''],
    ['Last checked', checkedAt]
  ]);
  const actions = element('div', 'update-actions');
  const check = element('button', 'button button-small', updateChecking ? 'Checking…' : 'Check now');
  check.type = 'button';
  check.disabled = updateChecking || updateBusy;
  check.addEventListener('click', () => checkUpdate({force: true}));
  actions.append(check);
  if (newer) {
    const open = element('button', 'button button-small button-primary', blocked ? 'See details' : `Update to ${info.latest}…`);
    open.type = 'button';
    open.addEventListener('click', openUpdateDialog);
    actions.append(open);
  }
  return settingsSection('Version', 'The version of the workspace in use, and the latest one available.', settingsCard(blocked ? 'warn' : newer ? 'info' : '', head, rows, actions));
}
function renderSettings() {
  if (view !== 'settings') return;
  const body = element('div', 'settings-body');
  const bar = element('div', 'settings-bar');
  const intro = element('p', '', 'Your workspace at a glance. Change what you like here: your agent takes care of anything technical.');
  const refresh = element('button', 'button button-small', settingsLoading ? 'Refreshing…' : 'Refresh');
  refresh.type = 'button';
  refresh.disabled = Boolean(settingsLoading);
  refresh.addEventListener('click', () => loadSettings());
  bar.append(intro, refresh);
  body.append(bar);
  if (settingsError) {
    const message = element('p', 'error-note', settingsError);
    message.setAttribute('role', 'alert');
    body.append(message);
  }
  if (settingsData) {
    body.append(renderSettingsTodo(settingsData.setup));
    const agent = renderSettingsAgent(settingsData.setup);
    if (agent) body.append(agent);
    body.append(renderSettingsWorkspace(settingsData.workspace), renderSettingsBrains(settingsData.brains), renderSettingsSkills(settingsData.skills));
  } else if (!settingsError) body.append(element('p', 'loading-note', 'Loading your settings…'));
  body.append(renderSettingsVersion());
  const scroll = ids.settingsView.scrollTop;
  ids.settingsView.replaceChildren(body);
  ids.settingsView.scrollTop = scroll;
  const missing = settingsData?.setup?.todo?.length || 0;
  ids.resultCount.textContent = settingsData ? (missing ? `${plural(missing, 'setting')} to complete` : 'Nothing to complete') : '';
  ids.settingsButton.setAttribute('aria-label', missing ? `Settings, ${plural(missing, 'setting')} to complete` : 'Settings');
}
function loadSettings() {
  if (settingsLoading) return settingsLoading;
  settingsLoading = (async () => {
    try {
      const data = await request('/api/settings', {}, '');
      if (!data.setup?.todo || !data.workspace?.needed_brains) throw new Error('Restart the app: this page is newer than the one that is running.');
      settingsData = data;
      settingsError = '';
    } catch (error) {
      settingsError = error.message;
    } finally {
      settingsLoading = null;
      renderSettings();
    }
  })();
  renderSettings();
  return settingsLoading;
}

// ---------- Update ----------
// `POST /api/update/check` (throttled by the server to one real check per hour) on load and every 6 hours; the sidebar button shows only
// when a newer release exists. The update itself (`POST /api/update/apply`) fast-forwards Work, runs update.sh and restarts this server.
const UPDATE_CHECK_EVERY = 6 * 60 * 60 * 1000;
const UPDATE_RESTART_WAIT = 60 * 1000;
const UPDATE_POLL_EVERY = 700;
const UPDATE_DONE_KEY = 'work-update-done-v1'; // {version, seconds}: set just before the reload that follows an update, read once after it
const UPDATE_WHAT = 'Installs version VERSION of the workspace, then restarts the app. Your brains and your work are not changed.';
function updateNewer(info) {
  return Boolean(info && (info.state === 'available' || info.state === 'blocked') && info.latest && info.latest !== info.current);
}
// Not `request()`: a check or an update must not hold back a brain switch, and neither carries a brain.
async function updatePost(url, body) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token}, body: JSON.stringify(body)});
  let payload;
  try { payload = await response.json(); } catch { throw new Error('Unreadable local response.'); }
  if (!response.ok) {
    const error = new Error(payload.error || 'Operation failed.');
    error.data = payload;
    throw error;
  }
  return payload;
}
function renderUpdateButton() {
  const newer = updateNewer(updateInfo);
  ids.updateButton.hidden = !newer;
  if (!newer) return;
  const blocked = updateInfo.state === 'blocked';
  ids.updateButtonLabel.textContent = `Update to ${updateInfo.latest}`;
  ids.updateButton.classList.toggle('is-warn', blocked);
  ids.updateButton.title = blocked ? `${updateInfo.latest} is available but cannot be applied yet. Click for the reasons.` : `Release ${updateInfo.latest} is available. Click to see what it brings.`;
}
async function checkUpdate({force = false} = {}) {
  if (updateChecking) return;
  updateChecking = true;
  renderSettings();
  try {
    updateInfo = await updatePost('/api/update/check', force ? {force: true} : {});
  } catch (error) {
    if (force) showToast(`Could not check for updates: ${error.message}`); // the automatic checks stay silent
  } finally {
    updateChecking = false;
    renderUpdateButton();
    renderSettings();
    if (ids.updateDialog.open && !updateBusy) fillUpdateDialog();
  }
}
function updateSetError(message) {
  ids.updateError.textContent = message;
  ids.updateError.hidden = !message;
}
function fillUpdateDialog() {
  const info = updateInfo;
  if (!updateNewer(info)) { ids.updateDialog.close(); return; }
  const blocked = info.state === 'blocked';
  ids.updateHeading.textContent = `Update to ${info.latest}`;
  ids.updateText.textContent = blocked ? `Cannot update to ${info.latest}:` : `${info.kind ? `${info.kind[0].toUpperCase()}${info.kind.slice(1)} release` : 'Release'}, from ${info.current || 'an unreleased version'}.`;
  const hasNotes = Boolean(info.notes_html);
  ids.updateNotes.hidden = !hasNotes;
  if (hasNotes) ids.updateNotes.innerHTML = info.notes_html; // rendered by the server: raw HTML escaped
  const lines = blocked ? info.reasons || [] : hasNotes ? [] : info.commits || [];
  const more = !blocked && !hasNotes && info.commits_total > (info.commits || []).length ? info.commits_total - info.commits.length : 0;
  ids.updateList.replaceChildren(...lines.map(text => element('li', '', text)), ...(more ? [element('li', 'git-confirm-more', `+${more} more`)] : []));
  ids.updateList.hidden = !lines.length;
  ids.updateWhat.textContent = blocked ? 'Ask your agent to resolve this, then check again.' : UPDATE_WHAT.replace('VERSION', info.latest);
  ids.updateConfirm.hidden = blocked;
  ids.updateRecheck.hidden = !blocked;
  ids.updateRecheck.disabled = updateChecking;
  ids.updateCancel.textContent = 'Cancel';
  updateSetError('');
}
function openUpdateDialog() {
  if (!updateNewer(updateInfo) || updateBusy) return;
  ids.updateConfirm.disabled = false;
  ids.updateConfirm.removeAttribute('aria-busy');
  fillUpdateDialog();
  if (!ids.updateDialog.open) ids.updateDialog.showModal();
}
// The new server has a new token: the page it serves differs from this one, which also tells it from the old server still shutting down.
async function waitForRestart() {
  const deadline = Date.now() + UPDATE_RESTART_WAIT;
  while (Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    try {
      const response = await fetch('/', {cache: 'no-store'});
      const match = response.ok ? (await response.text()).match(/name="csrf-token" content="([^"]*)"/) : null;
      if (match && match[1] !== token) return true;
    } catch { /* the server is down: it is restarting */ }
  }
  return false;
}
function updateClock(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}
// The step bar of a running update: determinate when GET /api/update/progress knows the total, an indeterminate stripe until then.
function paintUpdateProgress(step, seconds, restarting) {
  const known = restarting || Boolean(step && step.total && step.index);
  ids.updateBar.classList.toggle('is-determinate', known);
  ids.updateBar.setAttribute('aria-valuemax', known && !restarting ? String(step.total) : '100');
  if (known) {
    ids.updateBar.setAttribute('aria-valuenow', restarting ? '100' : String(step.index));
    ids.updateBarFill.style.width = restarting ? '100%' : `${Math.min(100, Math.round(step.index / step.total * 100))}%`;
  } else {
    ids.updateBar.removeAttribute('aria-valuenow');
    ids.updateBarFill.style.width = '';
  }
  const label = restarting ? 'Restarting…' : step && step.label ? (known ? `Step ${step.index} of ${step.total} · ${step.label}` : step.label) : 'Updating…';
  if (ids.updateStep.textContent !== label) ids.updateStep.textContent = label;
  ids.updateElapsed.textContent = updateClock(seconds);
}
function startUpdateProgress() {
  const began = Date.now();
  let step = null, restarting = false, stopped = false, busy = false;
  const paint = () => paintUpdateProgress(step, (Date.now() - began) / 1000, restarting);
  const tick = async () => {
    if (busy || stopped || restarting) { if (!stopped) paint(); return; }
    busy = true;
    try {
      const response = await fetch('/api/update/progress', {cache: 'no-store'});
      const data = response.ok ? await response.json() : null;
      if (data && data.running && !stopped) step = data;
    } catch { /* a failed poll only skips one refresh */ }
    busy = false;
    if (!stopped) paint();
  };
  ids.updateWhat.hidden = true;
  ids.updateProgress.hidden = false;
  paint();
  const timer = setInterval(tick, UPDATE_POLL_EVERY);
  return {
    seconds: () => (Date.now() - began) / 1000,
    restarting() { restarting = true; paint(); },
    stop() { stopped = true; clearInterval(timer); ids.updateProgress.hidden = true; ids.updateWhat.hidden = false; },
  };
}
// After the reload that follows an update: the one toast saying how long it took.
function showUpdatedToast() {
  let done = null;
  try {
    done = JSON.parse(sessionStorage.getItem(UPDATE_DONE_KEY));
    sessionStorage.removeItem(UPDATE_DONE_KEY);
  } catch { /* storage unavailable: no toast */ }
  if (done && typeof done.version === 'string' && /^v\d+\.\d+\.\d+$/.test(done.version) && Number.isFinite(done.seconds)) {
    showToast(`Updated to ${done.version} in ${updateClock(done.seconds)}`);
  }
}
async function confirmUpdate() {
  if (updateBusy || !updateNewer(updateInfo) || updateInfo.state !== 'available') return;
  const version = updateInfo.latest;
  updateBusy = true;
  ids.updateConfirm.disabled = true;
  ids.updateConfirm.setAttribute('aria-busy', 'true');
  ids.updateCancel.disabled = true;
  updateSetError('');
  const progress = startUpdateProgress();
  let report;
  try {
    report = await updatePost('/api/update/apply', {version});
  } catch (error) {
    progress.stop();
    updateBusy = false;
    ids.updateConfirm.disabled = false;
    ids.updateConfirm.removeAttribute('aria-busy');
    ids.updateCancel.disabled = false;
    ids.updateWhat.textContent = UPDATE_WHAT.replace('VERSION', version);
    updateSetError(error.message);
    checkUpdate({force: true}); // the state may have changed under the page
    return;
  }
  if (report.timings) console.info('Update timings', report.timings);
  if (!report.restarting) { // already up to date: nothing was changed
    progress.stop();
    updateBusy = false;
    ids.updateDialog.close();
    updateInfo = null;
    checkUpdate({force: true});
    return;
  }
  progress.restarting();
  const back = await waitForRestart();
  const script = report.update_script;
  const scriptFailed = script && script.ran && script.exit_code !== 0;
  if (back && !scriptFailed) {
    try { sessionStorage.setItem(UPDATE_DONE_KEY, JSON.stringify({version, seconds: Math.round(progress.seconds())})); } catch { /* no toast then */ }
    location.reload();
    return;
  }
  progress.stop();
  updateBusy = false;
  ids.updateCancel.disabled = false;
  ids.updateCancel.textContent = 'Reload';
  ids.updateConfirm.hidden = true;
  ids.updateConfirm.removeAttribute('aria-busy');
  ids.updateWhat.textContent = '';
  updateSetError(!back ? `Updated to ${version}, but the app did not come back within 60 seconds. Open it again from the Dock.` :
    `Updated to ${version}, but a final step of the update failed. Ask your agent to finish it.${script.output_tail?.length ? `\n\n${script.output_tail.slice(-6).join('\n')}` : ''}`);
  updateReloadOnClose = true;
}
ids.updateButton.addEventListener('click', openUpdateDialog);
ids.updateConfirm.addEventListener('click', confirmUpdate);
ids.updateRecheck.addEventListener('click', () => checkUpdate({force: true}));
ids.updateDialog.addEventListener('cancel', event => { if (updateBusy) event.preventDefault(); }); // never closed halfway through an update
ids.updateDialog.addEventListener('close', () => { if (updateReloadOnClose) location.reload(); });
