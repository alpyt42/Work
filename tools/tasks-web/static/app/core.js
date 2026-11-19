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
// Filled icons are Material Symbols (Apache License 2.0, static/licenses/), drawn on their own 960-unit grid; the stroked ones on a
// 16-unit grid. `ms` wraps the path of a filled one.
function ms(d) { return `<path class="ms" d="${d}"/>`; }
function svgIcon(markup, className = '') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', markup.startsWith('<path class="ms"') ? '0 -960 960 960' : '0 0 16 16');
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
  open: ms('M180-120q-24 0-42-18t-18-42v-600q0-24 18-42t42-18h279v60H180v600h600v-279h60v279q0 24-18 42t-42 18H180Zm202-219-42-43 398-398H519v-60h321v321h-60v-218L382-339Z'),
  trash: ms('M261-120q-24 0-42-18t-18-42v-570h-41v-60h188v-30h264v30h188v60h-41v570q0 24-18 42t-42 18H261Zm106-146h60v-399h-60v399Zm166 0h60v-399h-60v399Z'),
  plus: ms('M450-450H200v-60h250v-250h60v250h250v60H510v250h-60v-250Z'),
  chevron: '<path d="M4.5 6.25 8 9.75l3.5-3.5"/>',
  calendar: ms('M180-80q-24 0-42-18t-18-42v-620q0-24 18-42t42-18h65v-60h65v60h340v-60h65v60h65q24 0 42 18t18 42v620q0 24-18 42t-42 18H180Zm0-60h600v-430H180v430Z'),
  check: '<path d="M3.5 8.5l3 3 6-6.5"/>',
  edit: ms('M120-120v-128l575-574q8-8 19-12.5t23-4.5q11 0 22 4.5t20 12.5l44 44q9 9 13 20t4 22q0 11-4.5 22.5T823-694L248-120H120Zm619-577 40-40-41-41-40 40 41 41Z'),
  up: '<path d="M8 12.5v-9M4.5 7 8 3.5 11.5 7"/>',
  archive: ms('M180-80q-24.75 0-42.37-17.63Q120-115.25 120-140v-483q-17-6-28.5-21.39T80-680v-140q0-24.75 17.63-42.38Q115.25-880 140-880h680q24.75 0 42.38 17.62Q880-844.75 880-820v140q0 20.22-11.5 35.61T840-623v483q0 24.75-17.62 42.37Q804.75-80 780-80H180Zm-40-600h680v-140H140v140Zm220 260h240v-60H360v60Z'),
  more: ms('M207.86-432Q188-432 174-446.14t-14-34Q160-500 174.14-514t34-14Q228-528 242-513.86t14 34Q256-460 241.86-446t-34 14Zm272 0Q460-432 446-446.14t-14-34Q432-500 446.14-514t34-14Q500-528 514-513.86t14 34Q528-460 513.86-446t-34 14Zm272 0Q732-432 718-446.14t-14-34Q704-500 718.14-514t34-14Q772-528 786-513.86t14 34Q800-460 785.86-446t-34 14Z'),
  down: '<path d="M8 3.5v9M4.5 9 8 12.5 11.5 9"/>',
  // Markdown toolbar
  bold: ms('M275-200v-560h228q66 0 114.5 42T666-612q0 38-21 70t-56 49v6q43 14 69.5 50t26.5 81q0 68-52.5 112T510-200H275Zm86-76h144q38 0 66-25t28-63q0-37-28-62t-66-25H361v175Zm0-247h136q35 0 60.5-23t25.5-58q0-35-25.5-58.5T497-686H361v163Z'),
  italic: ms('M224-199v-80h134l139-409H338v-80h380v80H584L445-279h159v80H224Z'),
  underline: ms('M200-140v-60h560v60H200Zm123.5-198.5Q267-397 267-497v-343h83v343q0 63 34 101t96 38q62 0 96-38t34-101v-343h83v343q0 100-56.5 158.5T480-280q-100 0-156.5-58.5Z'),
  strike: ms('M80-410v-60h800v60H80Zm350-120v-170H200v-100h560v100H530v170H430Zm0 370v-190h100v190H430Z'),
  bullets: ms('M377-198v-60h463v60H377Zm0-252v-60h463v60H377Zm0-253v-60h463v60H377ZM189-161q-28.05 0-48.02-19Q121-199 121-227.5t19.5-48q19.5-19.5 48-19.5t47.5 19.98q19 19.97 19 48.02 0 27.23-19.39 46.61Q216.23-161 189-161Zm0-252q-28.05 0-48.02-19.5Q121-452 121-480t19.98-47.5Q160.95-547 189-547q27.23 0 46.61 19.5Q255-508 255-480t-19.39 47.5Q216.23-413 189-413Zm-48.5-272.5Q121-705 121-733t19.5-47.5Q160-800 188-800t47.5 19.5Q255-761 255-733t-19.5 47.5Q216-666 188-666t-47.5-19.5Z'),
  numbers: ms('M120-80v-60h100v-30h-60v-60h60v-30H120v-60h120q17 0 28.5 11.5T280-280v40q0 17-11.5 28.5T240-200q17 0 28.5 11.5T280-160v40q0 17-11.5 28.5T240-80H120Zm0-280v-110q0-17 11.5-28.5T160-510h60v-30H120v-60h120q17 0 28.5 11.5T280-560v70q0 17-11.5 28.5T240-450h-60v30h100v60H120Zm60-280v-180h-60v-60h120v240h-60Zm189 431v-60h471v60H369Zm0-243v-60h471v60H369Zm0-243v-60h471v60H369Z'),
  tasks: ms('M222-214 80-356l42-42 100 99 179-179 42 43-221 221Zm0-320L80-676l42-42 100 99 179-179 42 43-221 221Zm298 244v-60h360v60H520Zm0-320v-60h360v60H520Z'),
  quote: ms('m248-240 94-162q-5 1-11 1.5t-11 .5q-66 0-113-47t-47-113q0-66 47-113t113-47q66 0 113 47t47 113q0 21-5.5 41T458-480L320-240h-72Zm360 0 94-162q-5 1-11 1.5t-11 .5q-66 0-113-47t-47-113q0-66 47-113t113-47q66 0 113 47t47 113q0 21-5.5 41T818-480L680-240h-72Z'),
  code: ms('M320-242 80-482l242-242 43 43-199 199 197 197-43 43Zm318 2-43-43 199-199-197-197 43-43 240 240-242 242Z'),
  link: ms('M450-280H280q-83 0-141.5-58.5T80-480q0-83 58.5-141.5T280-680h170v60H280q-58.33 0-99.17 40.76-40.83 40.77-40.83 99Q140-422 180.83-381q40.84 41 99.17 41h170v60ZM325-450v-60h310v60H325Zm185 170v-60h170q58.33 0 99.17-40.76 40.83-40.77 40.83-99Q820-538 779.17-579q-40.84-41-99.17-41H510v-60h170q83 0 141.5 58.5T880-480q0 83-58.5 141.5T680-280H510Z'),
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
