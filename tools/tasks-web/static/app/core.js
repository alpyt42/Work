'use strict';

// The page's script is the files of static/app/, loaded in order by index.html: they share one global scope, and code
// that runs while a file loads may only call functions of that file or of an earlier one (README.md, "Code layout").

const token = document.querySelector('meta[name="csrf-token"]').content;
const ids = Object.fromEntries([
  'app', 'sidebar', 'scrim', 'sidebarToggle', 'brainMini', 'sidebarClose', 'mainContent',
  'brainSwitch', 'brainStatic', 'brainStaticName', 'brainButton', 'brainName', 'brainMenu',
  'prioButton', 'prioCount', 'prioView', 'todayButton', 'listButton', 'boardButton', 'timelineButton', 'docsButton', 'archivesButton', 'toolsButton', 'gitButton', 'settingsButton',
  'archiveScopeButton', 'archivesView', 'archiveStatus', 'archiveList', 'archivePane', 'archiveBack', 'archivePaneTitle', 'archivePaneMeta', 'archiveUnarchive',
  'archivePaneEmpty', 'archiveBody', 'archiveDialog', 'archiveHeading', 'archiveText', 'archiveDialogList', 'archiveDialogError', 'archiveCancel', 'archiveConfirm',
  'todayCount', 'openCount', 'gitCount', 'projectNav', 'lastSync',
  'moreButton', 'moreMenu', 'refreshButton', 'undoButton', 'undoLabel', 'shortcutsButton', 'quitButton',
  'viewTitle', 'resultCount', 'gitStatus', 'searchField', 'searchInput', 'newNoteButton', 'newButton',
  'filters', 'projectChip', 'projectChipValue', 'projectChipClear', 'ownerChip', 'ownerFilter', 'boardOwnerChip', 'boardOwner', 'boardEveryone', 'scopeChip', 'scopeFilter',
  'groupChip', 'groupFilter', 'docProjectChip', 'docProject', 'docTypeChip', 'docType', 'resetFilters', 'foldAllButton', 'errorBanner',
  'todayView', 'listView', 'boardView', 'timelineView', 'timelineBack', 'timelineToday', 'timelineForward', 'timelineLate', 'timelineDone', 'timelineScale', 'timelineSummary',
  'timelineScroll', 'timelineTray', 'timelineTrayToggle', 'timelineTrayCount', 'timelineTrayMore', 'timelineTrayHint', 'timelineTraySearch',
  'timelineTrayBody', 'timelineTrayList', 'docsView', 'docStatus', 'docList', 'docPane', 'docBack', 'docPaneTitle', 'docPaneMeta',
  'docPanePath', 'docEdit', 'docDelete', 'docCancel', 'docSave', 'docPaneEmpty', 'docPaneError', 'docArticle', 'docEditorToolbar', 'docEditor',
  'toolsView', 'toolsCatalog', 'toolResult', 'toolResultTitle', 'toolResultCommand', 'toolResultStatus', 'toolResultEmpty', 'toolResultOutput',
  'settingsView', 'gitView', 'gitCards', 'syncInfo', 'gitConfirmDialog', 'gitConfirmText', 'gitConfirmList', 'gitConfirmGo',
  'gitChangesDialog', 'gitChangesTitle', 'gitChangesMeta', 'gitChangesBody', 'gitChangesClose',
  'editor', 'editorForm', 'editorTitle', 'editorHint', 'closeEditor', 'editorProjectField', 'editorProject', 'editorActionTitle',
  'editorState', 'editorOwner', 'editorDue', 'editorScheduled', 'editorPriority', 'editorGroup', 'editorGroupNewLabel',
  'editorGroupNew', 'editorGroupHint', 'editorHistory', 'editorHistoryCount', 'addNoteButton', 'editorHistoryList', 'noteForm',
  'editorSubtasks', 'editorSubtasksCount', 'editorSubtasksBar', 'editorSubtaskList', 'subtaskForm', 'subtaskInput', 'submitSubtask', 'subtaskHint', 'subtaskError',
  'noteInput', 'noteWords', 'submitNote', 'closeNoteForm', 'noteError', 'editorStamps', 'editorError', 'deleteEditor', 'cancelEditor', 'saveEditor',
  'popover', 'newNoteDialog', 'newNoteForm', 'closeNewNote', 'newNoteTitle', 'newNoteProject', 'newNoteWhere', 'newNoteToolbar', 'newNoteContent',
  'newNoteError', 'cancelNewNote', 'saveNewNote', 'deleteNoteDialog', 'deleteNoteHeading', 'deleteNoteText', 'deleteNoteLinks', 'deleteNoteError', 'deleteNoteCancel', 'deleteNoteConfirm', 'updateButton', 'updateButtonLabel', 'updateDialog', 'updateHeading', 'updateText', 'updateNotes', 'updateList', 'updateWhat', 'updateError', 'updateCancel', 'updateRecheck', 'updateConfirm', 'quitDialog', 'quitConfirm', 'shortcutsDialog', 'toast', 'toastText', 'toastAction'
].map(id => [id, document.getElementById(id)]));

