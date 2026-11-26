'use strict';

// ---------- Selection and keyboard navigation over rows and cards ----------
function activeRoot() {
  return view === 'today' ? ids.todayView : view === 'list' ? ids.listView : view === 'board' ? ids.boardView : view === 'timeline' ? ids.timelineView : null;
}
function visibleRows() {
  const root = activeRoot();
  return root ? [...root.querySelectorAll('[data-id]')].filter(row => row.offsetParent !== null) : [];
}
const ROW_MAIN = '.row-title, .card-title, .tl-chip, .tl-card-main';
const ROW_CONTROLS = `.status-button, ${ROW_MAIN}, .due-button, .row-action, .tl-card-date`;
function setStops(row, on) { for (const control of row.querySelectorAll(ROW_CONTROLS)) control.tabIndex = on ? 0 : -1; }
// The selected row (else the first one) is the list's single tab stop: its controls are reachable with Tab, the others with j/k.
function markSelection() {
  const root = activeRoot();
  if (!root) return;
  const rows = [...root.querySelectorAll('[data-id]')];
  let current = null;
  for (const row of rows) {
    const selected = row.dataset.id === selectedId;
    row.classList.toggle('is-selected', selected);
    setStops(row, false);
    if (selected && row.offsetParent !== null) current = row;
  }
  const stop = current || rows.find(row => row.offsetParent !== null);
  if (stop) setStops(stop, true);
  if (view === 'timeline') markTimelineStops();
}
// The frieze and the tray are two places to Tab to: each keeps one stop, on its selected row (else its first).
function markTimelineStops() {
  for (const zone of [ids.timelineScroll, ids.timelineTray]) {
    const rows = [...zone.querySelectorAll('[data-id]')].filter(row => row.offsetParent !== null);
    const row = rows.find(item => item.dataset.id === selectedId) || rows[0];
    if (row) setStops(row, true);
  }
}
function rowFor(id) {
  const root = activeRoot();
  return root ? root.querySelector(`[data-id="${CSS.escape(id)}"]`) : null;
}
function selectAction(id, {focus = true, scroll = true} = {}) {
  selectedId = id;
  markSelection();
  const row = rowFor(id);
  if (!row) return;
  if (scroll) row.scrollIntoView({block: 'nearest'});
  if (focus) row.querySelector(ROW_MAIN)?.focus({preventScroll: true});
}
function moveSelection(delta) {
  const rows = visibleRows();
  if (!rows.length) return;
  const index = rows.findIndex(row => row.dataset.id === selectedId);
  const next = rows[index === -1 ? (delta > 0 ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, index + delta))];
  selectAndFollow(next.dataset.id);
}
// Select an action, and let an open (unmodified) detail panel follow it.
function selectAndFollow(id) {
  selectAction(id);
  if (editorOpen() && editorAction && editorAction.id !== id && !editorDirty()) {
    const action = findAction(id);
    if (action) openEditor(action, null, {focus: 'none'});
  }
}
function selectedAction() {
  const row = selectedId && rowFor(selectedId);
  return row && row.offsetParent !== null ? findAction(selectedId) : null;
}
// After a write and a refresh: the same action again, else the row now at its former place.
function focusAction(id, part = 'title', formerIndex = -1) {
  let row = rowFor(id);
  if (!row || row.offsetParent === null) {
    const rows = visibleRows();
    row = formerIndex >= 0 && rows.length ? rows[Math.min(formerIndex, rows.length - 1)] : null;
  }
  if (!row) { ids.resultCount.focus({preventScroll: true}); return; }
  selectedId = row.dataset.id;
  markSelection();
  const target = part === 'status' ? row.querySelector('.status-button') : part === 'due' ? row.querySelector('.due-button') : null;
  (target || row.querySelector(ROW_MAIN)).focus({preventScroll: true});
}

