'use strict';

// ---------- Archives ----------
// The archived clients, missions and internal projects (moved whole into an `archive/` folder by `brain-state.py archive`): out of every
// other view and of the global search, listed and read here, read-only. While this view is open, the header field searches the archives
// alone. Archive (a project header in Actions, or the filter row when a project or a client is chosen in the sidebar) and Unarchive
// (here) run the tool's dry run first and show what moves, or what blocks; the write is one undo step, whose undo is the inverse command.
const ARCHIVE_KIND_LABELS = {client: 'Client', mission: 'Mission', internal: 'Internal project'};
const ARCHIVE_KIND_HEADINGS = {client: 'Clients', mission: 'Missions', internal: 'Internal projects'};
let archivesData = null; // GET /api/archives: {archives, actions, clients}
let archivesRequest = 0;
let archiveError = '';
let archiveSelected = ''; // the folder open in the pane
let archiveProject = null; // GET /api/archives/project of it ({error} when it could not be read)
let archiveDocOpen = null; // one of its documents, open in the pane (Back returns to the project)
let archivePaneRequest = 0;
let archiveDocRequest = 0;
let archiveSearch = null; // {query, terms, actions, docs, total, pending, error} while the header field holds a query in this view
let archiveSearchRequest = 0;
let archiveAsk = null; // the open confirmation: {verb, folder, label, ready, busy, returnFocus}