// The interface text is English; dates, relative times, case changes and sorting follow the browser's locale.
const LOCALE = navigator.language || undefined;

// ---------- Session state (view and filters of this tab; no task content) ----------
const UI_STATE_KEY = 'actions-brain-ui-v1';
function readUIState() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(UI_STATE_KEY));
    return saved && typeof saved === 'object' ? saved : {};
  } catch { return {}; }
}
const savedUI = readUIState();
// `search` is the results page of the header field: no button, no digit, never restored (it has no query to show).
const VIEWS = ['priorities', 'today', 'list', 'board', 'timeline', 'docs', 'search', 'archives', 'tools', 'git', 'settings'];
const ACTION_VIEWS = ['today', 'list', 'board', 'timeline'];
const VIEW_TITLES = {priorities: 'Priorities', today: 'Today', list: 'Actions', board: 'Board', timeline: 'Timeline', docs: 'Docs', search: 'Search', archives: 'Archives', tools: 'Tools', git: 'Sync', settings: 'Settings'};
const NAV_BUTTONS = {priorities: 'prioButton', today: 'todayButton', list: 'listButton', board: 'boardButton', timeline: 'timelineButton', docs: 'docsButton', archives: 'archivesButton', tools: 'toolsButton', git: 'gitButton', settings: 'settingsButton'};
// The Docs view was called Notes: a view saved under the old name opens it.
let view = VIEWS.includes(savedUI.view) && savedUI.view !== 'search' ? savedUI.view : savedUI.view === 'notes' ? 'docs' : 'today';
let searchReturn = 'today'; // the view the results page goes back to
// The project filter of the sidebar: '' (all), a register path, or a folder prefix ending with '/' (a client and its missions).
let projectScope = typeof savedUI.project === 'string' ? savedUI.project : '';
let pendingGroup = typeof savedUI.group === 'string' ? savedUI.group : '';
// Folded sections, shared by the list and the board: `register|slug` for a group, `register|` for the loose actions of a project,
// `p:register` for a project, '|' for "No group" in a board column.
const foldedGroups = new Set(Array.isArray(savedUI.foldedGroups) ? savedUI.foldedGroups.filter(key => typeof key === 'string') : []);
// Timeline: the range (two, six, quarter), whether done actions show, whether the next draw brings today into view, the last layout.
let timelineRange = ['two', 'six', 'quarter'].includes(savedUI.timelineRange) ? savedUI.timelineRange : 'six';
let timelineDone = savedUI.timelineDone === true;
let timelineAnchor = true;
let timelineModel = null;
let timelineNarrow = false;
let timelineSpot = ''; // 'overdue', 'week', 'next': the others dim
let timelineTrayOpen = typeof savedUI.timelineTray === 'boolean' ? savedUI.timelineTray : null; // null: open on a wide page, closed on a narrow one
const timelineFolded = new Set(Array.isArray(savedUI.timelineFolded) ? savedUI.timelineFolded.filter(key => typeof key === 'string') : []); // folded tray groups: `vague|register`, `none|register`
let timelineOwners = new Map(); // owner → how a chip names them
let timelineBase = []; // the actions the view was last drawn from
let timelineWidth = 0;
let timelineDrag = null;
let snapshot = {actions: [], registers: [], owner: '', today: ''};
let toastTimer;
let tools = [];
// Settings view: the last answer of /api/settings, the request in flight, and the last error.
let settingsData = null;
let settingsLoading = null;
let settingsError = '';
let updateInfo = null; // the last answer of POST /api/update/check; null before the first one
let updateChecking = false;
let updateBusy = false;
let updateReloadOnClose = false;
let editorHistoryRequest = 0;
let noteState = null;
let noteBusy = false;
let undoState = {available: false, label: null, depth: 0};
let undoBusy = false;
let selectedId = null;
let docsData = [];
let notesLoaded = false;
let notesRequest = 0;
let docTimer;
let docPending = false; // the documents of the query are being searched
let docResults = [];
let docTotal = 0;
let docTruncated = false;
let docTerms = [];
let docTypes = {}; // the number of matching documents of each type, whatever the Type filter: what another type would find
let docError = '';
let docSearchRequest = 0;
let docSelectedId = null;
let docCurrent = null;
let docHistory = [];
let docMarks = [];
let docRenderRequest = 0;
let docEditing = false;
let docSaving = false;
let docNote = null;
const DOC_MARK_CAP = 500;
const docFoldCache = new Map();
const INBOX_REGISTER = 'inbox';
const DOC_TYPE_LABELS = {note: 'Note', source: 'Source', workstream: 'Workstream', journal: 'Journal', page: 'Project page'}; // the badge of each type of the Docs list
const detailCache = new Map();
function saveUIState() {
  try {
    sessionStorage.setItem(UI_STATE_KEY, JSON.stringify({
      view: view === 'search' ? searchReturn : view, project: projectScope, group: ids.groupFilter.value || pendingGroup,
      owner: ids.ownerFilter.value, boardOwner: ids.boardOwner.value, scope: ids.scopeFilter.value,
      docProject: ids.docProject.value, docType: ids.docType.value, foldedGroups: [...foldedGroups], brain: currentBrain, timelineRange, timelineDone, timelineTray: timelineTrayOpen, timelineFolded: [...timelineFolded]
    }));
  } catch { /* The interface remains usable when browser storage is unavailable. */ }
}

