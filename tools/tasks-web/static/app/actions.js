'use strict';

// ---------- Rows and cards ----------
function loadDetails(action) {
  const key = `${action.id}:${action.version}`;
  if (!detailCache.has(key)) {
    const pending = request(`/api/actions/${encodeURIComponent(action.id)}/details`);
    detailCache.set(key, pending);
    pending.catch(() => detailCache.delete(key));
  }
  return detailCache.get(key);
}
function findAction(id) { return snapshot.actions.find(action => action.id === id); }
function statusButton(action) {
  const button = element('button', 'status-button');
  button.type = 'button';
  button.tabIndex = -1;
  button.setAttribute('aria-haspopup', 'menu');
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-label', `Status: ${statusLabel(action.state).toLowerCase()}. Change the status of ${action.id}`);
  button.title = `${statusLabel(action.state)}: change the status (s)`;
  button.append(statusIcon(action.state));
  button.addEventListener('click', event => {
    event.stopPropagation();
    selectAction(action.id, {focus: false, scroll: false});
    openStatusMenu(action, button);
  });
  return button;
}
function dueButton(action) {
  const button = element('button', action.due ? 'due-button' : 'due-button is-empty');
  button.type = 'button';
  button.tabIndex = -1;
  button.setAttribute('aria-haspopup', 'dialog');
  button.setAttribute('aria-expanded', 'false');
  if (action.due) {
    button.append(dueNode(action));
    button.setAttribute('aria-label', `${dueTitle(action)}. Change the due date of ${action.id}`);
    button.title = `${dueTitle(action)} (d to change)`;
  } else {
    button.append(svgIcon(ICONS.calendar));
    button.setAttribute('aria-label', `Add a due date to ${action.id}`);
    button.title = 'Add a due date (d)';
  }
  button.addEventListener('click', event => {
    event.stopPropagation();
    selectAction(action.id, {focus: false, scroll: false});
    openDueMenu(action, button);
  });
  return button;
}
function deleteButton(action) {
  const button = iconButton('row-action row-delete', `Delete ${action.id}`, ICONS.trash, `Delete ${action.id} (can be undone)`);
  button.tabIndex = -1;
  button.addEventListener('click', event => { event.stopPropagation(); deleteFromRow(action, button); });
  return button;
}
function rowActions(action) {
  const wrap = element('span', 'row-actions');
  const open = iconButton('row-action', `Open the details of ${action.id}`, ICONS.open, 'Open the details (Enter)');
  open.tabIndex = -1;
  open.addEventListener('click', event => { event.stopPropagation(); selectAction(action.id, {focus: false}); openEditor(action); });
  wrap.append(open, deleteButton(action));
  return wrap;
}
function actionClasses(base, action) {
  return `${base}${closed(action) ? ' is-closed' : ''}${action.state === '-' ? ' is-cancelled' : ''}`;
}
// A row of the lists. project: show the project column (Today, when several projects are in scope). owner: show the owner
// column (not under a heading that already names the owner).
function actionRow(action, {project = false, owner = true} = {}) {
  const row = element('div', actionClasses(`row${project ? ' with-project' : ''}${owner ? '' : ' no-owner'}`, action));
  row.dataset.id = action.id;
  row.setAttribute('role', 'listitem');
  const title = element('button', 'row-title');
  title.type = 'button';
  title.tabIndex = -1;
  title.title = action.title;
  title.append(element('span', 'row-title-text', action.title));
  const pill = subtaskPill(action);
  if (pill) title.append(pill, element('span', 'sr-only', `, ${subtaskSummary(action)}`));
  const parts = [statusButton(action), element('span', 'row-id', action.id), title];
  const meta = element('span', 'row-meta');
  meta.append(element('span', '', action.id));
  if (project) {
    const where = element('span', 'row-project', action.project);
    where.title = action.project;
    parts.push(where);
    meta.append(element('span', '', action.project));
  }
  if (owner) {
    const who = element('span', 'row-owner', action.owner);
    who.title = `Owner: ${action.owner}`;
    parts.push(who);
    meta.append(element('span', '', action.owner));
  }
  parts.push(dueButton(action), priorityNode(action), rowActions(action), meta);
  row.append(...parts);
  row.addEventListener('click', event => {
    if (event.target.closest('.status-button, .due-button, .row-action')) return;
    selectAction(action.id, {focus: false, scroll: false});
    openEditor(action);
  });
  return row;
}
function rowList(actions, options) {
  const list = element('div', 'rows');
  list.setAttribute('role', 'list');
  for (const action of actions) list.append(actionRow(action, options));
  return list;
}