function archiveName(item) { return item.kind === 'client' ? displayClient(item.client) : displayProject(item.label); }
function archiveCounts(counts) {
  if (!counts.total) return 'No action';
  return `${plural(counts.total, 'action')}: ${counts.done} done, ${counts.cancelled} cancelled${counts.open ? `, ${counts.open} open` : ''}`;
}
function setArchiveStatus(message, failed = false) {
  ids.archiveStatus.textContent = message;
  ids.archiveStatus.classList.toggle('doc-status-error', failed);
}
async function loadArchives() {
  const requestId = ++archivesRequest;
  if (!archivesData && view === 'archives') setArchiveStatus('Loading…');
  try {
    const data = await request('/api/archives');
    if (requestId !== archivesRequest) return;
    clientNames = {...clientNames, ...(data.clients || {})};
    for (const action of data.actions) {
      action.project_key = action.project;
      action.project = displayProject(action.project);
    }
    archivesData = data;
    archiveError = '';
    setArchiveStatus('');
    if (archiveSelected && !data.archives.some(item => item.folder === archiveSelected)) closeArchive();
    else if (archiveSelected && !archiveDocOpen) openArchive(archiveSelected, {quiet: true});
    if (archiveSearch) runArchiveSearch();
    else if (view === 'archives') renderArchives();
  } catch (error) {
    if (requestId !== archivesRequest || error.stale) return;
    archiveError = error.message;
    setArchiveStatus('');
    if (view === 'archives') renderArchives();
  }
}
function renderArchives() {
  renderArchiveList();
  renderArchivePane();
}
function archiveListItem(item) {
  const li = element('li');
  const button = element('button', 'doc-item archive-item');
  button.type = 'button';
  button.dataset.folder = item.folder;
  button.setAttribute('aria-pressed', String(item.folder === archiveSelected));
  const meta = element('span', 'doc-item-meta');
  meta.append(element('span', 'doc-item-type', ARCHIVE_KIND_LABELS[item.kind]));
  if (item.archived_on) meta.append(element('span', 'doc-item-date', `Archived ${formatDay(item.archived_on)}`));
  meta.append(element('span', '', archiveCounts(item.counts)));
  button.append(element('span', 'doc-item-title', archiveName(item)), meta);
  button.addEventListener('click', () => openArchive(item.folder));
  li.className = 'archive-entry';
  li.append(button, entryMenu(button, archiveName(item), () => [['Unarchive…', anchor => askArchive('unarchive', item.folder, archiveName(item), anchor)]]));
  return li;
}
function renderArchiveList() {
  if (archiveSearch) { renderArchiveSearch(); return; }
  const items = archivesData?.archives || [];
  ids.resultCount.textContent = archivesData ? plural(items.length, 'archive') : '';
  if (archiveError) { ids.archiveList.replaceChildren(docEmpty('The archives could not be read.', archiveError)); return; }
  if (!archivesData) { ids.archiveList.replaceChildren(); return; }
  if (!items.length) {
    ids.archiveList.replaceChildren(docEmpty('Nothing is archived.', 'A finished project archived from its header in Actions, or from the filter row when a project or a client is chosen in the sidebar, appears here.'));
    return;
  }
  const nodes = [];
  for (const kind of ['client', 'mission', 'internal']) {
    const group = items.filter(item => item.kind === kind).sort((a, b) => archiveName(a).localeCompare(archiveName(b), LOCALE));
    if (!group.length) continue;
    const list = element('ul', 'doc-items');
    list.append(...group.map(archiveListItem));
    nodes.push(searchHead(ARCHIVE_KIND_HEADINGS[kind], String(group.length)), list);
  }
  ids.archiveList.replaceChildren(...nodes);
}
async function openArchive(folder, {quiet = false, action = ''} = {}) {
  archiveSelected = folder;
  if (!quiet) {
    archiveProject = null;
    archiveDocOpen = null;
    archiveDocRequest += 1;
  }
  const requestId = ++archivePaneRequest;
  if (!quiet) renderArchivePane();
  try {
    const data = await request(`/api/archives/project?${new URLSearchParams({folder})}`);
    if (requestId !== archivePaneRequest) return;
    archiveProject = data;
  } catch (error) {
    if (requestId !== archivePaneRequest || error.stale) return;
    archiveProject = {error: error.message};
  }
  if (archiveDocOpen) return; // a document opened meanwhile stays on screen
  renderArchivePane();
  const row = action && ids.archiveBody.querySelector(`details[data-id="${CSS.escape(action)}"]`);
  if (row) {
    row.open = true;
    row.scrollIntoView({block: 'center'});
    row.querySelector('summary').focus({preventScroll: true});
  } else if (!quiet) ids.archivePaneTitle.focus({preventScroll: true});
}
function closeArchive() {
  archiveSelected = '';
  archiveProject = null;
  archiveDocOpen = null;
  archivePaneRequest += 1;
  archiveDocRequest += 1;
}
// A document of an archived project, read-only (`archived=1`: the server reads only those there). From a search result, the archive it
// belongs to becomes the selected one, so that Back leads to it.
async function openArchiveDoc(id) {
  const owner = archivesData?.archives.find(item => id.startsWith(`${item.folder}/`));
  if (owner && owner.folder !== archiveSelected) {
    archiveSelected = owner.folder;
    archiveProject = null;
    openArchive(owner.folder, {quiet: true});
  }
  const requestId = ++archiveDocRequest;
  try {
    const doc = await request(`/api/docs/render?${new URLSearchParams({id, archived: '1'})}`);
    if (requestId !== archiveDocRequest) return;
    doc.project = displayProject(doc.project);
    archiveDocOpen = doc;
    renderArchivePane();
    ids.archivePaneTitle.focus({preventScroll: true});
  } catch (error) {
    if (requestId !== archiveDocRequest || error.stale) return;
    showToast(error.message);
  }
}
function archiveMeta(parts) {
  ids.archivePaneMeta.replaceChildren(...parts.filter(Boolean).map(text => element('span', '', text)));
}
function renderArchivePane() {
  const item = archivesData?.archives.find(entry => entry.folder === archiveSelected);
  ids.archivesView.classList.toggle('has-doc', Boolean(archiveSelected));
  for (const button of ids.archiveList.querySelectorAll('.archive-item')) button.setAttribute('aria-pressed', String(button.dataset.folder === archiveSelected));
  ids.archivePaneEmpty.hidden = Boolean(archiveSelected);
  ids.archiveBody.hidden = !archiveSelected;
  ids.archiveBack.hidden = !archiveDocOpen;
  ids.archiveUnarchive.hidden = !item || Boolean(archiveDocOpen);
  if (!archiveSelected) {
    ids.archivePaneTitle.textContent = 'Archives';
    archiveMeta([]);
    ids.archiveBody.replaceChildren();
    return;
  }
  if (archiveDocOpen) {
    ids.archivePaneTitle.textContent = archiveDocOpen.title;
    archiveMeta([archiveDocOpen.project, 'Archived, read-only']);
    const article = element('article', 'markdown-body archive-doc');
    article.innerHTML = archiveDocOpen.html; // rendered by the server: raw HTML of the document escaped, links checked
    ids.archiveBody.replaceChildren(article);
    ids.archiveBody.scrollTop = 0;
    return;
  }
  ids.archivePaneTitle.textContent = item ? archiveName(item) : 'Archive';
  archiveMeta(item ? [ARCHIVE_KIND_LABELS[item.kind], item.archived_on ? `Archived ${formatDay(item.archived_on)}` : '', archiveCounts(item.counts), 'Read-only'] : []);
  if (!archiveProject) { ids.archiveBody.replaceChildren(element('p', 'archive-loading', 'Loading…')); return; }
  if (archiveProject.error) { ids.archiveBody.replaceChildren(element('p', 'form-error', archiveProject.error)); return; }
  const nodes = [];
  if (archiveProject.page) nodes.push(archivePage(archiveProject.page));
  const several = archiveProject.projects.length > 1 || archiveProject.kind === 'client';
  for (const project of archiveProject.projects) nodes.push(archiveProjectSection(project, several));
  if (archiveProject.docs.length) nodes.push(archiveDocsSection(archiveProject.docs));
  ids.archiveBody.replaceChildren(...nodes);
}
// The page of the archive, read in place (its links to other archived documents open them here).
function archivePage(id) {
  const article = element('article', 'markdown-body archive-page');
  article.append(element('p', 'archive-loading', 'Loading the page…'));
  const requestId = archivePaneRequest;
  request(`/api/docs/render?${new URLSearchParams({id, archived: '1'})}`).then(doc => {
    if (requestId === archivePaneRequest && article.isConnected) article.innerHTML = doc.html;
  }).catch(error => { if (article.isConnected) article.replaceChildren(element('p', 'form-error', error.message)); });
  return article;
}
function archiveProjectSection(project, named) {
  const section = element('section', 'archive-section');
  const head = element('div', 'archive-section-head');
  head.append(element('h3', '', named ? displayProject(project.label) : `Actions`), element('span', 'section-count', String(project.actions.length)));
  for (const [id, label] of [[project.page, 'Page'], [project.decisions, 'Decisions']]) {
    if (!id) continue;
    const button = element('button', 'link-button', label);
    button.type = 'button';
    button.setAttribute('aria-label', `${label} of ${displayProject(project.label)}`);
    button.addEventListener('click', () => openArchiveDoc(id));
    head.append(button);
  }
  section.append(head);
  const list = element('ul', 'archive-actions');
  list.setAttribute('aria-label', `Actions of ${displayProject(project.label)}`);
  if (!project.actions.length) list.append(element('li', 'note-empty', 'No action.'));
  for (const action of sortActions(project.actions)) list.append(archiveActionItem(action));
  section.append(list);
  return section;
}
// An archived action: one line, read-only; opening it shows its subtasks and its history (newest first), nothing to edit.
function archiveActionItem(action) {
  const item = element('li');
  const details = element('details', `archive-action${closed(action) ? ' is-closed' : ''}${action.state === '-' ? ' is-cancelled' : ''}`);
  details.dataset.id = action.id;
  const summary = element('summary', 'archive-action-line');
  const state = statusIcon(action.state);
  state.setAttribute('role', 'img');
  state.setAttribute('aria-label', statusLabel(action.state));
  const title = element('span', 'archive-action-title', action.title);
  summary.append(state, element('span', 'row-id', action.id), title);
  const pill = subtaskPill(action);
  if (pill) summary.append(pill);
  summary.append(element('span', 'archive-action-owner', action.owner));
  if (action.done) summary.append(element('span', 'due due-closed', formatDay(action.done)));
  const body = element('div', 'archive-action-body');
  details.append(summary, body);
  details.addEventListener('toggle', () => {
    if (!details.open || body.dataset.loaded) return;
    body.dataset.loaded = '1';
    body.replaceChildren(element('p', 'archive-loading', 'Loading…'));
    request(`/api/actions/${encodeURIComponent(action.id)}/details`).then(found => {
      const nodes = [];
      if (found.subtasks?.length) {
        const steps = element('ul', 'archive-subtasks');
        steps.setAttribute('aria-label', 'Subtasks');
        for (const step of found.subtasks) steps.append(element('li', step.done ? 'is-done' : '', `${step.done ? '☑' : '☐'} ${step.text}`));
        nodes.push(steps);
      }
      const notes = found.notes.filter(note => !/^-?\s*(created|updated)\s*:/i.test(note.text)).reverse();
      const history = element('ul', 'archive-history');
      history.setAttribute('aria-label', 'History');
      for (const note of notes) history.append(element('li', '', note.text.replace(/^-\s+/, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')));
      if (!notes.length) history.append(element('li', 'note-empty', 'No history.'));
      nodes.push(history);
      body.replaceChildren(...nodes);
    }).catch(error => { body.replaceChildren(element('p', 'form-error', error.message)); delete body.dataset.loaded; });
  });
  item.append(details);
  return item;
}
function archiveDocsSection(docs) {
  const section = element('section', 'archive-section');
  const head = element('div', 'archive-section-head');
  head.append(element('h3', '', 'Documents'), element('span', 'section-count', String(docs.length)));
  const list = element('ul', 'archive-docs');
  for (const doc of docs) {
    const li = element('li');
    const button = element('button', 'archive-doc-link');
    button.type = 'button';
    button.append(element('span', 'doc-item-type', DOC_TYPE_LABELS[doc.type] || doc.type), element('span', 'archive-doc-title', doc.title));
    if (doc.date) button.append(element('span', 'doc-item-date', formatDay(doc.date)));
    button.addEventListener('click', () => openArchiveDoc(doc.id));
    li.append(button);
    list.append(li);
  }
  section.append(head, list);
  return section;
}
// The header field, in this view: the archived actions (matched here, at once) and the documents of the archived projects (the server).
function runArchiveSearch() {
  clearTimeout(docTimer);
  const query = ids.searchInput.value.trim();
  const requestId = ++archiveSearchRequest;
  if (!query) {
    archiveSearch = null;
    if (view === 'archives') renderArchives();
    return;
  }
  const terms = searchTerms(query);
  archiveSearch = {query, terms, actions: terms.length ? (archivesData?.actions || []).filter(action => actionMatches(action, terms)) : [],
    docs: [], total: 0, pending: terms.length > 0, error: ''};
  renderArchives();
  if (!terms.length) return;
  request(`/api/search?${new URLSearchParams({q: query, archived: '1'})}`).then(data => {
    if (requestId !== archiveSearchRequest || !archiveSearch) return;
    Object.assign(archiveSearch, {docs: nameDocs(data.results), total: data.total, terms: data.terms, pending: false});
    if (view === 'archives') renderArchives();
  }).catch(error => {
    if (requestId !== archiveSearchRequest || error.stale || !archiveSearch) return;
    Object.assign(archiveSearch, {pending: false, error: error.message});
    if (view === 'archives') renderArchives();
  });
}
function renderArchiveSearch() {
  const found = archiveSearch;
  ids.resultCount.textContent = found.terms.length ? `${plural(found.actions.length, 'action')}, ${found.pending ? '…' : plural(found.total, 'document')}` : '';
  if (!found.terms.length) { ids.archiveList.replaceChildren(searchNone('Type two letters or more.')); return; }
  const actions = element('ul', 'doc-items');
  for (const action of found.actions.slice(0, SEARCH_ACTION_LIMIT)) {
    const li = element('li');
    const button = element('button', 'doc-item');
    button.type = 'button';
    const title = element('span', 'doc-item-title');
    title.append(docMarked(action.title, docFindRanges(action.title, found.terms)));
    const meta = element('span', 'doc-item-meta');
    meta.append(element('span', 'doc-item-id', action.id), element('span', '', action.project), element('span', '', statusLabel(action.state)));
    button.append(title, meta);
    button.addEventListener('click', () => openArchive(action.folder, {action: action.id}));
    li.append(button);
    actions.append(li);
  }
  const docs = element('ul', 'doc-items');
  for (const item of found.docs) {
    const li = element('li');
    const button = element('button', 'doc-item');
    button.type = 'button';
    const title = element('span', 'doc-item-title');
    title.append(docMarked(item.title, docFindRanges(item.title, found.terms)));
    const meta = element('span', 'doc-item-meta');
    if (DOC_TYPE_LABELS[item.type]) meta.append(element('span', 'doc-item-type', DOC_TYPE_LABELS[item.type]));
    meta.append(element('span', '', item.project || ''));
    button.append(title, meta);
    for (const snippet of item.snippets || []) button.append(docSnippetNode(snippet));
    button.addEventListener('click', () => openArchiveDoc(item.id));
    li.append(button);
    docs.append(li);
  }
  ids.archiveList.replaceChildren(
    searchHead('Archived actions', String(found.actions.length)), found.actions.length ? actions : searchNone('No archived action matches.'),
    searchHead('Archived documents', found.pending ? '…' : String(found.total)),
    found.error ? searchNone(found.error, true) : found.pending ? searchNone('Searching…') : found.docs.length ? docs : searchNone('No archived document matches.'));
}
// Archive or unarchive: the dry run (what moves, the links rewritten), or the refusal with the actions that block it; then the write.
async function askArchive(verb, folder, label, returnFocus = document.activeElement) {
  if (archiveAsk?.busy) return;
  const ask = {verb, folder, label, ready: false, busy: false, returnFocus};
  archiveAsk = ask;
  const word = verb === 'archive' ? 'Archive' : 'Unarchive';
  ids.archiveHeading.textContent = `${word} ${label}?`;
  ids.archiveText.textContent = 'Checking what would move…';
  ids.archiveDialogList.replaceChildren();
  ids.archiveDialogList.hidden = true;
  ids.archiveDialogError.hidden = true;
  ids.archiveConfirm.textContent = word;
  ids.archiveConfirm.hidden = false;
  ids.archiveConfirm.disabled = true;
  ids.archiveCancel.textContent = 'Cancel';
  if (!ids.archiveDialog.open) ids.archiveDialog.showModal();
  try {
    const plan = await request(`/api/archives/plan?${new URLSearchParams({verb, folder})}`);
    if (archiveAsk !== ask) return;
    ask.ready = true;
    ids.archiveText.textContent = verb === 'archive'
      ? 'It leaves every view and the search, and stays readable in Archives. Undo, or Unarchive there, brings it back.'
      : 'It comes back to the views and the search, where it was.';
    const lines = [`Moves ${plan.from} to ${plan.to}.`,
      plan.links ? `Rewrites ${plural(plan.links, 'link')} in ${plural(plan.link_files.length, 'file')}, so that they still lead to it.` : 'No link to rewrite.'];
    if (plan.mentions_left.length) lines.push(`Not links, left as they are: ${plan.mentions_left.map(item => `${item.file} (${item.count})`).join(', ')}.`);
    ids.archiveDialogList.replaceChildren(...lines.map(text => element('li', '', text)));
    ids.archiveDialogList.hidden = false;
    ids.archiveConfirm.disabled = false;
    ids.archiveConfirm.focus();
  } catch (error) {
    if (archiveAsk !== ask) return;
    showArchiveRefusal(error);
  }
}
function showArchiveRefusal(error) {
  const blocking = error.data?.open_actions || [];
  // The tool names the project by its folders (`client acme`, `acme / demo`): the dialog says it as its heading does.
  const message = blocking.length && archiveAsk ? error.message.replace(/^.*? cannot be archived/, `${archiveAsk.label} cannot be archived`) : nameLabels(error.message);
  ids.archiveText.textContent = message ? message[0].toLocaleUpperCase(LOCALE) + message.slice(1) : '';
  ids.archiveDialogList.replaceChildren(...blocking.map(item => {
    const li = element('li');
    const button = element('button', 'link-button archive-blocking', `${item.id} — ${item.title}`);
    button.type = 'button';
    button.title = `Open ${item.id}`;
    button.addEventListener('click', () => {
      const action = findAction(item.id);
      ids.archiveDialog.close();
      if (action) openEditor(action);
    });
    li.append(button);
    return li;
  }));
  ids.archiveDialogList.hidden = !blocking.length;
  ids.archiveConfirm.hidden = true;
  ids.archiveCancel.textContent = 'Close';
  ids.archiveCancel.focus();
}
async function confirmArchive() {
  const ask = archiveAsk;
  if (!ask?.ready || ask.busy) return;
  ask.busy = true;
  ids.archiveConfirm.disabled = true;
  ids.archiveConfirm.setAttribute('aria-busy', 'true');
  ids.archiveDialogError.hidden = true;
  ids.archiveText.textContent = ask.verb === 'archive' ? 'Archiving…' : 'Unarchiving…';
  try {
    const result = await request(`/api/archives/${ask.verb}`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token}, body: JSON.stringify({folder: ask.folder})
    });
    setUndo(result.undo);
    ask.busy = false;
    archiveAsk = null;
    ids.archiveDialog.close();
    if (ask.verb === 'unarchive' && archiveSelected === ask.folder) closeArchive();
    await refresh();
    loadArchives();
    const warnings = result.link_check && !result.link_check.ok ? ['The link check of the brain reported problems: ask your agent to look at them.'] : [];
    showToast(`${ask.verb === 'archive' ? 'Archived' : 'Unarchived'} ${ask.label}`, {undo: true, warnings});
  } catch (error) {
    ask.busy = false;
    ids.archiveConfirm.removeAttribute('aria-busy');
    if (archiveAsk === ask) showArchiveRefusal(error);
  }
}
