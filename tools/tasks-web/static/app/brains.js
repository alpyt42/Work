'use strict';

// ---------- Brains ----------
const BRAIN_STORAGE_KEY = 'actions-brain-current-v1';
// Routes that do not depend on the selected brain: their answers are never dropped when the brain changes.
const BRAIN_NEUTRAL = new Set(['/api/brains', '/api/tools', '/api/settings', '/api/shutdown']);
let brains = [];
let currentBrain = '';
let brainEpoch = 0;
let brainMenuIndex = -1;
let pendingWrites = 0;
function brainUrl(url, brain = currentBrain) {
  if (!brain || !url.startsWith('/api/')) return url;
  return `${url}${url.includes('?') ? '&' : '?'}brain=${encodeURIComponent(brain)}`;
}
// A read that answers after a brain change belongs to the previous brain: it is dropped (error.stale) instead of overwriting the new views.
// Writes are never dropped: the brain switch waits for them (switchBrain).
// `brain` names another brain than the current one (the Git cards act on the brain they are about).
async function request(url, options = {}, brain = currentBrain) {
  const epoch = brainEpoch;
  const write = (options.method || 'GET').toUpperCase() !== 'GET';
  if (write) pendingWrites += 1;
  try {
    const response = await fetch(brainUrl(url, brain), options);
    if (!write && epoch !== brainEpoch && !BRAIN_NEUTRAL.has(url.split('?')[0])) {
      const stale = new Error('Response from another brain ignored.');
      stale.stale = true;
      throw stale;
    }
    let payload;
    try { payload = await response.json(); } catch { throw new Error('Unreadable local response.'); }
    if (!response.ok) {
      const error = new Error(payload.error || 'Operation failed.');
      error.status = response.status;
      error.data = payload; // the rest of the answer (the pages that link to a note that cannot be deleted)
      throw error;
    }
    return payload;
  } finally {
    if (write) pendingWrites -= 1;
  }
}
function readStoredBrain() {
  try { return localStorage.getItem(BRAIN_STORAGE_KEY) || ''; } catch { return ''; }
}
function storeBrain(name) {
  try { localStorage.setItem(BRAIN_STORAGE_KEY, name); } catch { /* The choice is simply not remembered. */ }
}
function brainFromUrl() {
  try { return new URL(location.href).searchParams.get('brain') || ''; } catch { return ''; }
}
function syncBrainUrl() {
  try {
    const url = new URL(location.href);
    url.searchParams.set('brain', currentBrain);
    history.replaceState(history.state, '', url.href);
  } catch { /* The address bar keeps its value. */ }
}
// One accent per brain, stable: steel for the default brain (or `brain` before the list is loaded), plum for
// `brain-perso`, then a hash over four more.
const EXTRA_ACCENTS = ['teal', 'olive', 'rust', 'slate'];
function accentFor(name) {
  const listed = brains.find(brain => brain.name === name);
  if (!name || listed?.default || (!listed && name === 'brain')) return 'steel';
  if (name === 'brain-perso') return 'plum';
  let hash = 0;
  for (const char of name) hash = (Math.imul(hash, 31) + char.charCodeAt(0)) >>> 0;
  return EXTRA_ACCENTS[hash % EXTRA_ACCENTS.length];
}
function applyAccent(name) { document.documentElement.dataset.accent = accentFor(name); }
// What the page shows for a brain: the short label of the server (`Perso` for `brain-perso`); the folder name stays the technical value.
function brainLabel(name) {
  return brains.find(brain => brain.name === name)?.label || name;
}
// Tooltip of a brain: its folder name and scope, then its description. The scope is not displayed otherwise.
function brainTitle(brain) {
  return [brain.scope ? `${brain.name} (${brain.scope})` : brain.name, brain.description].filter(Boolean).join(': ');
}
function brainOption(brain, index) {
  const option = element('li', 'brain-option');
  option.id = `brainOption${index}`;
  option.setAttribute('role', 'option');
  option.setAttribute('aria-selected', String(brain.name === currentBrain));
  option.dataset.brain = brain.name;
  const swatch = element('span', 'brain-swatch');
  swatch.dataset.accent = accentFor(brain.name);
  const text = element('span', 'brain-option-text');
  text.append(element('span', 'brain-option-name', brain.label || brain.name));
  option.append(swatch, text, svgIcon(ICONS.check, 'brain-check'));
  option.title = brainTitle(brain);
  option.addEventListener('click', () => chooseBrain(brain.name));
  return option;
}
// The switcher: the brain's name as plain text when the Work has one brain, otherwise a button that opens the list.
function renderBrainSwitch() {
  const several = brains.length > 1;
  const known = brains.find(brain => brain.name === currentBrain);
  const active = ids.brainMenu.children[brainMenuIndex]?.dataset.brain || currentBrain;
  ids.brainStatic.hidden = several;
  ids.brainStaticName.textContent = brainLabel(currentBrain) || 'Brain';
  ids.brainStatic.title = known ? brainTitle(known) : '';
  ids.brainButton.hidden = !several;
  ids.brainName.textContent = brainLabel(currentBrain);
  ids.brainMini.textContent = brainLabel(currentBrain) || 'Brain';
  ids.brainButton.title = known ? brainTitle(known) : '';
  ids.brainMenu.replaceChildren(...brains.map(brainOption));
  if (!several) closeBrainMenu(false);
  else if (brainMenuOpen()) setBrainActive(Math.max(0, brains.findIndex(brain => brain.name === active)));
  document.title = several && currentBrain ? `Actions – ${brainLabel(currentBrain)}` : 'Actions';
}
function brainMenuOpen() { return !ids.brainMenu.hidden; }
function setBrainActive(index) {
  const options = [...ids.brainMenu.children];
  if (!options.length) return;
  brainMenuIndex = Math.max(0, Math.min(index, options.length - 1));
  options.forEach((option, position) => option.classList.toggle('is-active', position === brainMenuIndex));
  ids.brainMenu.setAttribute('aria-activedescendant', options[brainMenuIndex].id);
  options[brainMenuIndex].scrollIntoView({block: 'nearest'});
}
function openBrainMenu() {
  if (brains.length < 2 || brainMenuOpen()) return;
  closePopover(false);
  ids.brainMenu.hidden = false;
  ids.brainButton.setAttribute('aria-expanded', 'true');
  setBrainActive(brains.findIndex(brain => brain.name === currentBrain));
  ids.brainMenu.focus();
  loadBrains(); // A brain added since the page was opened shows up.
}
function closeBrainMenu(refocus = true) {
  if (!brainMenuOpen()) return;
  ids.brainMenu.hidden = true;
  ids.brainButton.setAttribute('aria-expanded', 'false');
  ids.brainMenu.removeAttribute('aria-activedescendant');
  brainMenuIndex = -1;
  if (refocus) ids.brainButton.focus();
}
function chooseBrain(name) {
  closeBrainMenu();
  if (!name || name === currentBrain) return;
  const from = brains.findIndex(brain => brain.name === currentBrain);
  turnToBrain(name, brains.findIndex(brain => brain.name === name) >= from ? 1 : -1);
}
function adoptBrain(name) {
  currentBrain = name;
  brainEpoch += 1;
  storeBrain(name);
  syncBrainUrl();
  applyAccent(name);
  renderBrainSwitch();
}
// What a brain owns: project filter, group folds, selection, panel, open documents and Git detail, tool output, undo.
// The text typed in the search boxes and the owner (Everyone or Me) and status filters are not tied to a brain: they stay.
// A person chosen as owner is: the choice goes.
function resetBrainState() {
  projectScope = '';
  pendingGroup = '';
  ids.groupFilter.value = '';
  dropPersonFilters();
  clientNames = {};
  archivesData = null;
  archivesRequest += 1;
  archiveError = '';
  archiveSearch = null;
  archiveAsk = null;
  if (ids.archiveDialog.open) ids.archiveDialog.close();
  closeArchive();
  ids.docProject.value = '';
  ids.editorProject.replaceChildren();
  foldedGroups.clear();
  timelineFolded.clear();
  snapshot = {actions: [], registers: [], owner: '', today: ''};
  detailCache.clear();
  selectedId = null;
  timelineAnchor = true;
  timelineModel = null;
  timelineSpot = '';
  timelineBase = [];
  ids.timelineTraySearch.value = '';
  resetPriorities();
  closePopover(false);
  closeEditor({force: true, refocus: false});
  // The Git cards are the same for every brain (only their order follows the current one): kept, drawn again by the render below.
  gitLoadId += 1;
  gitLoading = null;
  closeGitDialogs();
  clearTimeout(docTimer);
  notesRequest += 1;
  docSearchRequest += 1;
  docRenderRequest += 1;
  docsData = [];
  notesLoaded = false;
  docPending = false;
  docResults = [];
  docTotal = 0;
  docTruncated = false;
  docTerms = [];
  docError = '';
  docSelectedId = null;
  docCurrent = null;
  docHistory = [];
  docMarks = [];
  docEditing = false;
  docNote = null;
  ids.docPaneEmpty.textContent = 'Choose a document to read it.';
  ids.docList.replaceChildren();
  ids.docArticle.replaceChildren();
  ids.docEditor.value = '';
  setDocError('');
  setDocStatus('');
  renderDocPane();
  ids.toolResultTitle.textContent = 'Result';
  ids.toolResultCommand.hidden = true;
  ids.toolResultStatus.textContent = 'Ready';
  ids.toolResultStatus.className = '';
  ids.toolResultEmpty.hidden = false;
  ids.toolResultOutput.hidden = true;
  ids.toolResultOutput.textContent = '';
  setUndo(null);
  ids.errorBanner.hidden = true;
  ids.lastSync.textContent = 'Loading…';
  ids.todayCount.textContent = '';
  ids.openCount.textContent = '';
  populateProjects();
  renderProjectNav();
  render();
  saveUIState();
}
function enterBrain(name) {
  adoptBrain(name);
  resetBrainState();
  refresh();
}
// A change waits for the writes in flight and keeps an action or a note being edited unless the user lets it go.
function switchBrain(name) {
  if (name === currentBrain) return false;
  if (pendingWrites > 0) {
    showToast('An operation is in progress: wait for it to finish before switching brain.');
    return false;
  }
  if (editorDirty() && !confirm('Discard the unsaved changes to this action?')) return false;
  if (docDirty() && !confirm('Discard the unsaved changes to this note?')) return false;
  enterBrain(name);
  showToast(`Brain ${brainLabel(name)} opened`);
  return true;
}
// Reads the brains of the Work (rediscovered by the server each time). Startup: the brain comes from the URL, then the browser's memory,
// then the server's default. Later: a brain that disappeared sends the page back to the default one. Returns true when it reloaded the views.
async function loadBrains({initial = false} = {}) {
  let data;
  try { data = await request('/api/brains'); } catch { return false; }
  if (!Array.isArray(data.brains)) return false;
  const previousLabel = brainLabel(currentBrain);
  brains = data.brains;
  const names = brains.map(brain => brain.name);
  const fallback = names.includes(data.default) ? data.default : names[0];
  if (initial) {
    const choice = [brainFromUrl(), readStoredBrain()].find(name => names.includes(name)) || fallback;
    if (choice) adoptBrain(choice);
    // Filters kept by this tab belong to the brain they were saved with.
    if (savedUI.brain && savedUI.brain !== currentBrain) {
      projectScope = '';
      pendingGroup = '';
      dropPersonFilters();
      ids.docProject.value = '';
      foldedGroups.clear();
      timelineFolded.clear();
    }
  } else if (fallback && !names.includes(currentBrain)) {
    if (currentBrain) showToast(`Brain ${previousLabel} no longer exists: back to ${brainLabel(fallback)}.`);
    enterBrain(fallback);
    return true;
  }
  renderBrainSwitch();
  return false;
}