// ---------- Small helpers ----------
const SVG_NS = 'http://www.w3.org/2000/svg';
function element(tag, className = '', value = '') {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value) node.textContent = value;
  return node;
}
function svgIcon(markup, className = '') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('aria-hidden', 'true');
  if (className) svg.setAttribute('class', className);
  svg.innerHTML = markup;
  return svg;
}
function iconButton(className, label, icon, title = label) {
  const button = element('button', className);
  button.type = 'button';
  button.setAttribute('aria-label', label);
  button.title = title;
  button.append(svgIcon(icon));
  return button;
}
const ICONS = {
  open: '<path d="M9.5 3h3.5v3.5M13 3 8.5 7.5M7 4H4.5A1.5 1.5 0 0 0 3 5.5v6A1.5 1.5 0 0 0 4.5 13h6a1.5 1.5 0 0 0 1.5-1.5V9"/>',
  trash: '<path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.7 8.5h5.6l.7-8.5"/>',
  plus: '<path d="M8 3.5v9M3.5 8h9"/>',
  chevron: '<path d="M4.5 6.25 8 9.75l3.5-3.5"/>',
  calendar: '<rect x="2.75" y="3.5" width="10.5" height="9.5" rx="1.5"/><path d="M2.75 6.5h10.5M5.5 2.5v2M10.5 2.5v2"/>',
  check: '<path d="M3.5 8.5l3 3 6-6.5"/>',
  edit: '<path d="M3 13l.8-3.2L10.6 3a1.5 1.5 0 0 1 2.1 0l.3.3a1.5 1.5 0 0 1 0 2.1L6.2 12.2z"/><path d="M9.2 4.4l2.4 2.4"/>',
  up: '<path d="M8 12.5v-9M4.5 7 8 3.5 11.5 7"/>',
  archive: '<rect x="2.5" y="3" width="11" height="3" rx="1"/><path d="M3.5 6v6.5h9V6M6.5 8.75h3"/>',
  more: '<circle cx="3.5" cy="8" r="1.1"/><circle cx="8" cy="8" r="1.1"/><circle cx="12.5" cy="8" r="1.1"/>',
  down: '<path d="M8 3.5v9M4.5 9 8 12.5 11.5 9"/>',
  // Markdown toolbar
  bold: '<path stroke-width="1.9" d="M4.75 3h3.5a2.25 2.25 0 0 1 0 4.5h-3.5zM4.75 7.5h4a2.5 2.5 0 0 1 0 5h-4z"/>',
  italic: '<path d="M10 3H7M9 13H6M9.2 3 6.8 13"/>',
  underline: '<path d="M4.75 2.75v5a3.25 3.25 0 0 0 6.5 0v-5M3.5 13.5h9"/>',
  strike: '<path d="M2.5 8h11M10.8 5.3c-.2-1.3-1.3-2.1-2.8-2.1-1.6 0-2.7.9-2.7 2.1 0 1 .6 1.6 1.7 2M8.6 8.5c1.4.4 2.1 1.1 2.1 2.2 0 1.3-1.2 2.2-2.7 2.2-1.5 0-2.6-.8-2.8-2.1"/>',
  bullets: '<path d="M6.5 4.5h7M6.5 8h7M6.5 11.5h7"/><path stroke-width="2.4" d="M2.75 4.5h.01M2.75 8h.01M2.75 11.5h.01"/>',
  numbers: '<path d="M7.25 4h6.25M7.25 8.2h6.25M7.25 12.4h6.25M2.3 3.2l1.3-1v3.3M2.3 7.2c.3-.6.8-.9 1.4-.9.7 0 1.2.4 1.2 1 0 1.2-1.8 1.7-2.6 2.9h2.7M2.3 11.7c.2-.5.7-.8 1.3-.8.7 0 1.1.4 1.1.9s-.5.9-1.2.9c.8 0 1.3.4 1.3 1s-.6 1-1.3 1c-.7 0-1.2-.3-1.3-.8"/>',
  tasks: '<rect x="2.25" y="2.75" width="4" height="4" rx="1"/><path d="M3.3 4.8l.8.8 1.3-1.5M8 4.75h5.5M8 11.25h5.5"/><rect x="2.25" y="9.25" width="4" height="4" rx="1"/>',
  quote: '<path d="M3.5 7.5V4h2.7v3.5c0 1.7-.7 2.9-2.4 3.5M9.8 7.5V4h2.7v3.5c0 1.7-.7 2.9-2.4 3.5"/>',
  code: '<path d="M5.25 4.5 1.75 8l3.5 3.5M10.75 4.5 14.25 8l-3.5 3.5M9 3.25 7 12.75"/>',
  link: '<path d="M6.75 9.25a2.5 2.5 0 0 0 3.5 0l2.25-2.25a2.5 2.5 0 0 0-3.5-3.5l-.75.75M9.25 6.75a2.5 2.5 0 0 0-3.5 0L3.5 9a2.5 2.5 0 0 0 3.5 3.5l.75-.75"/>',
  arrow: '<path d="M2.5 8h11M9.5 4l4 4-4 4"/>',
  // Timeline
  late: '<circle cx="8" cy="8" r="5.75"/><path d="M8 4.9v3.6M8 10.9h.01"/>',
  hourglass: '<path d="M4.75 2.75h6.5M4.75 13.25h6.5M5.5 2.75v1.6c0 1.7 2.5 2.4 2.5 3.65s-2.5 1.95-2.5 3.65v1.6M10.5 2.75v1.6c0 1.7-2.5 2.4-2.5 3.65s2.5 1.95 2.5 3.65v1.6"/>',
  info: '<circle cx="8" cy="8" r="5.75"/><path d="M8 7.2v3.6M8 5.2h.01"/>',
  // Git: save and send
  gitSaved: '<circle cx="8" cy="8" r="5.75"/><path d="M5.4 8.3l1.9 1.9 3.5-3.9"/>',
  gitEdited: '<path d="M3 13l.8-3.2L10.6 3a1.5 1.5 0 0 1 2.1 0l.3.3a1.5 1.5 0 0 1 0 2.1L6.2 12.2z"/><path d="M9.2 4.4l2.4 2.4"/>',
  gitSend: '<path d="M8 10.5V3M4.9 5.9 8 2.8l3.1 3.1M3 10.5v1.8c0 .5.4.9.9.9h8.2c.5 0 .9-.4.9-.9v-1.8"/>',
  gitBehind: '<path d="M8 2.8v7.7M4.9 7.4 8 10.5l3.1-3.1M3 10.5v1.8c0 .5.4.9.9.9h8.2c.5 0 .9-.4.9-.9v-1.8"/>',
  gitOff: '<circle cx="8" cy="8" r="5.75"/><path d="M4 12 12 4"/>'
};
function plural(count, word, words = `${word}s`) { return `${count} ${count === 1 ? word : words}`; }
const TIME_FORMAT = new Intl.DateTimeFormat(LOCALE, {hour: '2-digit', minute: '2-digit'});
const DAY_FORMAT = new Intl.DateTimeFormat(LOCALE, {weekday: 'short', day: 'numeric', month: 'short'});
const DAY_YEAR_FORMAT = new Intl.DateTimeFormat(LOCALE, {day: 'numeric', month: 'short', year: 'numeric'});
const LONG_FORMAT = new Intl.DateTimeFormat(LOCALE, {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
function parseDay(iso) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day, 12);
}
function isoDay(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
function today() { return snapshot.today || isoDay(new Date()); }
function addDays(iso, count) {
  const date = parseDay(iso);
  date.setDate(date.getDate() + count);
  return isoDay(date);
}
function dayDiff(from, to) { return Math.round((parseDay(to) - parseDay(from)) / 86400000); }
function formatDay(iso) { return iso ? DAY_YEAR_FORMAT.format(parseDay(iso)) : ''; }
function formatStamp(value) {
  if (!value) return '';
  const [day, time] = value.split(' ');
  return time ? `${formatDay(day)} at ${time}` : formatDay(day);
}
// "today", "tomorrow", "yesterday", otherwise "Mon, Oct 27" ("Jan 12, 2027" in another year), in the browser's locale.
function relativeDay(iso) {
  const diff = dayDiff(today(), iso);
  if (diff === 0) return 'today';
  if (diff === 1) return 'tomorrow';
  if (diff === -1) return 'yesterday';
  return iso.slice(0, 4) === today().slice(0, 4) ? DAY_FORMAT.format(parseDay(iso)) : DAY_YEAR_FORMAT.format(parseDay(iso));
}
function closed(action) { return action.state === 'x' || action.state === '-'; }
// The mission part of "client / mission" (the whole label otherwise), for narrow places; the full label goes in the tooltip.
function shortProject(label) { return label.split(' / ').at(-1); }
// Clients by their display name ("ACME", "Globex Industries": the first heading of the client page, else the folder name capitalised),
// from the server (`clients` of the snapshot and of the archives). The server's labels (`acme / demo`, by folder names) are renamed
// once, as they arrive (`nameSnapshot`, the document lists): every view then shows the names. Requests address projects by path.
let clientNames = {};
function displayClient(folder) { return clientNames[folder] || folder; }
function displayProject(label) {
  if (typeof label !== 'string' || !label.includes(' / ')) return label;
  const [client, ...rest] = label.split(' / ');
  return clientNames[client] ? [clientNames[client], ...rest].join(' / ') : label;
}
function nameSnapshot(data) {
  clientNames = {...clientNames, ...(data.clients || {})};
  for (const action of data.actions || []) {
    action.project_key = action.project; // the label by folder names: still found by the search
    action.project = displayProject(action.project);
  }
  for (const register of data.registers || []) register.label = displayProject(register.label);
  return data;
}
function nameDocs(items) { return (items || []).map(item => ({...item, project: displayProject(item.project)})); }
function dueState(action) {
  if (!action.due) return '';
  if (closed(action)) return 'closed';
  return action.due < today() ? 'late' : action.due === today() ? 'today' : '';
}
function dueTitle(action) {
  const late = dueState(action) === 'late' ? dayDiff(action.due, today()) : 0;
  return `Due on ${LONG_FORMAT.format(parseDay(action.due))}${late ? `, ${plural(late, 'day')} overdue` : ''}`;
}
function dueNode(action) {
  const state = dueState(action);
  const node = element('span', `due${state ? ` due-${state}` : ''}`, relativeDay(action.due));
  node.title = dueTitle(action);
  return node;
}

// ---------- Status and priority ----------
const STATUS = {
  ' ': {label: 'To do', cls: 's-todo', icon: '<circle class="ring" cx="8" cy="8" r="5.75"/>'},
  '/': {label: 'In progress', cls: 's-doing', icon: '<circle class="ring" cx="8" cy="8" r="5.75"/><path class="fill" d="M8 4.25a3.75 3.75 0 0 1 0 7.5z"/>'},
  w: {label: 'Waiting', cls: 's-wait', icon: '<circle class="ring" cx="8" cy="8" r="5.75"/><path class="bar" d="M6.6 6.1v3.8M9.4 6.1v3.8"/>'},
  x: {label: 'Done', cls: 's-done', icon: '<circle class="fill" cx="8" cy="8" r="6.5"/><path class="knock" d="M5.3 8.2l1.8 1.8 3.6-3.8"/>'},
  '-': {label: 'Cancelled', cls: 's-cancel', icon: '<circle class="fill" cx="8" cy="8" r="6.5"/><path class="knock" d="M5.9 5.9l4.2 4.2M10.1 5.9l-4.2 4.2"/>'}
};
const STATUS_ORDER = [' ', '/', 'w', 'x', '-'];
function statusInfo(state) { return STATUS[state] || STATUS[' ']; }
function statusLabel(state) { return STATUS[state]?.label || state; }
function statusIcon(state) { return svgIcon(statusInfo(state).icon, `status-icon ${statusInfo(state).cls}`); }
const PRIORITY = {
  '⏫': {label: 'High', cls: 'prio-high', icon: '<path d="M4 8.5l4-4 4 4M4 12.5l4-4 4 4"/>'},
  '🔼': {label: 'Medium', cls: 'prio-medium', icon: '<path d="M4.5 10 8 6.5l3.5 3.5"/>'},
  '🔽': {label: 'Low', cls: 'prio-low', icon: '<path d="M4.5 6.5 8 10l3.5-3.5"/>'}
};
function priorityNode(action) {
  const info = PRIORITY[action.priority];
  const node = element('span', info ? `priority ${info.cls}` : 'priority');
  if (info) {
    node.setAttribute('role', 'img');
    node.setAttribute('aria-label', `${info.label} priority`);
    node.title = `${info.label} priority`;
    node.append(svgIcon(info.icon));
  }
  return node;
}
// The progress of an action's subtasks (`subtasks` of the snapshot: done, total, texts), only when it has some: a small `d/t`
// pill, in the done colours once every subtask is ticked. The pill is for the eye; `subtaskSummary` says it in words to the
// screen readers (in the name of the row's button, of the chip or of the tray row).
function subtaskSummary(action) {
  const progress = action.subtasks;
  return progress?.total ? `${progress.done} of ${plural(progress.total, 'subtask')} done` : '';
}
function subtaskPill(action) {
  const progress = action.subtasks;
  if (!progress?.total) return null;
  const pill = element('span', `subtask-pill${progress.done === progress.total ? ' is-complete' : ''}`, `${progress.done}/${progress.total}`);
  pill.setAttribute('aria-hidden', 'true');
  pill.title = `Subtasks: ${subtaskSummary(action)}`;
  return pill;
}

// ---------- Groups ----------
function groupLabel(slug) {
  const text = slug.replace(/-/g, ' ');
  return text.charAt(0).toLocaleUpperCase(LOCALE) + text.slice(1);
}
// A free label ("Ingestion workshop") becomes a slug the way the server expects it: a-z, 0-9 and single hyphens, 40 characters.
function groupSlug(text) {
  return text.toLowerCase().replace(/œ/g, 'oe').replace(/æ/g, 'ae').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+/, '').slice(0, 40).replace(/-+$/, '');
}
// A stable tone per group: its slug picks one of the 8 palette colours (--grp-0…7), the same everywhere.
function groupTone(slug) {
  let hash = 0;
  for (const char of slug) hash = (Math.imul(hash, 72) + char.charCodeAt(0)) >>> 0;
  return `grp-${((hash ^ (hash >>> 13)) >>> 0) % 8}`;
}
const NO_GROUP = '|';
function groupKey(action) { return `${action.register}|${action.group}`; }
function compareGroups(a, b) {
  return a.project.localeCompare(b.project, LOCALE) || a.label.localeCompare(b.label, LOCALE) || a.key.localeCompare(b.key);
}