// ---------- Popovers: status menu and due date ----------
let popoverState = null;
function popoverItems() { return [...ids.popover.querySelectorAll('.menu-item, input')]; }
function openPopover(anchor, nodes, {role = 'menu', label = ''} = {}) {
  closePopover(false);
  closeMoreMenu(false);
  ids.popover.replaceChildren(...nodes);
  ids.popover.setAttribute('role', role);
  ids.popover.setAttribute('aria-label', label);
  ids.popover.hidden = false;
  anchor.setAttribute('aria-expanded', 'true');
  popoverState = {anchor};
  const rect = anchor.getBoundingClientRect();
  const box = ids.popover.getBoundingClientRect();
  let left = Math.min(rect.left, window.innerWidth - box.width - 12);
  left = Math.max(12, left);
  let top = rect.bottom + 4;
  if (top + box.height > window.innerHeight - 12) top = Math.max(12, rect.top - box.height - 4);
  ids.popover.style.left = `${left}px`;
  ids.popover.style.top = `${top}px`;
  (ids.popover.querySelector('[aria-checked="true"]') || popoverItems()[0])?.focus();
}
function closePopover(refocus = true) {
  if (!popoverState) return;
  const {anchor} = popoverState;
  popoverState = null;
  ids.popover.hidden = true;
  ids.popover.replaceChildren();
  anchor.setAttribute('aria-expanded', 'false');
  if (refocus && anchor.isConnected) anchor.focus({preventScroll: true});
}
function menuItem(content, onPick, {role = 'menuitem', checked = null, hint = ''} = {}) {
  const item = element('button', 'menu-item');
  item.type = 'button';
  item.setAttribute('role', role);
  if (checked !== null) item.setAttribute('aria-checked', String(checked));
  item.append(...content);
  if (hint) item.append(element('span', 'menu-item-hint', hint));
  item.addEventListener('click', () => { closePopover(false); onPick(); });
  return item;
}
function openStatusMenu(action, anchor) {
  const items = STATUS_ORDER.map((state, index) => menuItem(
    [statusIcon(state), element('span', 'menu-item-text', statusLabel(state))],
    () => updateStatus(action, state, anchor),
    {role: 'menuitemradio', checked: state === action.state, hint: String(index + 1)}
  ));
  openPopover(anchor, items, {label: `Status of ${action.id}`});
}
function nextMonday(day) {
  const date = parseDay(day);
  date.setDate(date.getDate() + ((8 - date.getDay()) % 7 || 7));
  return isoDay(date);
}
function openDueMenu(action, anchor) {
  const day = today();
  const choices = [['Today', day], ['Tomorrow', addDays(day, 1)]];
  if (nextMonday(day) !== addDays(day, 1)) choices.push(['Next Monday', nextMonday(day)]);
  choices.push(['In a week', addDays(day, 7)]);
  const nodes = [element('p', 'menu-heading', `Due date of ${action.id}`)];
  for (const [label, value] of choices) {
    nodes.push(menuItem([element('span', 'menu-item-text', label)], () => updateDue(action, value, anchor), {hint: DAY_FORMAT.format(parseDay(value))}));
  }
  const pick = element('label', 'menu-date');
  const input = element('input');
  input.type = 'date';
  input.value = action.due || '';
  input.setAttribute('aria-label', 'Other date');
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && input.value) { event.preventDefault(); closePopover(false); updateDue(action, input.value, anchor); }
  });
  input.addEventListener('change', () => {
    // A picked date applies at once; typing digits waits for Enter (each keystroke fires change in some browsers).
    if (input.value && input.dataset.typed !== '1') { closePopover(false); updateDue(action, input.value, anchor); }
  });
  input.addEventListener('keydown', event => { if (/^\d$/.test(event.key)) input.dataset.typed = '1'; });
  pick.append(input);
  nodes.push(element('div', 'menu-separator'), pick);
  if (action.due) nodes.push(menuItem([element('span', 'menu-item-text', 'Remove the due date')], () => updateDue(action, '', anchor)));
  openPopover(anchor, nodes, {role: 'dialog', label: `Due date of ${action.id}`});
}
ids.popover.addEventListener('keydown', event => {
  const items = popoverItems();
  const index = items.indexOf(document.activeElement);
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    if (document.activeElement?.tagName === 'INPUT' && event.target.type === 'date') return;
    event.preventDefault();
    items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
  } else if (event.key === 'Home' || event.key === 'End') {
    if (document.activeElement?.tagName === 'INPUT') return;
    event.preventDefault();
    items[event.key === 'Home' ? 0 : items.length - 1]?.focus();
  } else if (event.key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    closePopover();
  } else if (event.key === 'Tab') {
    // Focus stays in the popover: Tab and Shift+Tab cycle through its items.
    event.preventDefault();
    items[(index + (event.shiftKey ? -1 : 1) + items.length) % items.length]?.focus();
  } else if (/^[1-5]$/.test(event.key) && ids.popover.getAttribute('role') === 'menu') {
    event.preventDefault();
    ids.popover.querySelectorAll('.menu-item')[Number(event.key) - 1]?.click();
  }
});
document.addEventListener('pointerdown', event => {
  if (popoverState && !ids.popover.contains(event.target) && !popoverState.anchor.contains(event.target)) closePopover(false);
  if (!ids.moreMenu.hidden && !ids.moreMenu.parentElement.contains(event.target)) closeMoreMenu(false);
  if (brainMenuOpen() && !ids.brainSwitch.contains(event.target)) closeBrainMenu(false);
});
window.addEventListener('resize', () => closePopover(false));
for (const root of [ids.todayView, ids.listView, ids.boardView, ids.timelineScroll]) root.addEventListener('scroll', () => closePopover(false), {passive: true, capture: true});