// ---------- Turning to another brain ----------
// A change of brain turns the workspace like a cube: the brain's name and its sidebar (views, projects) swing away on their edge
// toward the side the change goes to, then the next brain's swing in from the other side while the views slide in after them. A
// swipe leans the sidebar with the fingers first, and a swipe given up swings it back. The switch itself is `switchBrain`, so a
// write in progress or an unsaved edit still holds it back (the sidebar then swings back). Without motion (the system setting),
// the brain just changes.
const TURN_OUT = {duration: 170, easing: 'cubic-bezier(.4, 0, 1, 1)'};
const TURN_IN = {duration: 300, easing: 'cubic-bezier(.2, .8, .2, 1)'};
const TURN_REST = {transform: 'perspective(900px) translateX(0) rotateY(0deg)', transformOrigin: '50% 50%', opacity: 1};
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
let turning = false;
let turnLean = null;  // how far a swipe in progress leaned the sidebar: {direction, amount}
function turnParts() { return [ids.brainSwitch, ids.sidebar.querySelector('.sidebar-scroll')]; }
// The sidebar `amount` of the way out (0 to 1) toward the next brain (direction 1: it leaves to the left) or the previous one.
function turnOut(direction, amount) {
  return {transform: `perspective(900px) translateX(${-direction * amount * 55}%) rotateY(${direction * amount * 70}deg)`,
          transformOrigin: direction > 0 ? '0% 50%' : '100% 50%', opacity: 1 - amount * .85};
}
// The next brain's sidebar, `amount` of the way before it is in place, coming from the other side.
function turnIn(direction, amount) {
  return {transform: `perspective(900px) translateX(${direction * amount * 55}%) rotateY(${-direction * amount * 70}deg)`,
          transformOrigin: direction > 0 ? '100% 50%' : '0% 50%', opacity: 1 - amount};
}
function setTurnPose(pose) {
  for (const part of turnParts()) {
    part.style.transform = pose ? pose.transform : '';
    part.style.transformOrigin = pose ? pose.transformOrigin : '';
    part.style.opacity = pose ? String(pose.opacity) : '';
  }
}
// Each step ends with its animations, or after a grace delay when they cannot run (a page in the background does not animate):
// the turn never stays stuck halfway.
async function playTurn(from, to, timing) {
  const animations = turnParts().map(part => part.animate([from, to], {...timing, fill: 'forwards'}));
  const ended = Promise.all(animations.map(animation => animation.finished.catch(() => null)));
  await Promise.race([ended, new Promise(resolve => setTimeout(resolve, timing.duration + 250))]);
  return animations;
}
function leanTurn(direction, amount) {
  if (turning || reducedMotion.matches) return;
  ids.sidebar.classList.add('is-turning');
  turnLean = {direction, amount: Math.min(amount, 1) * .45};
  setTurnPose(turnOut(direction, turnLean.amount));
}
async function turnBack() {
  if (!turnLean || turning) return;
  const from = turnOut(turnLean.direction, turnLean.amount);
  turnLean = null;
  turning = true;
  setTurnPose(null);
  (await playTurn(from, TURN_REST, TURN_IN)).forEach(animation => animation.cancel());
  ids.sidebar.classList.remove('is-turning');
  turning = false;
}
async function turnToBrain(name, direction) {
  if (turning) return false;
  if (reducedMotion.matches) {
    turnLean = null;
    setTurnPose(null);
    return switchBrain(name);
  }
  turning = true;
  ids.sidebar.classList.add('is-turning');
  document.documentElement.classList.add('brain-turning');
  const from = turnLean ? turnOut(turnLean.direction, turnLean.amount) : TURN_REST;
  turnLean = null;
  setTurnPose(null);
  const out = await playTurn(from, turnOut(direction, 1), TURN_OUT);
  const switched = switchBrain(name);
  out.forEach(animation => animation.cancel());  // in the same task as the next animations: no frame shows the sidebar at rest
  let back;
  if (switched) {
    ids.mainContent.querySelector('.views')?.animate([{transform: `translateX(${direction * 32}px)`, opacity: 0}, {transform: 'none', opacity: 1}], TURN_IN);
    back = await playTurn(turnIn(direction, 1), TURN_REST, TURN_IN);
  } else back = await playTurn(turnOut(direction, 1), TURN_REST, TURN_IN);
  back.forEach(animation => animation.cancel());
  ids.sidebar.classList.remove('is-turning');
  document.documentElement.classList.remove('brain-turning');
  turning = false;
  return switched;
}