// Fold sections (list and board share the keys).
function applyFolds() {
  for (const section of document.querySelectorAll('[data-fold]')) {
    const folded = foldedGroups.has(section.dataset.fold);
    section.querySelector(':scope > .fold-body').hidden = folded;
    section.querySelector(':scope > :first-child > .fold-toggle')?.setAttribute('aria-expanded', String(!folded));
  }
  const keys = listProjectKeys();
  ids.foldAllButton.textContent = keys.length && keys.every(key => foldedGroups.has(key)) ? 'Expand all' : 'Collapse all';
}
function listProjectKeys() { return [...ids.listView.querySelectorAll('[data-fold^="p:"]')].map(section => section.dataset.fold); }
function toggleFold(key) {
  if (foldedGroups.has(key)) foldedGroups.delete(key); else foldedGroups.add(key);
  applyFolds();
  markSelection();
  saveUIState();
}
function setAllFolds() {
  const keys = listProjectKeys();
  if (keys.every(key => foldedGroups.has(key))) {
    for (const section of ids.listView.querySelectorAll('[data-fold]')) foldedGroups.delete(section.dataset.fold);
  } else for (const key of keys) foldedGroups.add(key);
  applyFolds();
  markSelection();
  saveUIState();
}
function foldToggle(key, label) {
  const toggle = element('button', 'fold-toggle');
  toggle.type = 'button';
  toggle.setAttribute('aria-expanded', String(!foldedGroups.has(key)));
  toggle.addEventListener('click', () => toggleFold(key));
  toggle.append(svgIcon(ICONS.chevron, 'fold-chevron'));
  if (label) toggle.setAttribute('aria-label', label);
  return toggle;
}
function addButton(label, preset) {
  const button = iconButton('icon-button fold-add', `Add an action to ${label}`, ICONS.plus);
  button.addEventListener('click', event => { event.stopPropagation(); openEditor(null, preset); });
  return button;
}
// "Archive…" on a project header (Actions): the dry run first, then a confirmation (see `askArchive`).
function archiveButton(label, register) {
  const button = iconButton('icon-button fold-add fold-archive', `Archive ${label}…`, ICONS.archive, `Archive ${label}: check what moves first`);
  button.addEventListener('click', event => { event.stopPropagation(); askArchive('archive', registerFolder(register), label, button); });
  return button;
}
function registerFolder(register) { return register.replace(/\/state\/actions\.md$/, ''); }
// What the sidebar project can archive: a project (one register) or a whole client (`projects/clients/<client>/`); else nothing.
function scopeArchive(scope = projectScope) {
  if (snapshot.registers.some(register => register.path === scope)) return {folder: registerFolder(scope), kind: 'project', label: scopeLabel(scope)};
  const client = /^(projects\/clients\/[^/]+)\/$/.exec(scope);
  return client && client[1].split('/')[2] !== 'archive' ? {folder: client[1], kind: 'client', label: scopeLabel(scope)} : null;
}
// Progress over the members of a project or group (cancelled left out, Status filter ignored).
function progressStats(members) {
  const counted = members.filter(action => action.state !== '-');
  const done = counted.filter(action => action.state === 'x').length;
  const late = counted.filter(action => action.state !== 'x' && action.due && action.due < today()).length;
  return {done, total: counted.length, late};
}
function foldMeta(stats) {
  const meta = element('span', 'fold-meta');
  if (stats.late) meta.append(element('span', 'fold-late', plural(stats.late, 'overdue', 'overdue')));
  const fraction = element('span', '', `${stats.done}/${stats.total}`);
  fraction.title = `${stats.done} of ${stats.total} done`;
  const bar = element('span', 'fold-progress');
  bar.style.setProperty('--p', stats.total ? stats.done / stats.total : 0);
  bar.append(element('span'));
  meta.append(fraction, bar);
  return meta;
}
function foldSection(key, headClass, toggle, extra, body) {
  const section = element('section', 'fold-section');
  section.dataset.fold = key;
  const head = element('div', `fold-head ${headClass}`);
  head.append(toggle, ...extra);
  body.classList.add('fold-body');
  body.hidden = foldedGroups.has(key);
  section.append(head, body);
  return section;
}