// ---------- Render ----------
function isDocsView() { return view === 'docs' || view === 'search'; }
function renderFilterChips() {
  const actionView = ACTION_VIEWS.includes(view);
  const docs = isDocsView();
  const docsList = view === 'docs';
  ids.filters.classList.toggle('is-empty', !actionView && !docs);
  ids.projectChip.hidden = !projectScope || !(actionView || docs);
  ids.projectChipValue.textContent = scopeLabel(projectScope);
  const board = view === 'board';
  ids.ownerChip.hidden = !actionView || board;
  ids.boardOwnerChip.hidden = !board;
  ids.boardEveryone.hidden = !board;
  ids.boardEveryone.setAttribute('aria-checked', String(ids.boardOwner.value === ''));
  ids.scopeChip.hidden = !(view === 'list' || view === 'board');
  ids.groupChip.hidden = !actionView;
  ids.docProjectChip.hidden = !docs;
  ids.docTypeChip.hidden = !docs;
  ids.ownerChip.classList.toggle('is-active', ids.ownerFilter.value !== '');
  ids.boardOwnerChip.classList.toggle('is-active', ids.boardOwner.value !== '');
  ids.scopeChip.classList.toggle('is-active', ids.scopeFilter.value !== 'active');
  ids.groupChip.classList.toggle('is-active', ids.groupFilter.value !== '');
  ids.docProjectChip.classList.toggle('is-active', ids.docProject.value !== '');
  ids.docTypeChip.classList.toggle('is-active', ids.docType.value !== '');
  for (const select of [ids.ownerFilter, ids.boardOwner, ids.scopeFilter, ids.groupFilter, ids.docProject, ids.docType]) {
    const chosen = select.selectedOptions[0];
    select.parentElement.querySelector('.chip-value').textContent = chosen?.dataset.name || chosen?.textContent || '';
  }
  const active = actionView ? actionFiltersActive() : docs ? Boolean(projectScope || ids.docProject.value || ids.docType.value) : false;
  ids.resetFilters.hidden = !active;
  ids.foldAllButton.hidden = view !== 'list' || !listProjectKeys().length;
  const archivable = (actionView || view === 'docs') && scopeArchive();
  ids.archiveScopeButton.hidden = !archivable;
  if (archivable) {
    ids.archiveScopeButton.textContent = archivable.kind === 'client' ? 'Archive this client…' : 'Archive this project…';
    ids.archiveScopeButton.title = `Archive ${archivable.label}: check what moves first`;
  }
}
function render() {
  closePopover(false);
  renderSyncPullButton();
  if (view === 'priorities') renderPriorities();
  else if (view === 'tools') countTools();
  else if (view === 'git') renderGit();
  else if (view === 'settings') renderSettings();
  else if (view === 'archives') renderArchives();
  else if (isDocsView()) renderDocsView();
  else {
    const base = filteredBase();
    if (view === 'today') renderToday(base);
    else if (view === 'list') renderList(scoped(base));
    else if (view === 'timeline') renderTimeline(base);
    else renderBoard(base);
    markSelection();
  }
  renderFilterChips();
}
function setView(next, persist = true) {
  if (!VIEWS.includes(next)) next = 'today';
  view = next;
  closePopover(false);
  ids.prioView.hidden = next !== 'priorities';
  ids.todayView.hidden = next !== 'today';
  ids.listView.hidden = next !== 'list';
  ids.boardView.hidden = next !== 'board';
  ids.timelineView.hidden = next !== 'timeline';
  if (next === 'timeline') timelineAnchor = true;
  ids.docsView.hidden = !isDocsView();
  ids.archivesView.hidden = next !== 'archives';
  if (next !== 'archives') archiveSearch = null;
  ids.searchInput.placeholder = next === 'archives' ? 'Search the archives' : 'Search actions and documents';
  ids.searchInput.setAttribute('aria-label', next === 'archives' ? 'Search the archived projects (words or "exact phrase")' : 'Search the actions and the documents of the brain (words or "exact phrase")');
  ids.toolsView.hidden = next !== 'tools';
  ids.gitView.hidden = next !== 'git';
  ids.settingsView.hidden = next !== 'settings';
  ids.syncInfo.hidden = next !== 'git';
  for (const [name, id] of Object.entries(NAV_BUTTONS)) {
    if (name === next) ids[id].setAttribute('aria-current', 'page'); else ids[id].removeAttribute('aria-current');
  }
  ids.viewTitle.textContent = VIEW_TITLES[next];
  fitCardToView(); // the Mac window's card: away on the views without projects (app/shell.js)
  if (next !== 'search' && ids.searchInput.value) { // any other view ends the search: the field never says something the page does not show
    ids.searchInput.value = '';
    clearTimeout(docTimer);
    docSearchRequest += 1;
    resetSearchResults();
    setDocStatus('');
  }
  ids.gitStatus.hidden = next !== 'git';
  ids.resultCount.textContent = '';
  render();
  if (next === 'priorities') loadPriorities();
  if (next === 'tools' && !tools.length) loadTools();
  if (next === 'git') loadGit();
  if (next === 'settings' && !settingsData) loadSettings();
  if (next === 'archives') loadArchives();
  if (isDocsView()) refreshDocsView();
  if (persist) {
    saveUIState();
    closeDrawer(false);
  }
}
function populateProjects() {
  const editing = ids.editorProject.value;
  ids.editorProject.replaceChildren(...snapshot.registers.map(register => new Option(register.label, register.path)));
  populateGroupFilter();
  populateOwnerFilters();
  ids.editorProject.value = editing || defaultRegister();
  if (!editorOpen()) fillGroupOptions();
}
function defaultRegister() {
  if (snapshot.registers.some(register => register.path === projectScope)) return projectScope;
  return snapshot.registers.find(register => inScope(register.path))?.path || snapshot.registers[0]?.path || '';
}
// Group filter: "All", "No group", then the groups as `register|slug`; one <optgroup> per project unless one register is selected.
function populateGroupFilter() {
  const selected = ids.groupFilter.value || pendingGroup;
  pendingGroup = '';
  const single = snapshot.registers.some(register => register.path === projectScope);
  const entries = [];
  for (const register of snapshot.registers) {
    if (!inScope(register.path)) continue;
    for (const slug of register.groups || []) entries.push({value: `${register.path}|${slug}`, project: register.label, label: groupLabel(slug), key: slug});
  }
  entries.sort(compareGroups);
  const nodes = [];
  for (const entry of entries) {
    if (single) { nodes.push(new Option(entry.label, entry.value)); continue; }
    if (nodes.at(-1)?.label !== entry.project) { const section = document.createElement('optgroup'); section.label = entry.project; nodes.push(section); }
    nodes.at(-1).append(new Option(entry.label, entry.value));
  }
  ids.groupFilter.replaceChildren(new Option('All', ''), new Option('No group', 'none'), ...nodes);
  ids.groupFilter.value = [...ids.groupFilter.options].some(option => option.value === selected) ? selected : '';
  titleGroupFilter();
}
function titleGroupFilter() {
  const chosen = ids.groupFilter.selectedOptions[0];
  ids.groupFilter.title = chosen?.value && chosen.parentElement.label ? `${chosen.parentElement.label}: ${chosen.textContent}` : '';
}
