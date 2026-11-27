'use strict';

// ---------- Filters ----------
function inScope(register, scope = projectScope) {
  return !scope || register === scope || (scope.endsWith('/') && typeof register === 'string' && register.startsWith(scope));
}
function isMine(action) {
  const me = snapshot.owner.toLocaleLowerCase(LOCALE);
  return action.owner.toLocaleLowerCase(LOCALE).includes(me);
}
// What the global search reads of an action: ID, title, owner, project, group and the texts of its subtasks.
function actionSearchText(action) {
  return `${action.id} ${action.title} ${action.owner} ${action.project} ${action.project_key || ""} ${action.group ? `${groupLabel(action.group)} ${action.group}` : ''} ${(action.subtasks?.texts || []).join(' ')}`;
}
// The owner filter: '' (everyone), 'mine', or a person, `o:<owner as written in the registers>`. The Board keeps its own
// choice, which starts on 'mine' (a board of everyone's to-dos hides one's own); the other views start on everyone.
const OWNER_MINE = 'mine';
const OWNER_PREFIX = 'o:';
function isPerson(choice) { return choice.startsWith(OWNER_PREFIX) && choice.length > OWNER_PREFIX.length; }
function ownerSelect() { return view === 'board' ? ids.boardOwner : ids.ownerFilter; }
function ownerMatches(action, choice) {
  return !choice || (choice === OWNER_MINE ? isMine(action) : action.owner === choice.slice(OWNER_PREFIX.length));
}
// The owners as written, the ones with the most open actions first (then the most actions, then by name).
function ownerCounts(actions) {
  const counts = new Map();
  for (const action of actions) {
    if (!counts.has(action.owner)) counts.set(action.owner, {owner: action.owner, open: 0, total: 0});
    const entry = counts.get(action.owner);
    entry.total += 1;
    if (!closed(action)) entry.open += 1;
  }
  return [...counts.values()].sort((a, b) => b.open - a.open || b.total - a.total || a.owner.localeCompare(b.owner, LOCALE));
}
function ownerOption(owner, open) {
  const option = new Option(open ? `${owner} (${open})` : owner, OWNER_PREFIX + owner);
  option.dataset.name = owner; // what the chip shows: the name without the count
  return option;
}
// A saved choice comes back before the actions are read: a person gets an option right away, counted by the next populateOwnerFilters.
function restoreOwner(select, saved, fallback) {
  const choice = typeof saved === 'string' && (saved === '' || saved === OWNER_MINE || isPerson(saved)) ? saved : fallback;
  if (isPerson(choice)) select.append(ownerOption(choice.slice(OWNER_PREFIX.length), 0));
  select.value = choice;
}
// Both owner filters: Everyone, Me, then the people with their number of open actions. A chosen person stays offered when no
// action carries the name any more (reassigned or deleted meanwhile): the empty view says so and offers to clear the filters.
function populateOwnerFilters() {
  const people = ownerCounts(snapshot.actions);
  for (const select of [ids.ownerFilter, ids.boardOwner]) {
    const chosen = select.value;
    const options = people.map(entry => ownerOption(entry.owner, entry.open));
    if (isPerson(chosen) && !options.some(option => option.value === chosen)) options.push(ownerOption(chosen.slice(OWNER_PREFIX.length), 0));
    const section = document.createElement('optgroup');
    section.label = 'People';
    section.append(...options);
    select.replaceChildren(new Option('Everyone', ''), new Option('Me', OWNER_MINE), ...(options.length ? [section] : []));
    select.value = chosen;
  }
}
// The Board's switch (one's own cards, or everyone's) is a preference of the browser, kept beyond the tab like the sidebar's;
// a person chosen there is a filter of the tab, kept with the other filters.
const BOARD_EVERYONE_KEY = 'actions-brain-board-everyone-v1';
function readBoardEveryone() {
  try { return localStorage.getItem(BOARD_EVERYONE_KEY) === 'yes'; } catch { return false; }
}
function storeBoardEveryone() {
  if (isPerson(ids.boardOwner.value)) return;
  try { localStorage.setItem(BOARD_EVERYONE_KEY, ids.boardOwner.value === '' ? 'yes' : 'no'); } catch { /* Not remembered. */ }
}
// A person belongs to the brain whose registers name them: on another brain the choice goes back to everyone (on the Board, to
// the position of its switch). "Everyone" and "Me" mean the same in every brain and stay.
function dropPersonFilters() {
  if (isPerson(ids.ownerFilter.value)) ids.ownerFilter.value = '';
  if (isPerson(ids.boardOwner.value)) ids.boardOwner.value = readBoardEveryone() ? '' : OWNER_MINE;
}
function filteredBase() {
  const owner = ownerSelect().value;
  const group = ids.groupFilter.value;
  return snapshot.actions.filter(action =>
    inScope(action.register) &&
    (!group || (group === 'none' ? !action.group : Boolean(action.group) && groupKey(action) === group)) &&
    ownerMatches(action, owner)
  );
}
// One register in scope (a project chosen in the sidebar, a client with a single mission, a brain with a single project):
// a row need not repeat it.
function singleProject() { return snapshot.registers.filter(register => inScope(register.path)).length === 1; }
function scoped(actions) {
  const scope = ids.scopeFilter.value;
  return actions.filter(action => scope === 'all' || (scope === 'active' ? !closed(action) : closed(action)));
}
const STATE_RANK = {'/': 0, ' ': 1, w: 2, x: 3, '-': 4};
const PRIORITY_RANK = {'⏫': 0, '🔼': 1, '': 2, '🔽': 3};
function sortActions(actions) {
  return [...actions].sort((a, b) =>
    STATE_RANK[a.state] - STATE_RANK[b.state] ||
    PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] ||
    (a.due || '9999').localeCompare(b.due || '9999') ||
    a.id.localeCompare(b.id)
  );
}
function byDue(actions) {
  return [...actions].sort((a, b) =>
    (a.due || '9999').localeCompare(b.due || '9999') || PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] || a.id.localeCompare(b.id));
}
// Today: my late, due or scheduled work, my work in progress, what others are late on (someone else's, due date passed), what else
// waits on others (state w or someone else's), then the week ahead.
function todaySections(actions) {
  const day = today();
  const week = addDays(day, 7);
  const sections = {late: [], today: [], doing: [], othersLate: [], waiting: [], week: []};
  for (const action of actions) {
    if (closed(action)) continue;
    const mine = isMine(action);
    if (!mine && action.due && action.due < day) sections.othersLate.push(action);
    else if (action.state === 'w' || !mine) sections.waiting.push(action);
    else if (action.due && action.due < day) sections.late.push(action);
    else if (action.due === day || (action.scheduled && action.scheduled <= day)) sections.today.push(action);
    else if (action.state === '/') sections.doing.push(action);
    else if ((action.due && action.due <= week) || (action.scheduled && action.scheduled <= week)) sections.week.push(action);
  }
  return {late: byDue(sections.late), today: sortActions(sections.today), doing: byDue(sections.doing),
    othersLate: byDue(sections.othersLate), waiting: byDue(sections.waiting), week: byDue(sections.week)};
}
// The actions of a section by owner (as written), in the order they came. First the owners with overdue actions (`late`: owner →
// number of them, the most first), then the ones with the most actions here, then by name.
function ownerGroups(actions, late) {
  const groups = new Map();
  for (const action of actions) {
    if (!groups.has(action.owner)) groups.set(action.owner, {owner: action.owner, actions: []});
    groups.get(action.owner).actions.push(action);
  }
  return [...groups.values()].sort((a, b) =>
    (late.get(b.owner) || 0) - (late.get(a.owner) || 0) || b.actions.length - a.actions.length || a.owner.localeCompare(b.owner, LOCALE));
}

