'use strict';

// ---------- Git: save and send (and check online, pull) ----------
// One card per brain of the Work, the chosen one first (never Work itself). The server says what is possible (`state`, `action`)
// and writes the sentences; this draws them, with the changed notes in plain words (title, project, New / Edited / Deleted / Renamed),
// and runs the one button of a card after a confirmation. No path, branch, hash or line count is shown.
const GIT_STATE_ICONS = {clean: 'gitSaved', changes: 'gitEdited', unsent: 'gitSend', behind: 'gitBehind', unavailable: 'gitOff'};
const GIT_VISIBLE_NOTES = 8;
const GIT_FETCH_EVERY = 10 * 60 * 1000; // background check of the online copies (the server also throttles to one per 5 minutes)
const GIT_FOCUS_AFTER = 5 * 60 * 1000; // back on the window: check again when the last check is older than this
const GIT_VISIBLE_LINES = 3000; // the server cuts a comparison there
const GIT_CHANGE_TEXT = {New: 'New', Edited: 'Edited', Deleted: 'Deleted', Renamed: 'Renamed'};
let gitCards = [];
let gitLoaded = false;
let gitLoading = null;
let gitLoadId = 0; // bumped when the brain changes: a load started before it no longer owns `gitLoading`
let gitChangesRequest = 0;
let gitConfirmCard = null; // the card the open confirmation is about, as the person saw it
const gitResults = new Map(); // brain name -> what the last save or send said (shown in its card)
const gitBusy = new Set(); // brain names being saved or sent
const gitExpanded = new Set(); // brain names whose whole list of notes is shown
let gitFetching = false; // a check of the online copies is running (a pull is `gitBusy`)
let gitLastFetchAt = 0; // when this page last got an answer from a check (milliseconds)
// "2 hours ago", "yesterday", "3 days ago"; a date after a month.
function relativeTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const seconds = (date.getTime() - Date.now()) / 1000;
  const formatter = new Intl.RelativeTimeFormat(LOCALE, {numeric: 'auto'});
  for (const [limit, unit, size] of [[60, 'second', 1], [3600, 'minute', 60], [86400, 'hour', 3600], [2592000, 'day', 86400]]) {
    if (Math.abs(seconds) < limit) return formatter.format(Math.round(seconds / size), unit);
  }
  return DAY_YEAR_FORMAT.format(date);
}
function orderedGitCards() {
  return [...gitCards].sort((a, b) => Number(b.name === currentBrain) - Number(a.name === currentBrain));
}
function gitPendingCount() { return gitCards.filter(card => card.pending).length; }
function gitPullPlural(count) { return plural(count, 'change'); }
// The sidebar button: shown only when the current brain is behind its online copy and can simply be brought up to date.
function renderSyncPullButton() {
  const card = gitLoaded ? gitCards.find(item => item.name === currentBrain) : null;
  const show = Boolean(card && card.pullable && card.behind > 0);
  ids.syncPullButton.hidden = !show;
  if (!show) return;
  const busy = gitBusy.has(card.name);
  ids.syncPullButtonLabel.textContent = busy ? 'Syncing…' : `Sync ${gitPullPlural(card.behind)}`;
  ids.syncPullButton.disabled = busy;
  ids.syncPullButton.setAttribute('aria-busy', String(busy));
  ids.syncPullButton.title = `${gitPullPlural(card.behind)} from another computer ${card.behind === 1 ? 'is' : 'are'} waiting online. Click to bring ${card.behind === 1 ? 'it' : 'them'} into ${card.label}.`;
}
// "Checked online 3 minutes ago", from the newest check of any brain; a failed one is named quietly.
function gitCheckText() {
  const stamps = gitCards.map(card => card.fetched_at).filter(Boolean).sort();
  const failed = gitCards.filter(card => card.fetch_error);
  const parts = [stamps.length ? `Checked online ${relativeTime(stamps[stamps.length - 1])}` : 'Not checked online yet'];
  if (failed.length) parts.push(failed.length === 1 && gitCards.length === 1 ? failed[0].fetch_error : `${plural(failed.length, 'brain')} could not be checked`);
  return parts.join(' · ');
}
function gitNoteRow(card, note) {
  const row = element('button', 'git-note');
  row.type = 'button';
  row.dataset.focusKey = `note:${card.name}:${note.path}`;
  const change = element('span', `git-change git-change-${note.change.toLowerCase()}`, GIT_CHANGE_TEXT[note.change] || note.change);
  const main = element('span', 'git-note-main');
  main.append(element('span', 'git-note-title', note.title));
  if (note.project) main.append(element('span', 'git-note-project', note.project));
  const see = element('span', 'git-note-see', 'See changes');
  see.append(svgIcon(ICONS.chevron));
  row.append(change, main, see);
  row.title = note.from ? `${note.from} → ${note.path}` : note.path;
  row.setAttribute('aria-label', `${GIT_CHANGE_TEXT[note.change] || note.change}: ${note.title}${note.project ? `, ${note.project}` : ''}. See changes`);
  row.addEventListener('click', () => openGitChanges(card, note));
  return row;
}
function gitResultBox(card, result) {
  const tone = result.ok ? 'ok' : result.saved ? 'partial' : 'failed';
  const box = element('div', `git-result git-result-${tone}`);
  box.setAttribute('role', result.ok ? 'status' : 'alert');
  const body = element('div', 'git-result-body');
  body.append(element('p', 'git-result-message', result.message));
  if (result.details) {
    const details = element('details', 'git-details');
    details.append(element('summary', '', 'Details'), element('pre', '', result.details));
    body.append(details);
  }
  const dismiss = iconButton('icon-button', 'Dismiss this message', '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>');
  dismiss.dataset.focusKey = `dismiss:${card.name}`;
  dismiss.addEventListener('click', () => { gitResults.delete(card.name); renderGit(`card:${card.name}`); });
  box.append(body, dismiss);
  return box;
}
function gitCardNode(card) {
  const section = element('section', 'git-card');
  section.dataset.state = card.state;
  section.dataset.accent = accentFor(card.name);
  section.dataset.focusKey = `card:${card.name}`;
  section.tabIndex = -1;
  section.setAttribute('aria-labelledby', `gitTitle-${card.name}`);
  const head = element('div', 'git-head');
  const title = element('h2', '', card.label);
  title.id = `gitTitle-${card.name}`;
  head.append(title);
  head.append(onlineCopyPopover(card));
  if (card.name === currentBrain && gitCards.length > 1) head.append(element('span', 'git-current', 'Current brain'));
  const status = element('div', 'git-status');
  const badge = element('span', 'git-badge');
  badge.append(svgIcon(ICONS[GIT_STATE_ICONS[card.state] || 'gitOff']));
  const text = element('div', 'git-status-text');
  text.append(element('p', 'git-sentence', card.message));
  if (card.last_saved) {
    const last = element('p', 'git-last', `Last saved: ${relativeTime(card.last_saved)}`);
    last.title = formatStamp(card.last_saved.slice(0, 16).replace('T', ' '));
    text.append(last);
  }
  if (card.fetch_error) {
    const problem = element('p', 'git-last git-fetch-error', card.fetch_error);
    if (card.fetched_at) problem.title = `Tried ${formatStamp(card.fetched_at.slice(0, 16).replace('T', ' '))}`;
    text.append(problem);
  }
  status.append(badge, text);
  section.append(head, status);
  const result = gitResults.get(card.name);
  if (result) section.append(gitResultBox(card, result));
  if (card.changes.length) {
    const total = card.count;
    const heading = element('div', 'git-notes-head');
    heading.append(element('h3', '', plural(total, 'changed note')));
    section.append(heading);
    const expanded = gitExpanded.has(card.name);
    const shown = expanded ? card.changes : card.changes.slice(0, GIT_VISIBLE_NOTES);
    const list = element('ul', 'git-notes');
    for (const note of shown) {
      const item = element('li');
      item.append(gitNoteRow(card, note));
      list.append(item);
    }
    section.append(list);
    if (card.changes.length > GIT_VISIBLE_NOTES) {
      const toggle = element('button', 'link-button git-more', expanded ? 'Show fewer' : `Show all ${plural(card.changes.length, 'note')}`);
      toggle.type = 'button';
      toggle.dataset.focusKey = `more:${card.name}`;
      toggle.setAttribute('aria-expanded', String(expanded));
      toggle.addEventListener('click', () => {
        if (gitExpanded.has(card.name)) gitExpanded.delete(card.name); else gitExpanded.add(card.name);
        renderGit(`more:${card.name}`);
      });
      section.append(toggle);
    }
    if (card.more) section.append(element('p', 'git-last', `and ${plural(card.more, 'more note')}`));
  }
  if (card.action) {
    const busy = gitBusy.has(card.name);
    const actions = element('div', 'git-actions');
    const label = {save: 'Save and send', send: 'Send', pull: 'Sync'}[card.action] || 'Send';
    const verb = {save: 'Saving and sending', send: 'Sending', pull: 'Syncing'}[card.action] || 'Sending';
    const button = element('button', 'button button-primary', busy ? `${verb}…` : label);
    button.type = 'button';
    button.dataset.focusKey = `go:${card.name}`;
    button.disabled = busy;
    button.setAttribute('aria-busy', String(busy));
    button.setAttribute('aria-label', busy ? `${verb} ${card.label}` : card.action === 'pull' ? `Sync ${gitPullPlural(card.behind)} into ${card.label}` : `${label} for ${card.label}`);
    button.addEventListener('click', () => card.action === 'save' ? askGitSave(card) : runGit(card, card.action === 'pull' ? 'pull' : 'send'));
    actions.append(button);
    section.append(actions);
  }
  return section;
}
// Draws the cards again, keeping the scroll position and the focus (`fallbackKey`: where the focus goes when its control is gone).
function renderGit(fallbackKey = '') {
  const pending = gitPendingCount();
  renderSyncPullButton();
  ids.gitCount.textContent = gitLoaded && pending ? String(pending) : '';
  ids.gitButton.setAttribute('aria-label', gitLoaded && pending ? `Sync, ${plural(pending, 'brain')} to save or send` : 'Sync');
  if (view !== 'git') return;
  ids.gitCheckInfo.textContent = gitLoaded ? gitCheckText() : '';
  ids.gitCheckButton.disabled = gitFetching;
  ids.gitCheckButton.textContent = gitFetching ? 'Checking…' : 'Check online';
  const behind = gitCards.filter(card => card.pullable).length;
  ids.resultCount.textContent = !gitLoaded ? '' : pending ? `${plural(pending, 'brain')} to save or send` : behind ? `${plural(behind, 'brain')} to update` : 'Everything is saved';
  if (!gitLoaded) return;
  const focused = ids.gitCards.contains(document.activeElement) ? document.activeElement.dataset.focusKey || '' : '';
  const scroll = ids.gitView.scrollTop;
  ids.gitCards.replaceChildren(...orderedGitCards().map(gitCardNode));
  ids.gitView.scrollTop = scroll;
  const find = key => key ? [...ids.gitCards.querySelectorAll('[data-focus-key]')].find(node => node.dataset.focusKey === key) : null;
  const target = find(focused) || find(fallbackKey);
  if (target && (focused || fallbackKey)) target.focus({preventScroll: true});
}
// A message tied to a state of the brain goes when that state does; the others stay for one more look.
function dropStaleGitResults() {
  for (const [name, result] of [...gitResults]) {
    const card = gitCards.find(item => item.name === name);
    if (!card) gitResults.delete(name);
    else if (result.version) { if (card.version !== result.version) gitResults.delete(name); }
    else if (result.seen) gitResults.delete(name);
    else result.seen = true;
  }
}
function loadGit({quiet = false} = {}) {
  if (gitLoading) return gitLoading;
  if (!quiet) {
    ids.gitStatus.textContent = gitLoaded ? 'Refreshing…' : 'Loading…';
    ids.gitStatus.classList.remove('git-status-error');
    if (!gitLoaded && view === 'git') ids.gitCards.replaceChildren(element('p', 'loading-note', 'Loading…'));
  }
  const loadId = gitLoadId;
  gitLoading = (async () => {
    try {
      const data = await request('/api/git');
      if (!Array.isArray(data.brains)) throw new Error('Restart tasks-web: this page is newer than the server that is running.');
      gitCards = data.brains;
      gitLoaded = true;
      dropStaleGitResults();
      ids.gitStatus.textContent = `Refreshed at ${TIME_FORMAT.format(new Date())}`;
      renderGit();
    } catch (error) {
      if (error.stale || loadId !== gitLoadId || (quiet && gitLoaded)) return;
      ids.gitStatus.textContent = 'Failed';
      ids.gitStatus.classList.add('git-status-error');
      if (!gitLoaded && view === 'git') {
        const message = element('p', 'error-note', error.message);
        message.setAttribute('role', 'alert');
        ids.gitCards.replaceChildren(message);
      } else if (view === 'git') showToast(`Sync: ${error.message}`);
    } finally {
      if (loadId === gitLoadId) gitLoading = null;
    }
  })();
  return gitLoading;
}
function replaceGitCard(card) {
  const index = gitCards.findIndex(item => item.name === card.name);
  if (index >= 0) gitCards[index] = card; else gitCards.push(card);
}
// The confirmation says what will happen, in the person's words, and lists the notes (the server refuses if they have changed since).
function askGitSave(card) {
  const count = card.count;
  ids.gitConfirmText.textContent = `Save ${plural(count, 'changed note')} of ${card.label} and send ${count === 1 ? 'it' : 'them'} to its online copy?`
    + (card.unsent ? ' What was saved earlier and not sent yet goes with it.' : '');
  const shown = card.changes.slice(0, GIT_VISIBLE_NOTES);
  ids.gitConfirmList.replaceChildren(...shown.map(note => element('li', '', note.title)));
  const rest = count - shown.length;
  if (rest > 0) ids.gitConfirmList.append(element('li', 'git-confirm-more', `and ${plural(rest, 'more note')}`));
  ids.gitConfirmDialog.dataset.accent = accentFor(card.name);
  gitConfirmCard = card;
  ids.gitConfirmDialog.showModal();
}
// Asks every brain's online copy whether it has newer changes (`force`: the person asked, so the server's 5-minute throttle is skipped).
// Not `request()`: a check can take a while and must not hold back a brain switch; the cards it returns are the same for every brain.
async function fetchGit({force = false} = {}) {
  if (gitFetching) return;
  gitFetching = true;
  if (view === 'git') renderGit();
  try {
    const data = await updatePost('/api/git/fetch', force ? {force: true} : {});
    if (Array.isArray(data.brains)) {
      gitCards = data.brains;
      gitLoaded = true;
      dropStaleGitResults();
    }
    gitLastFetchAt = Date.now();
  } catch (error) {
    if (force) showToast(`Check online: ${error.message}`);
  } finally {
    gitFetching = false;
    renderGit();
  }
}
// Background checks: at start, every 10 minutes and when the window comes back after a while. Quiet: nothing is shown but the cards.
function fetchGitInBackground() {
  if (document.hidden || gitFetching || gitBusy.size) return;
  fetchGit();
}
async function runGit(card, action) {
  if (gitBusy.has(card.name)) return false;
  gitBusy.add(card.name);
  gitResults.delete(card.name);
  let succeeded = false;
  renderGit(`go:${card.name}`);
  try {
    const result = await request(`/api/git/${action}`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({version: card.version})
    }, card.name);
    replaceGitCard(result.brain);
    gitResults.set(card.name, {ok: result.ok, saved: result.saved, message: result.message, details: result.details, version: result.ok ? '' : result.brain.version});
    succeeded = result.ok;
    if (succeeded && action === 'pull') {
      showToast(result.message);
      refresh(); // the actions and the notes changed under the page
    }
  } catch (error) {
    // Refused before anything ran (the notes changed, the brain is behind, another save is running…): say so, and show the brain as it is now.
    gitResults.set(card.name, {ok: false, saved: false, message: error.message, details: '', version: ''});
    await loadGit({quiet: true});
  } finally {
    gitBusy.delete(card.name);
    renderGit(`card:${card.name}`);
  }
  return succeeded;
}
// The sidebar button: pull the current brain; on a refusal, open the Sync view where the reason is written.
async function pullCurrentBrain() {
  const card = gitCards.find(item => item.name === currentBrain);
  if (!card || !card.pullable || gitBusy.has(card.name)) return;
  const done = await runGit(card, 'pull');
  if (!done) setView('git');
}
ids.syncPullButton.addEventListener('click', pullCurrentBrain);
ids.gitCheckButton.addEventListener('click', () => fetchGit({force: true}));
// Also when a page loaded hidden (a background tab) is first shown: the check at start was skipped then.
function fetchGitIfStale() { if (Date.now() - gitLastFetchAt > GIT_FOCUS_AFTER) fetchGitInBackground(); }
window.addEventListener('focus', fetchGitIfStale);
document.addEventListener('visibilitychange', () => { if (!document.hidden) fetchGitIfStale(); });
async function openGitChanges(card, note) {
  const requestId = ++gitChangesRequest;
  ids.gitChangesTitle.textContent = note.title;
  ids.gitChangesMeta.textContent = [GIT_CHANGE_TEXT[note.change] || note.change, note.project, card.label].filter(Boolean).join(' · ');
  ids.gitChangesBody.replaceChildren(element('p', 'git-changes-message', 'Loading…'));
  ids.gitChangesDialog.dataset.accent = accentFor(card.name);
  if (!ids.gitChangesDialog.open) ids.gitChangesDialog.showModal();
  ids.gitChangesBody.scrollTop = 0;
  try {
    const data = await request(`/api/git/changes?${new URLSearchParams({path: note.path})}`, {}, card.name);
    if (requestId === gitChangesRequest) renderGitChanges(data);
  } catch (error) {
    if (requestId !== gitChangesRequest || error.stale) return;
    ids.gitChangesBody.replaceChildren(element('p', 'git-changes-message', error.status === 404 ? 'This note has no change to save any more. Refresh the list.' : error.message));
  }
}
function gitChangesMessage(data) {
  if (data.hidden) return 'This file may hold a secret, so its content is not shown.';
  if (data.binary) return 'This file is not text, so there is nothing to compare here.';
  if (data.too_large) return 'This note is too large to compare here.';
  if (data.unchanged) {
    return {New: 'This note is empty.', Deleted: 'This note was empty.', Renamed: 'This note was moved or renamed. Its text did not change.'}[data.change]
      || 'Nothing to show: the text of this note did not change.';
  }
  return '';
}
function renderGitChanges(data) {
  const message = gitChangesMessage(data);
  if (message) { ids.gitChangesBody.replaceChildren(element('p', 'git-changes-message', message)); return; }
  const lines = element('div', 'git-lines');
  for (const [kind, value] of data.blocks) {
    if (kind === 'gap') {
      lines.append(element('span', 'git-gap', `${plural(value, 'unchanged line')} not shown`));
      continue;
    }
    const line = element('span', `git-line git-line-${kind}`);
    if (kind !== 'ctx') line.append(element('span', 'sr-only', kind === 'add' ? 'Added: ' : 'Removed: '));
    line.append(element('span', 'git-line-text', value));
    lines.append(line);
  }
  const nodes = [element('p', 'git-legend', 'What was saved last time against what is there now: removed lines are struck through, added lines are highlighted.'), lines];
  if (data.truncated) nodes.push(element('p', 'git-truncated', `Only the first ${GIT_VISIBLE_LINES} lines are shown.`));
  ids.gitChangesBody.replaceChildren(...nodes);
}
function closeGitDialogs() {
  gitChangesRequest += 1;
  gitConfirmCard = null;
  for (const dialog of [ids.gitConfirmDialog, ids.gitChangesDialog]) if (dialog.open) dialog.close();
}
ids.gitConfirmGo.addEventListener('click', () => {
  const card = gitConfirmCard;
  gitConfirmCard = null;
  ids.gitConfirmDialog.close();
  if (card) runGit(card, 'save');
});
ids.gitChangesClose.addEventListener('click', () => ids.gitChangesDialog.close());
// A click on the backdrop closes the comparison, as it does for the other dialogs of the page.
ids.gitChangesDialog.addEventListener('click', event => { if (event.target === ids.gitChangesDialog) ids.gitChangesDialog.close(); });
