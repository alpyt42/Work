'use strict';

// The page's script is the files of static/app/, loaded in order by index.html: they share one global scope, and code
// that runs while a file loads may only call functions of that file or of an earlier one (REFERENCE.md, "Code layout").

const token = document.querySelector('meta[name="csrf-token"]').content;
const ids = Object.fromEntries([
  'app', 'sidebar', 'scrim', 'sidebarToggle', 'brainMini', 'sidebarClose', 'mainContent', 'brainSwipe', 'brainSwipeName',
  'brainSwitch', 'brainButton', 'brainName', 'brainMenu', 'railTip',
  'addBrainDialog', 'addBrainForm', 'closeAddBrain', 'addBrainName', 'addBrainDescription', 'addBrainScope', 'addBrainError', 'cancelAddBrain', 'saveAddBrain',
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
  'newNoteError', 'cancelNewNote', 'saveNewNote', 'deleteNoteDialog', 'deleteNoteHeading', 'deleteNoteText', 'deleteNoteLinks', 'deleteNoteError', 'deleteNoteCancel', 'deleteNoteConfirm', 'updateButton', 'updateButtonLabel', 'updateDialog', 'updateHeading', 'updateText', 'updateNotes', 'updateList', 'updateWhat', 'updateProgress', 'updateBar', 'updateBarFill', 'updateStep', 'updateElapsed', 'updateError', 'updateCancel', 'updateRecheck', 'updateConfirm', 'quitDialog', 'quitConfirm', 'shortcutsDialog', 'toast', 'toastText', 'toastAction'
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
// Icons are Lucide (ISC License, static/licenses/), inlined on their own 24-unit grid; one CSS rule (`.lucide`) gives them their stroke.
// The status and priority icons are drawn on a 16-unit grid of their own, hence `svgIcon`'s viewBox.
function svgIcon(markup, className = '', viewBox = '0 0 24 24') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', viewBox);
  svg.setAttribute('aria-hidden', 'true');
  const classes = (viewBox === '0 0 24 24' ? `lucide ${className}` : className).trim();
  if (classes) svg.setAttribute('class', classes);
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
  open: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  calendar: '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  edit: '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
  up: '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
  archive: '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  down: '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
  // Markdown toolbar
  bold: '<path d="M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8"/>',
  italic: '<line x1="19" x2="10" y1="4" y2="4"/><line x1="14" x2="5" y1="20" y2="20"/><line x1="15" x2="9" y1="4" y2="20"/>',
  underline: '<path d="M6 4v6a6 6 0 0 0 12 0V4"/><line x1="4" x2="20" y1="20" y2="20"/>',
  strike: '<path d="M16 4H9a3 3 0 0 0-2.83 4"/><path d="M14 12a4 4 0 0 1 0 8H6"/><line x1="4" x2="20" y1="12" y2="12"/>',
  bullets: '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M8 6h13"/>',
  numbers: '<path d="M10 12h11"/><path d="M10 18h11"/><path d="M10 6h11"/><path d="M4 10h2"/><path d="M4 6h1v4"/><path d="M6 18H4c0-1 2-2 2-3s-1-1.5-2-1"/>',
  tasks: '<rect x="3" y="5" width="6" height="6" rx="1"/><path d="m3 17 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
  quote: '<path d="M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/><path d="M5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  arrow: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  // Timeline
  late: '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
  hourglass: '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  // Git: save and send
  gitSaved: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  gitEdited: '<path d="M12 20h9"/><path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z"/><path d="m15 5 3 3"/>',
  gitSend: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  gitBehind: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  gitOff: '<path d="m2 2 20 20"/><path d="M8.35 2.69A10 10 0 0 1 21.3 15.65"/><path d="M19.08 19.08A10 10 0 1 1 4.92 4.92"/>'
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
function statusIcon(state) { return svgIcon(statusInfo(state).icon, `status-icon ${statusInfo(state).cls}`, '0 0 16 16'); }
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
    node.append(svgIcon(info.icon, '', '0 0 16 16'));
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