// ---------- Today ----------
// On the Board, "Me" and "Everyone" are the two positions of its switch, not a filter to clear: only a person is.
function actionFiltersActive() {
  const owner = view === 'board' ? isPerson(ids.boardOwner.value) : Boolean(ids.ownerFilter.value);
  return Boolean(projectScope || owner || ids.groupFilter.value || (view !== 'today' && view !== 'timeline' && ids.scopeFilter.value !== 'active'));
}
// With filters on, the empty view offers to clear them; otherwise to create an action.
function emptyState(title, text, withButton = true) {
  const box = element('div', 'empty-state');
  if (actionFiltersActive()) {
    box.append(element('h2', '', 'No actions match these filters.'), element('p', '', 'Clear the filters to see everything again.'));
    const button = element('button', 'button', 'Clear filters');
    button.type = 'button';
    button.addEventListener('click', () => ids.resetFilters.click());
    box.append(button);
    return box;
  }
  box.append(element('h2', '', title), element('p', '', text));
  if (withButton) {
    const button = element('button', 'button button-primary');
    button.type = 'button';
    button.append(svgIcon(ICONS.plus), element('span', '', 'New action'));
    button.addEventListener('click', () => openEditor());
    box.append(button);
  }
  return box;
}
// One owner of a "from others" section: a heading with the name and the count, then the rows (which do not repeat the name).
function ownerBlock(id, group, options) {
  const block = element('div', 'owner-group');
  block.setAttribute('role', 'group');
  block.setAttribute('aria-labelledby', id);
  const heading = element('h3', 'owner-head');
  heading.id = id;
  const name = element('span', 'owner-name', group.owner);
  name.title = `Owner: ${group.owner}`;
  heading.append(name, element('span', 'section-count', String(group.actions.length)));
  block.append(heading, rowList(group.actions, {...options, owner: false}));
  return block;
}
// ---------- Focus ----------
// One page for "what should I do now?" (the view `today`): the brain's own actions by urgency, with the sections of the /priorities
// ranking among them when its file is today's (app/priorities.js). The ranking covers the whole brain: with a project chosen, it
// keeps the items that cite an action of that project. Each block has a heading, a count and a quiet line on where its items come
// from; an empty block is left out.
const FOCUS_OWN_BLOCKS = new Set(['now', 'prepare', 'conflicts', 'new-requests', 'follow-ups', 'to-chase', 'warnings']); // the sections with a block (or a banner) of their own
function focusBlock(key, title, count, hint, parts) {
  const section = element('section', `section focus-block focus-${key}`);
  section.setAttribute('aria-labelledby', `focus-${key}`);
  const head = element('div', 'section-head');
  const heading = element('h2', '', title);
  heading.id = `focus-${key}`;
  head.append(heading, element('span', 'section-count', String(count)));
  section.append(head, element('p', 'focus-hint', hint), ...parts);
  return section;
}
// A sub-heading inside a block, in the style of the owners' headings.
function focusSub(text) { return element('h3', 'owner-head focus-sub', text); }
function focusPrio(section) {
  const box = element('div', 'focus-prio');
  box.append(prioBody(section));
  return box;
}
function renderToday(base) {
  const sections = todaySections(base);
  const options = {project: !singleProject()};
  // Today's ranking only; with a project chosen, each of its sections keeps the items that cite an action in scope (prioScoped).
  const prio = freshPriorities();
  const ranked = prio ? prio.sections.filter(section => section.key !== 'warnings').map(prioScoped) : [];
  const rankedSection = key => ranked.find(section => section.key === key) || null;
  ids.viewNote.textContent = prioSourceLine(ranked.reduce((sum, section) => sum + section.count, 0));
  ids.viewNote.hidden = !ids.viewNote.textContent;
  const openDrafts = new Set([...ids.todayView.querySelectorAll('.prio-draft[open]')].map(draftKey));
  const moreOpen = ids.todayView.querySelector('.focus-more')?.open === true;
  // Who is late, over both "from others" blocks: those owners lead each of them.
  const late = new Map();
  for (const action of [...sections.othersLate, ...sections.waiting]) {
    if (action.due && action.due < today()) late.set(action.owner, (late.get(action.owner) || 0) + 1);
  }
  const byOwner = (key, actions) => ownerGroups(actions, late).map((group, index) => ownerBlock(`focus-${key}-owner-${index}`, group, options));
  const blocks = [];
  const nodes = [];
  // Now: the ranking's Now items, then my overdue and due-today actions they do not cite; those actions alone without a ranking.
  const now = rankedSection('now');
  const urgent = [...sections.late, ...sections.today];
  if (now?.count) {
    const cited = prioCitedIds(now);
    const also = urgent.filter(action => !cited.has(action.id));
    const parts = [focusPrio(now)];
    if (also.length) parts.push(focusSub('Also overdue or due today'), rowList(also, options));
    blocks.push(focusBlock('now', 'Now', now.count + also.length, 'Ranked by /priorities, then your other actions past their due date or due today', parts));
  } else if (urgent.length) {
    blocks.push(focusBlock('now', 'Now', urgent.length, 'Your actions past their due date or due today', [rowList(urgent, options)]));
  }
  for (const [key, title, hint] of [['prepare', 'To prepare', 'From /priorities: what to get ready before a meeting or a deadline'],
    ['conflicts', 'Conflicts', 'From /priorities: clashes in your agenda'], ['new-requests', 'New requests', 'From /priorities: requests received since the last message review']]) {
    const section = rankedSection(key);
    if (section?.count) blocks.push(focusBlock(key, title, section.count, hint, [focusPrio(section)]));
  }
  if (sections.doing.length) blocks.push(focusBlock('doing', 'In progress', sections.doing.length, 'Your actions in progress', [rowList(sections.doing, options)]));
  // To chase: what others are late on, by owner, then the follow-ups the ranking drafted (with their messages).
  const followUps = ['follow-ups', 'to-chase'].map(rankedSection).filter(section => section?.count);
  const chaseCount = sections.othersLate.length + followUps.reduce((sum, section) => sum + section.count, 0);
  if (chaseCount) {
    const parts = byOwner('chase', sections.othersLate);
    if (followUps.length) parts.push(...(sections.othersLate.length ? [focusSub('Drafted by /priorities')] : []), ...followUps.map(focusPrio));
    blocks.push(focusBlock('chase', 'To chase', chaseCount, followUps.length ? 'Actions of others past their due date, and the follow-ups drafted by /priorities' : 'Actions of others past their due date', parts));
  }
  if (sections.waiting.length) blocks.push(focusBlock('waiting', 'Waiting on others', sections.waiting.length, 'Waiting, or assigned to someone else', byOwner('waiting', sections.waiting)));
  if (sections.week.length) {
    blocks.push(focusBlock('week', 'This week', sections.week.length, `Your actions due or scheduled until ${DAY_FORMAT.format(parseDay(addDays(today(), 7)))}`, [rowList(sections.week, options)]));
  }
  // The rest of the ranking (To close, Lingering, Admin, any other section), folded away.
  const rest = ranked.filter(section => !FOCUS_OWN_BLOCKS.has(section.key) && section.count);
  if (rest.length) {
    const more = element('details', 'focus-more');
    more.open = moreOpen;
    const summary = element('summary', 'focus-more-summary');
    summary.append(element('span', 'focus-more-title', 'Also from /priorities'), element('span', 'section-count', String(rest.reduce((sum, section) => sum + section.count, 0))),
      element('span', 'focus-hint', rest.map(section => section.title).join(', ')));
    more.append(summary, ...rest.flatMap(section => [focusSub(section.title), focusPrio(section)]));
    const section = element('section', 'section focus-block focus-rest');
    section.setAttribute('aria-label', 'Also from /priorities');
    section.append(more);
    blocks.push(section);
  }
  // The ranking's warnings: one compact banner at the top (about the registers as a whole: kept with a project chosen).
  const warnings = prio && prioSection('warnings');
  if (warnings?.count) {
    const banner = element('section', 'focus-warnings');
    banner.setAttribute('role', 'note');
    banner.setAttribute('aria-label', 'Warnings from /priorities');
    banner.append(prioBody(warnings));
    nodes.push(banner);
  }
  const total = sections.late.length + sections.today.length + sections.doing.length + sections.othersLate.length + sections.waiting.length + sections.week.length;
  ids.resultCount.textContent = plural(total, 'action');
  if (!blocks.length) {
    ids.todayView.replaceChildren(...nodes, emptyState('Nothing to focus on right now.', 'Overdue actions, actions due today, work in progress, what waits on others and the /priorities ranking appear here.'));
    return;
  }
  ids.todayView.replaceChildren(...nodes, ...blocks);
  for (const draft of ids.todayView.querySelectorAll('.prio-draft')) draft.open = openDrafts.has(draftKey(draft)); // the drafts that were open stay open
  markOpenAction();
}