// ---------- Swipe between brains ----------
// A sideways scroll moves to the previous or the next brain, in the order of the selector (the logic is BrainSwipe, in
// brain-swipe.js): it leans the sidebar, a cue slides in from the side it leads to with that brain's name and colour, and far
// enough it turns the workspace to that brain.
let brainSwipe = BrainSwipe.idle();
let brainSwipeTimer = 0;
function brainNeighbour(direction) {
  const index = brains.findIndex(brain => brain.name === currentBrain);
  return index < 0 ? null : brains[index + direction] || null;
}
// Whether something under the pointer can still scroll sideways that way (-1 left, 1 right): then the swipe scrolls it instead.
// Nothing in the sidebar scrolls sideways: over it a swipe always turns the brain.
function scrollsSideways(target, direction) {
  if (target instanceof Element && target.closest('.sidebar')) return false;
  for (let node = target instanceof Element ? target : null; node && node !== document.body; node = node.parentElement) {
    if (node.scrollWidth <= node.clientWidth + 1) continue;
    const overflow = getComputedStyle(node).overflowX;
    if (overflow !== 'auto' && overflow !== 'scroll') continue;
    if (direction < 0 ? node.scrollLeft > 0 : node.scrollLeft + node.clientWidth < node.scrollWidth - 1) return true;
  }
  return false;
}
function showBrainSwipe(direction, amount) {
  const brain = brainNeighbour(direction);
  const cue = ids.brainSwipe;
  cue.hidden = false;
  cue.dataset.side = direction > 0 ? 'right' : 'left';
  cue.style.left = direction > 0 ? '' : `${Math.round(ids.mainContent.getBoundingClientRect().left) + 16}px`;
  cue.classList.toggle('is-end', !brain);
  if (brain) cue.dataset.accent = accentFor(brain.name);
  else delete cue.dataset.accent;
  ids.brainSwipeName.textContent = brain ? brainLabel(brain.name) : 'No other brain';
  cue.style.setProperty('--swipe', String(Math.min(amount, 1)));
}
function hideBrainSwipe() { ids.brainSwipe.hidden = true; }
function onBrainWheel(event) {
  const deciding = brainSwipe.phase !== 'tracking';  // a new gesture may start (after a pause, or inside a momentum)
  const scale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? innerWidth : 1;  // lines or pages from some mice
  const result = BrainSwipe.step(brainSwipe, {
    dx: event.deltaX * scale, dy: event.deltaY * scale, time: event.timeStamp,
    // A pinch (ctrl), another modifier, a text field, a dialog or the open selector: never a swipe (Shift is how a mouse scrolls
    // sideways, so it counts). One brain: nowhere to go.
    ignore: brains.length < 2 || event.ctrlKey || event.altKey || event.metaKey || isTyping(event.target)
      || Boolean(document.querySelector('dialog[open]')) || brainMenuOpen(),
    scrollsLeft: deciding && scrollsSideways(event.target, -1), scrollsRight: deciding && scrollsSideways(event.target, 1),
  });
  brainSwipe = result.state;
  if (result.prevent) event.preventDefault();
  clearTimeout(brainSwipeTimer);
  brainSwipeTimer = setTimeout(() => {
    const end = BrainSwipe.settle(brainSwipe);
    brainSwipe = end.state;
    hideBrainSwipe();
    if (end.action?.type === 'cancel') turnBack();
  }, BrainSwipe.GAP);
  const action = result.action;
  if (action?.type === 'progress' && !turning) {
    showBrainSwipe(action.direction, action.amount);
    leanTurn(action.direction, action.amount);
  }
  if (action?.type === 'switch') {
    hideBrainSwipe();
    const brain = brainNeighbour(action.direction);
    if (brain) turnToBrain(brain.name, action.direction);
    else turnBack();  // past the last brain: the sidebar swings back
  }
}
// Not passive: a swipe that switches brain must also keep the browser from going back or forward in its history.
document.addEventListener('wheel', onBrainWheel, {passive: false});
