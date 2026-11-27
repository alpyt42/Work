'use strict';

// ---------- Undo ----------
// Undo labels come from the server ("status of ABC-001 → In progress"): the arrow is shown as "to" in the interface.
// The client part of a project label (`acme / demo`) is shown by the client's name, as everywhere else.
function nameLabels(text) { return String(text || '').replace(/([^\s/]+) \/ /g, (whole, client) => `${displayClient(client)} / `); }
function undoText(label) { return nameLabels(String(label || '').replace(/\s*→\s*/g, ' to ')); }
function setUndo(state) {
  undoState = state || {available: false, label: null, depth: 0};
  renderUndo();
}
function renderUndo() {
  const text = undoState.available ? `Undo: ${undoText(undoState.label)}` : 'Nothing to undo';
  ids.undoLabel.textContent = text;
  ids.undoButton.setAttribute('aria-disabled', String(undoBusy || !undoState.available));
  ids.undoButton.title = text;
  if (!undoState.available || undoBusy) ids.toastAction.hidden = true;
}
async function loadUndo() {
  try { setUndo(await request('/api/undo')); } catch { /* The menu keeps its last known state. */ }
}
async function undoLast() {
  if (undoBusy || !undoState.available) return;
  undoBusy = true;
  renderUndo();
  try {
    const result = await request('/api/undo', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({label: undoState.label})
    });
    setUndo(result.undo);
    detailCache.clear();
    await refresh();
    if (result.restored && isDocsView()) openDoc(result.action_id, {nav: 'root'}); // a deleted note is back: show it
    else if (isDocsView() && docCurrent && !docEditing && docCurrent.id === result.action_id) openDoc(result.action_id, {nav: 'keep'}); // an undone edit or tick
    // An undone note or subtask leaves the action's line as it was: the open panel reads its details again.
    if (editorOpen() && editorAction?.id === result.action_id) reloadDetails();
    showToast(`Undone: ${undoText(result.undone)}`);
  } catch (error) {
    showToast(error.message);
    await refresh();
  } finally {
    undoBusy = false;
    renderUndo();
  }
}

// ---------- Refresh ----------
// A refresh redraws the active view: keep its scroll positions (rows, board, every column).
function viewScrolls() {
  return {
    today: ids.todayView.scrollTop, list: ids.listView.scrollTop, board: ids.boardView.scrollLeft,
    // Not while the next draw still has to bring today into view.
    timeline: timelineAnchor ? null : {left: ids.timelineScroll.scrollLeft, top: ids.timelineScroll.scrollTop},
    columns: [...ids.boardView.querySelectorAll('.board-cards')].map(cards => cards.scrollTop)
  };
}
function restoreViewScrolls(scrolls) {
  ids.todayView.scrollTop = scrolls.today;
  ids.listView.scrollTop = scrolls.list;
  ids.boardView.scrollLeft = scrolls.board;
  if (scrolls.timeline) { ids.timelineScroll.scrollLeft = scrolls.timeline.left; ids.timelineScroll.scrollTop = scrolls.timeline.top; }
  ids.boardView.querySelectorAll('.board-cards').forEach((cards, index) => { cards.scrollTop = scrolls.columns[index] || 0; });
}
function showError(message) {
  ids.errorBanner.textContent = message;
  ids.errorBanner.hidden = false;
}
async function refresh() {
  loadPriorities(); // the file is written by /priorities, outside the page: read again with the rest
  loadGit({quiet: view !== 'git'}); // the badge of the Sync button follows the writes made from the page
  if (isDocsView()) refreshDocsView();
  if (view === 'archives' || archivesData) loadArchives(); // an archive or an unarchive changes both lists
  try {
    snapshot = nameSnapshot(await request('/api/actions'));
    detailCache.clear();
    loadUndo();
    ids.errorBanner.hidden = true;
    ids.lastSync.textContent = `Refreshed at ${TIME_FORMAT.format(new Date())}`;
    validateScope();
    populateProjects();
    setSummary();
    const scrolls = viewScrolls();
    render();
    restoreViewScrolls(scrolls);
    syncEditorAfterRefresh();
  } catch (error) {
    if (error.stale) return;
    showError(error.message);
  }
}
// Counters and rows follow a write made from the panel (a note), without moving the focus.
async function refreshQuietly() {
  try {
    snapshot = nameSnapshot(await request('/api/actions'));
    loadGit({quiet: true});
    setSummary();
    const scrolls = viewScrolls();
    if (ACTION_VIEWS.includes(view) || view === 'search') { render(); restoreViewScrolls(scrolls); }
  } catch { /* The next refresh will catch up. */ }
}