// ---------- Actions (list) ----------
function renderList(actions) {
  const qualifier = ids.scopeFilter.value === 'active' ? 'open ' : ids.scopeFilter.value === 'closed' ? 'closed ' : '';
  ids.resultCount.textContent = plural(actions.length, `${qualifier}action`);
  if (!actions.length) {
    ids.listView.replaceChildren(emptyState('No actions here.', 'Try another filter or create an action.'));
    return;
  }
  const base = filteredBase();
  const order = new Map(snapshot.registers.map((register, index) => [register.path, index]));
  const byRegister = new Map();
  for (const action of actions) {
    if (!byRegister.has(action.register)) byRegister.set(action.register, []);
    byRegister.get(action.register).push(action);
  }
  const nodes = [];
  for (const [register, shown] of [...byRegister.entries()].sort((a, b) => (order.get(a[0]) ?? 0) - (order.get(b[0]) ?? 0))) {
    const label = shown[0].project;
    const members = base.filter(action => action.register === register);
    const body = element('div');
    const groups = new Map();
    for (const action of shown) {
      if (!action.group) continue;
      if (!groups.has(action.group)) groups.set(action.group, []);
      groups.get(action.group).push(action);
    }
    const loose = shown.filter(action => !action.group);
    const sorted = [...groups.entries()].sort((a, b) => groupLabel(a[0]).localeCompare(groupLabel(b[0]), LOCALE) || a[0].localeCompare(b[0]));
    for (const [slug, groupActions] of sorted) {
      const key = `${register}|${slug}`;
      const name = groupLabel(slug);
      const stats = progressStats(members.filter(action => action.group === slug));
      const toggle = foldToggle(key, `Group ${name}, ${stats.done} of ${stats.total} done`);
      toggle.append(element('span', `group-dot ${groupTone(slug)}`), element('span', 'fold-label', name), foldMeta(stats));
      const rows = rowList(sortActions(groupActions), {});
      rows.classList.add('in-group');
      body.append(foldSection(key, 'group-head', toggle, [addButton(`${name} (${label})`, {register, group: slug})], rows));
    }
    if (loose.length && sorted.length) {
      const key = `${register}|`;
      const toggle = foldToggle(key, 'No group');
      toggle.append(element('span', 'group-dot'), element('span', 'fold-label', 'No group'), foldMeta(progressStats(members.filter(action => !action.group))));
      const rows = rowList(sortActions(loose), {});
      rows.classList.add('in-group');
      body.append(foldSection(key, 'group-head', toggle, [addButton(`${label}, no group`, {register})], rows));
    } else if (loose.length) body.append(rowList(sortActions(loose), {}));
    const stats = progressStats(members);
    const toggle = foldToggle(`p:${register}`, `${label}, ${stats.done} of ${stats.total} done`);
    toggle.append(element('span', 'fold-label', label), foldMeta(stats));
    nodes.push(foldSection(`p:${register}`, 'project-head', toggle, [addButton(label, {register}), archiveButton(label, register)], body));
  }
  ids.listView.replaceChildren(...nodes);
  applyFolds();
}