// ---------- Projects (sidebar) ----------
const PARENT_LABELS = {internal: 'Internal', archive: 'Archive'};
// Registers as a tree: a client and its missions, a folder of internal projects, or a project on its own.
function projectTree() {
  const parents = [];
  const byKey = new Map();
  for (const register of snapshot.registers) {
    const parts = register.path.split('/');
    const client = parts[1] === 'clients' && parts.length >= 7;
    const nested = !client && parts.length > 4;
    const key = client ? `projects/clients/${parts[2]}/` : nested ? `projects/${parts[1]}/` : register.path;
    const labels = register.label.split(' / ');
    const label = client ? labels[0] : nested ? PARENT_LABELS[parts[1]] || parts[1] : register.label;
    const child = client ? labels.slice(1).join(' / ') || parts[4] : register.label;
    if (!byKey.has(key)) {
      const node = {key, label, children: []};
      byKey.set(key, node);
      parents.push(node);
    }
    byKey.get(key).children.push({key: register.path, label: child});
  }
  return parents;
}
function scopeLabel(scope) {
  if (!scope) return '';
  const register = snapshot.registers.find(item => item.path === scope);
  if (register) return register.label;
  return projectTree().find(node => node.key === scope)?.label || scope;
}
function validateScope() {
  if (projectScope && !snapshot.registers.some(register => inScope(register.path))) projectScope = '';
}
function projectButton(scope, label, count, className = '') {
  const button = element('button', `project-item${className ? ` ${className}` : ''}`);
  button.type = 'button';
  button.dataset.scope = scope;
  button.setAttribute('aria-current', String(scope === projectScope));
  button.append(element('span', 'nav-label', label), element('span', 'nav-count', count ? String(count) : ''));
  button.title = scope ? `${label}: ${plural(count, 'open action')}` : 'All the actions of the brain';
  button.addEventListener('click', () => {
    const target = pendingPeekView(); // Corvus's app window: the view of the group hovered in the rail while the card peeks (app/shell.js)
    if (target && target !== view) setView(target);
    setProjectScope(scope);
  });
  return button;
}
// The "⋯" of a sidebar entry or of an archived one: a small menu in the popover of the status menu (arrows, Home, End, Esc back to
// the button), also opened by a right click on the entry. `items()` gives [label, pick(button)] pairs; each pick runs the flow the rest
// of the app has for it (`askArchive`: the dry run, then a confirmation).
function entryMenu(entry, name, items) {
  const button = iconButton('icon-button entry-more', `More actions for ${name}`, ICONS.more, 'More actions');
  button.setAttribute('aria-haspopup', 'menu');
  button.setAttribute('aria-expanded', 'false');
  const open = () => openPopover(button, items().map(([label, pick]) => menuItem([element('span', 'menu-item-text', label)], () => pick(button))),
    {label: `Actions for ${name}`});
  button.addEventListener('click', event => {
    event.stopPropagation();
    if (popoverState?.anchor === button) closePopover(); else open();
  });
  for (const node of [entry, button]) node.addEventListener('contextmenu', event => { event.preventDefault(); event.stopPropagation(); open(); });
  return button;
}
// A project or mission offers "New action…" (the + of its header in Actions) and "Archive…"; a client "Archive…" (the whole client).
// "All projects" and the Internal folder have no menu: nothing to archive there.
function projectMenuItems(scope) {
  const target = scopeArchive(scope);
  if (!target) return null;
  return [
    ...(target.kind === 'project' ? [['New action…', () => openEditor(null, {register: scope})]] : []),
    ['Archive…', button => askArchive('archive', target.folder, target.label, button)]
  ];
}
function projectEntry(scope, label, count, className = '') {
  const button = projectButton(scope, label, count, className);
  const items = projectMenuItems(scope);
  if (!items) return button;
  const row = element('div', 'project-row');
  row.append(button, entryMenu(button, scopeLabel(scope) || label, () => items)); // a mission is named with its client
  return row;
}
function renderProjectNav() {
  const counts = new Map();
  for (const action of snapshot.actions) if (!closed(action)) counts.set(action.register, (counts.get(action.register) || 0) + 1);
  const total = [...counts.values()].reduce((sum, count) => sum + count, 0);
  const all = element('li');
  all.append(projectButton('', 'All projects', total, 'project-all'));
  const items = [all];
  for (const parent of projectTree()) {
    const item = element('li');
    if (parent.children.length === 1 && parent.children[0].key === parent.key) {
      item.append(projectEntry(parent.key, parent.label, counts.get(parent.key) || 0));
    } else {
      item.append(projectEntry(parent.key, parent.label, parent.children.reduce((sum, child) => sum + (counts.get(child.key) || 0), 0)));
      const list = element('ul');
      for (const child of parent.children) {
        const entry = element('li');
        entry.append(projectEntry(child.key, child.label, counts.get(child.key) || 0, 'project-child'));
        list.append(entry);
      }
      item.append(list);
    }
    items.push(item);
  }
  if (items.length === 1 && snapshot.registers.length === 0) items.push(element('li', 'project-empty', 'No register'));
  ids.projectNav.replaceChildren(...items);
  renderRailProjects(counts);
}
// ---------- Projects in the folded rail (Corvus window) ----------
// Folded, the rail of a Corvus window shows, under its groups, the top level of the project tree (a client, a folder of internal
// projects), as in the card: the six with the most open actions, by name, each as two letters. A click filters by it, a click on
// the current one clears the filter. With more than six, the sixth is "+N", which shows the card as hovering a group does. app.css
// shows them only in the folded rail of a wide window; each names itself in the rail's bubble (app/shell.js).
const RAIL_PROJECTS = 6;
// "Globex Media" → "GM", "CYBERDYNE" → "CY", "Wonka" → "Wo"; three letters ("Glo", "CYB", "Won") for the ones that would clash.
function railLetters(label, size = 2) {
  const words = label.trim().split(/\s+/).filter(Boolean);
  const first = words[0] || '?';
  if (size === 2 && words.length > 1) return words.slice(0, 2).map(word => word.charAt(0)).join('').toLocaleUpperCase(LOCALE);
  if (first.length > 1 && first === first.toLocaleUpperCase(LOCALE) && first !== first.toLocaleLowerCase(LOCALE)) return first.slice(0, size);
  const letters = words.join('');
  return letters.charAt(0).toLocaleUpperCase(LOCALE) + letters.slice(1, size).toLocaleLowerCase(LOCALE);
}
function railProjectButton(text, name, count, label, current) {
  const button = element('button', 'rail-project', text);
  button.type = 'button';
  button.dataset.name = name; // the bubble's text and count (app/shell.js)
  button.dataset.count = count;
  button.setAttribute('aria-label', label);
  if (current) button.setAttribute('aria-current', 'true');
  return button;
}
function renderRailProjects(counts) {
  const holder = ids.railProjects;
  const focused = holder.contains(document.activeElement) ? document.activeElement.dataset.key : null;
  const inGroup = key => Boolean(projectScope) && (projectScope === key || (key.endsWith('/') && projectScope.startsWith(key)));
  const groups = projectTree().map(node => ({...node, count: node.children.reduce((sum, child) => sum + (counts.get(child.key) || 0), 0)}));
  const room = groups.length > RAIL_PROJECTS ? RAIL_PROJECTS - 1 : RAIL_PROJECTS;
  const shown = [...groups].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, LOCALE)).slice(0, room)
    .sort((a, b) => a.label.localeCompare(b.label, LOCALE));
  const twos = shown.map(group => railLetters(group.label));
  const buttons = shown.map((group, index) => {
    const text = twos.filter(two => two === twos[index]).length > 1 ? railLetters(group.label, 3) : twos[index];
    const current = inGroup(group.key);
    const button = railProjectButton(text, group.label, group.count ? String(group.count) : '', `${group.label}, ${plural(group.count, 'open action')}`, current);
    button.dataset.key = group.key;
    button.addEventListener('click', () => setProjectScope(current ? '' : group.key));
    return button;
  });
  const hidden = groups.filter(group => !shown.includes(group));
  if (hidden.length) {
    const more = railProjectButton(`+${hidden.length}`, plural(hidden.length, 'more project'), '', `${plural(hidden.length, 'more project')}: show them in the card`,
      hidden.some(group => inGroup(group.key)));
    more.dataset.key = '+';
    more.addEventListener('click', event => {
      startPeek(); // the card over the page, as when the pointer is on a group of the rail
      if (event.detail === 0) ids.projectNav.querySelector('.project-item')?.focus(); // from the keyboard: into the card
    });
    buttons.push(more);
  }
  holder.replaceChildren(...buttons);
  if (focused) buttons.find(button => button.dataset.key === focused)?.focus();
}
function setProjectScope(scope) {
  projectScope = scope;
  if (scope) ids.docProject.value = ''; // A project of the sidebar and "Inbox" or "Outside projects" exclude each other.
  populateGroupFilter();
  renderProjectNav();
  saveUIState();
  closeDrawer(false);
  if (isDocsView()) refreshDocLists();
  render();
}

// ---------- Counters ----------
function setSummary() {
  const open = snapshot.actions.filter(action => !closed(action));
  ids.openCount.textContent = open.length ? String(open.length) : '';
  const sections = todaySections(open);
  const urgent = sections.late.length + sections.today.length;
  ids.todayCount.textContent = urgent ? String(urgent) : '';
  ids.todayButton.title = `Focus (1): ${plural(sections.late.length, 'overdue action')}, ${plural(sections.today.length, 'due today', 'due today')}`;
  renderProjectNav();
}