// ---------- Board ----------
function makeCard(action, grouped = false) {
  const card = element('article', actionClasses(`card ${statusInfo(action.state).cls}`, action));
  card.dataset.id = action.id;
  card.draggable = true;
  const top = element('div', 'card-top');
  const title = element('button', 'card-title', action.title);
  title.type = 'button';
  title.tabIndex = -1;
  title.title = `${action.title}\nOwner: ${action.owner}`;
  top.append(statusButton(action), title);
  const meta = element('div', 'card-meta');
  meta.append(element('span', 'row-id', action.id));
  const pill = subtaskPill(action);
  if (pill) {
    meta.append(pill);
    title.append(element('span', 'sr-only', `, ${subtaskSummary(action)}`));
  }
  if (!grouped) {
    const where = element('span', 'card-project', shortProject(action.project));
    where.title = action.project;
    meta.append(where);
  }
  if (grouped) {
    const owner = element('span', 'card-project', action.owner);
    owner.title = `Owner: ${action.owner}`;
    meta.append(owner);
  }
  if (action.due) meta.append(dueNode(action));
  if (PRIORITY[action.priority]) meta.append(priorityNode(action));
  const actions = element('div', 'card-actions');
  actions.append(deleteButton(action));
  card.append(top, meta, actions);
  card.addEventListener('click', event => {
    if (event.target.closest('.status-button, .row-action')) return;
    selectAction(action.id, {focus: false, scroll: false});
    openEditor(action);
  });
  // Buttons inside the card must not start a drag (the title still may); capture phase, as the status button stops its own events.
  card.addEventListener('pointerdown', event => { card.draggable = !event.target.closest('button:not(.card-title)'); }, true);
  for (const type of ['pointerup', 'pointercancel', 'dragend']) card.addEventListener(type, () => { card.draggable = true; });
  card.addEventListener('dragstart', event => {
    if (event.target.closest?.('button:not(.card-title)')) { event.preventDefault(); return; }
    closePopover(false);
    event.dataTransfer.setData('text/plain', action.id);
    event.dataTransfer.effectAllowed = 'move';
  });
  return card;
}
// A column's cards under one header per (project, group), "No group" last; the header folds them (keys shared with the list).
function boardGroup(key, cards, group = null, state = ' ') {
  const toggle = foldToggle(key, group ? `${group.label}, ${group.project}, ${plural(cards.length, 'card')}` : `No group, ${plural(cards.length, 'card')}`);
  if (group) {
    const where = element('span', 'board-group-project', shortProject(group.project));
    where.title = group.project;
    toggle.append(element('span', `group-dot ${groupTone(group.slug)}`), element('span', 'fold-label', group.label), where);
  }
  else toggle.append(element('span', 'group-dot'), element('span', 'fold-label', 'No group'));
  toggle.append(element('span', 'board-group-count', String(cards.length)));
  const body = element('div', 'board-group-cards');
  cards.forEach(action => body.append(makeCard(action, Boolean(group))));
  const section = foldSection(key, 'board-group-head', toggle, group ? [addButton(`${group.label} (${group.project})`, {register: group.register, group: group.slug, state})] : [], body);
  section.className = 'board-group fold-section';
  section.firstChild.className = 'board-group-head';
  return section;
}
function renderBoard(base) {
  const scope = ids.scopeFilter.value;
  const columns = [
    {state: ' ', title: 'To do'},
    {state: '/', title: 'In progress'},
    {state: 'w', title: 'Waiting'},
    {state: 'x', title: 'Recently done'}
  ];
  let shownTotal = 0;
  const panels = [];
  for (const column of columns) {
    const panel = element('section', 'board-column');
    const all = base.filter(action => column.state === 'x' ? closed(action) : action.state === column.state);
    let actions;
    if (column.state === 'x') actions = [...all].sort((a, b) => (b.done || '').localeCompare(a.done || '') || b.id.localeCompare(a.id)).slice(0, 10);
    else if (scope === 'closed') actions = [];
    else actions = sortActions(all);
    shownTotal += actions.length;
    const heading = element('h2', 'board-heading');
    heading.id = `column-${column.state === ' ' ? 'todo' : column.state === '/' ? 'doing' : column.state}`;
    heading.append(statusIcon(column.state), element('span', '', column.title), element('span', 'board-count', String(actions.length)));
    panel.setAttribute('aria-labelledby', heading.id);
    const cards = element('div', 'board-cards');
    if (!actions.length) cards.append(element('p', 'board-empty', 'No actions'));
    else if (!actions.some(action => action.group)) actions.forEach(action => cards.append(makeCard(action)));
    else {
      const buckets = new Map();
      for (const action of actions) {
        if (!action.group) continue;
        const key = groupKey(action);
        if (!buckets.has(key)) buckets.set(key, {key, slug: action.group, register: action.register, project: action.project, label: groupLabel(action.group), cards: []});
        buckets.get(key).cards.push(action);
      }
      const state = column.state === 'x' ? ' ' : column.state;
      for (const group of [...buckets.values()].sort(compareGroups)) cards.append(boardGroup(group.key, group.cards, group, state));
      const loose = actions.filter(action => !action.group);
      if (loose.length) cards.append(boardGroup(NO_GROUP, loose));
    }
    panel.append(heading, cards);
    panel.addEventListener('dragover', event => { event.preventDefault(); panel.classList.add('drag-over'); });
    panel.addEventListener('dragleave', event => { if (!panel.contains(event.relatedTarget)) panel.classList.remove('drag-over'); });
    panel.addEventListener('drop', async event => {
      event.preventDefault();
      panel.classList.remove('drag-over');
      const action = findAction(event.dataTransfer.getData('text/plain'));
      if (action && action.state !== column.state) await updateStatus(action, column.state);
    });
    panels.push(panel);
  }
  ids.resultCount.textContent = plural(shownTotal, 'action');
  ids.boardView.replaceChildren(...panels);
  applyFolds();
}
