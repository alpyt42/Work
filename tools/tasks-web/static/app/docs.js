'use strict';

// ---------- Documents: Docs and Search ----------
function docFoldChar(char) {
  let folded = docFoldCache.get(char);
  if (folded === undefined) {
    folded = char.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/ß/g, 'ss').replace(/\p{M}/gu, '');
    docFoldCache.set(char, folded);
  }
  return folded;
}
// Same normalisation as the server (accents, case, whitespace runs); starts/ends map each folded unit back to the source text.
function docFoldMap(text) {
  let folded = '';
  const starts = [];
  const ends = [];
  let spaced = false;
  for (let index = 0; index < text.length;) {
    const char = String.fromCodePoint(text.codePointAt(index));
    const next = index + char.length;
    const piece = docFoldChar(char);
    if (piece) {
      if (/^\s+$/u.test(piece)) {
        if (!spaced) { folded += ' '; starts.push(index); ends.push(next); }
        spaced = true;
      } else {
        spaced = false;
        for (let unit = 0; unit < piece.length; unit += 1) {
          folded += piece[unit];
          starts.push(index);
          ends.push(next);
        }
      }
    }
    index = next;
  }
  return {folded, starts, ends};
}
function docFindRanges(text, terms) {
  if (!terms.length || !text) return [];
  const {folded, starts, ends} = docFoldMap(text);
  const found = [];
  for (const term of terms) {
    for (let at = folded.indexOf(term); at !== -1; at = folded.indexOf(term, at + term.length)) {
      found.push([starts[at], ends[at + term.length - 1]]);
    }
  }
  found.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  const merged = [];
  for (const range of found) {
    const last = merged[merged.length - 1];
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([range[0], range[1]]);
  }
  return merged;
}
function docMarked(text, ranges) {
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  for (const [start, end] of ranges) {
    if (start > cursor) fragment.append(text.slice(cursor, start));
    fragment.append(element('mark', '', text.slice(start, end)));
    cursor = end;
  }
  if (cursor < text.length) fragment.append(text.slice(cursor));
  return fragment;
}
function docSnippetNode(snippet) {
  const chars = Array.from(snippet.text);
  const node = element('span', 'doc-item-snippet');
  let cursor = 0;
  for (const [start, end] of snippet.ranges) {
    if (start < cursor || end > chars.length) continue;
    if (start > cursor) node.append(chars.slice(cursor, start).join(''));
    node.append(element('mark', '', chars.slice(start, end).join('')));
    cursor = end;
  }
  if (cursor < chars.length) node.append(chars.slice(cursor).join(''));
  return node;
}
function docShortPath(id) {
  return id.replace(/^projects\//, '').replace(/^clients\//, '');
}
function setDocStatus(message, failed = false) {
  ids.docStatus.textContent = message;
  ids.docStatus.className = failed ? 'doc-status doc-status-error' : 'doc-status';
}
// Where the documents come from: "Inbox" or "Outside projects" of the chip, else the sidebar project (a client prefix is filtered here).
function docProjectParam() {
  if (ids.docProject.value) return ids.docProject.value;
  return snapshot.registers.some(register => register.path === projectScope) ? projectScope : '';
}
function docScopeMatch(item) {
  const place = ids.docProject.value;
  if (place === INBOX_REGISTER) return item.register === INBOX_REGISTER;
  if (place === 'none') return !item.register;
  return !projectScope || (Boolean(item.register) && item.register !== INBOX_REGISTER && inScope(item.register));
}
function docItem(item, searching) {
  const li = element('li');
  const button = element('button', 'doc-item');
  button.type = 'button';
  button.dataset.docId = item.id;
  button.setAttribute('aria-pressed', String(item.id === docSelectedId));
  const title = element('span', 'doc-item-title');
  if (searching) title.append(docMarked(item.title, docFindRanges(item.title, docTerms)));
  else title.textContent = item.title;
  const meta = element('span', 'doc-item-meta');
  if (DOC_TYPE_LABELS[item.type]) meta.append(element('span', 'doc-item-type', DOC_TYPE_LABELS[item.type]));
  meta.append(element('span', '', item.project || 'Outside projects'));
  if (item.date) meta.append(element('span', 'doc-item-date', formatDay(item.date)));
  button.append(title, meta);
  if (searching) {
    const path = element('span', 'doc-item-path');
    path.append(docMarked(docShortPath(item.id), docFindRanges(docShortPath(item.id), docTerms)));
    button.append(path);
    for (const snippet of item.snippets || []) button.append(docSnippetNode(snippet));
  } else if (item.excerpt) button.append(element('span', 'doc-item-excerpt', item.excerpt));
  button.addEventListener('click', () => openDoc(item.id, {nav: 'root', terms: searching ? docTerms : []}));
  li.append(button);
  return li;
}
function docEmpty(heading, message) {
  const box = element('div', 'empty-state');
  box.append(element('h2', '', heading), element('p', '', message));
  return box;
}
// The words of the query, folded like the server folds them: whitespace-separated words or "quoted phrases", all required, two characters at least.
function searchTerms(query) {
  const terms = [];
  for (const [, quoted, bare] of query.matchAll(/"([^"]*)"|([^\s"]+)/g)) {
    const term = docFoldMap(quoted ?? bare).folded.trim();
    if (term.length >= 2 && !terms.includes(term)) terms.push(term);
  }
  return terms;
}
function actionMatches(action, terms) {
  const text = docFoldMap(actionSearchText(action)).folded;
  return terms.every(term => text.includes(term));
}
const SEARCH_ACTION_LIMIT = 50;
// An action of the results: a click opens its detail panel. Closed actions are shown too, with their state.
function searchActionItem(action, terms) {
  const li = element('li');
  const button = element('button', `doc-item doc-action${closed(action) ? ' is-closed' : ''}${action.state === '-' ? ' is-cancelled' : ''}`);
  button.type = 'button';
  button.dataset.actionId = action.id;
  const title = element('span', 'doc-item-title');
  const text = element('span', 'doc-action-text');
  text.append(docMarked(action.title, docFindRanges(action.title, terms)));
  title.append(statusIcon(action.state), text);
  const meta = element('span', 'doc-item-meta');
  meta.append(element('span', 'doc-item-id', action.id), element('span', '', action.project), element('span', '', statusLabel(action.state)));
  if (action.due) meta.append(dueNode(action));
  button.append(title, meta);
  button.addEventListener('click', () => {
    selectAction(action.id, {focus: false, scroll: false});
    openEditor(action);
  });
  li.append(button);
  return li;
}
function searchHead(title, count) {
  const head = element('h2', 'doc-list-heading search-head');
  head.append(element('span', '', title), element('span', 'section-count', count));
  return head;
}
function searchNone(message, failed = false) { return element('p', failed ? 'search-none search-error' : 'search-none', message); }
// The results page: the actions that match every word (open and closed), then the documents the server found.
function renderSearchResults() {
  const terms = searchTerms(ids.searchInput.value);
  if (!terms.length) {
    ids.resultCount.textContent = '';
    ids.docList.replaceChildren(docEmpty('Nothing to search yet.', 'Type words of two characters or more, or "an exact phrase".'));
    return;
  }
  const type = ids.docType.value; // a type of document chosen: the actions, which have none, are left out
  const actions = type ? [] : sortActions(snapshot.actions.filter(action => docScopeMatch(action) && actionMatches(action, terms)));
  const docs = docResults.filter(docScopeMatch);
  if (type) {
    const docSection = element('section', 'search-section');
    const label = ids.docType.selectedOptions[0]?.textContent || DOC_TYPE_LABELS[type] || type;
    docSection.append(searchHead(label, docPending || docError ? '' : docTotal > docs.length ? `${docs.length} shown of ${docTotal}` : String(docTotal)));
    if (docError) docSection.append(searchNone(`Search failed: ${docError}`, true));
    else if (docs.length) {
      const list = element('ul', 'doc-items');
      list.append(...docs.map(item => docItem(item, true)));
      docSection.append(list);
    } else if (!docPending) {
      const others = Object.entries(docTypes).filter(([kind]) => kind !== type).reduce((sum, [, count]) => sum + count, 0);
      docSection.append(searchNone(`No document of this type contains these words.${others ? ` ${plural(others, 'document')} of other types do: choose All types.` : ''}`));
    }
    ids.resultCount.textContent = docPending || docError ? '' : plural(docTotal, 'document');
    ids.docList.replaceChildren(docSection);
    return;
  }
  const actionSection = element('section', 'search-section');
  actionSection.append(searchHead('Actions', String(actions.length)));
  if (actions.length) {
    const list = element('ul', 'doc-items');
    list.append(...actions.slice(0, SEARCH_ACTION_LIMIT).map(action => searchActionItem(action, terms)));
    actionSection.append(list);
    if (actions.length > SEARCH_ACTION_LIMIT) actionSection.append(searchNone(`${plural(actions.length - SEARCH_ACTION_LIMIT, 'more action')}: add a word to narrow the search.`));
  } else actionSection.append(searchNone('No action contains these words.'));
  const docSection = element('section', 'search-section');
  docSection.append(searchHead('Documents', docPending || docError ? '' : docTotal > docs.length ? `${docs.length} shown of ${docTotal}` : String(docTotal)));
  if (docError) docSection.append(searchNone(`Search failed: ${docError}`, true));
  else if (docs.length) {
    const list = element('ul', 'doc-items');
    list.append(...docs.map(item => docItem(item, true)));
    docSection.append(list);
  } else if (!docPending) docSection.append(searchNone('No document contains these words.'));
  ids.resultCount.textContent = `${plural(actions.length, 'action')}${docPending || docError ? '' : `, ${plural(docTotal, 'document')}`}`;
  ids.docList.replaceChildren(actionSection, docSection);
}
function renderDocList() {
  const focused = ids.docList.contains(document.activeElement) ? document.activeElement.dataset.docId : null;
  const filtering = Boolean(projectScope || ids.docProject.value);
  if (view === 'docs') {
    if (!notesLoaded) { ids.docList.replaceChildren(); return; }
    const type = ids.docType.value;
    const items = docsData.filter(item => docScopeMatch(item) && (!type || item.type === type));
    const noun = type === 'note' ? 'note' : 'document';
    ids.resultCount.textContent = plural(items.length, noun);
    if (!items.length) {
      // The hint to create a note stays where it can help: with nothing filtered, or on the notes themselves.
      const hint = filtering || (type && type !== 'note') ? `No ${noun}s for this filter.` : 'Create a note: it is saved in the chosen project or in the Inbox.';
      ids.docList.replaceChildren(docEmpty(`No ${noun}s here.`, hint));
      return;
    }
    const list = element('ul', 'doc-items');
    list.append(...items.map(item => docItem(item, false)));
    ids.docList.replaceChildren(list);
  } else renderSearchResults();
  if (focused) ids.docList.querySelector(`.doc-item[data-doc-id="${CSS.escape(focused)}"]`)?.focus();
}
function renderDocsView() { renderDocList(); }
function markDocSelection() {
  for (const button of ids.docList.querySelectorAll('.doc-item[data-doc-id]')) {
    button.setAttribute('aria-pressed', String(button.dataset.docId === docSelectedId));
  }
}
async function loadNotes() {
  const requestId = ++notesRequest;
  if (!notesLoaded && view === 'docs') setDocStatus('Loading…');
  try {
    const data = await request('/api/docs/list');
    if (requestId !== notesRequest) return;
    docsData = nameDocs(data.docs);
    notesLoaded = true;
    if (view === 'docs') setDocStatus('');
    if (isDocsView()) renderDocsView();
  } catch (error) {
    if (requestId !== notesRequest || error.stale || view !== 'docs') return;
    setDocStatus(`Failed: ${error.message}`, true);
  }
}
// The global search. The query lives in the header field, whatever the view: a query takes the page to the results (the view it left is
// remembered), an empty field or Esc brings it back. The actions are matched here at once, the documents come from the server.
function resetSearchResults() {
  docResults = [];
  docTotal = 0;
  docTruncated = false;
  docTerms = [];
  docTypes = {};
  docError = '';
  docPending = false;
}
async function runDocSearch() {
  if (view === 'archives') { runArchiveSearch(); return; } // in Archives the field searches the archives alone
  clearTimeout(docTimer);
  const query = ids.searchInput.value.trim();
  const requestId = ++docSearchRequest;
  docError = '';
  if (!query) {
    resetSearchResults();
    setDocStatus('');
    if (view === 'search') leaveSearch();
    return;
  }
  if (view !== 'search') {
    searchReturn = view;
    setView('search', false); // the page it opens runs the search
    return;
  }
  docPending = true;
  setDocStatus('Searching…');
  renderDocsView();
  try {
    const params = {q: query, project: docProjectParam()};
    if (ids.docType.value) params.type = ids.docType.value;
    const data = await request(`/api/search?${new URLSearchParams(params)}`);
    if (requestId !== docSearchRequest) return;
    docResults = nameDocs(data.results);
    docTotal = data.total;
    docTruncated = data.truncated;
    docTerms = data.terms;
    docTypes = data.types || {};
    setDocStatus(data.truncated ? `The ${data.results.length} best documents are shown.` : '');
  } catch (error) {
    if (requestId !== docSearchRequest || error.stale) return;
    docResults = [];
    docTotal = 0;
    docTerms = [];
    docError = error.message;
    setDocStatus('');
  }
  docPending = false;
  if (view === 'search') renderDocsView();
}
function scheduleDocSearch() {
  clearTimeout(docTimer);
  docTimer = setTimeout(runDocSearch, 200);
}
function leaveSearch() {
  setView(VIEWS.includes(searchReturn) && searchReturn !== 'search' ? searchReturn : 'today');
}
// The lists of the documents views after a filter change.
function refreshDocLists() {
  if (view === 'search') runDocSearch();
  else loadNotes();
  renderDocsView();
}
function setDocError(message) {
  ids.docPaneError.textContent = message;
  ids.docPaneError.hidden = !message;
}
function docDirty() {
  return docEditing && docNote !== null && ids.docEditor.value !== docNote.content;
}
function renderDocPane() {
  const doc = docCurrent;
  ids.docsView.classList.toggle('has-doc', Boolean(doc));
  ids.docBack.hidden = !docHistory.length;
  ids.docPaneEmpty.hidden = Boolean(doc);
  ids.docArticle.hidden = !doc || docEditing;
  ids.docEditor.hidden = !doc || !docEditing;
  ids.docEditorToolbar.hidden = ids.docEditor.hidden;
  ids.docEdit.hidden = !doc || !doc.note || docEditing;
  ids.docDelete.hidden = !doc || !doc.deletable || docEditing;
  ids.docCancel.hidden = !doc || !docEditing;
  ids.docSave.hidden = !doc || !docEditing;
  ids.docSave.disabled = docSaving;
  ids.docCancel.disabled = docSaving;
  ids.docEditor.disabled = docSaving;
  ids.docEditorToolbar.inert = docSaving;
  ids.docPaneMeta.hidden = !doc;
  ids.docPanePath.hidden = !doc;
  if (!doc) {
    ids.docPaneTitle.textContent = 'Document';
    return;
  }
  const listed = docsData.find(item => item.id === doc.id);
  ids.docPaneTitle.textContent = doc.title;
  ids.docPaneMeta.replaceChildren(element('span', '', doc.project || 'Outside projects'), ...(listed?.date ? [element('span', 'doc-item-date', formatDay(listed.date))] : []));
  ids.docPanePath.textContent = doc.id;
  setupTaskBoxes();
}
function scrollDocTo(node, center) {
  const box = ids.docArticle;
  if (box.scrollHeight > box.clientHeight + 1) {
    const offset = node.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    box.scrollTo({top: Math.max(0, offset - (center ? box.clientHeight / 3 : 8))});
  } else node.scrollIntoView({block: center ? 'center' : 'start'});
}
function scrollDocAnchor(anchor) {
  const target = [...ids.docArticle.querySelectorAll('[id]')].find(node => node.id === anchor);
  if (target) scrollDocTo(target, false);
  return Boolean(target);
}
function highlightDocArticle(terms) {
  if (!terms.length) return 0;
  const walker = document.createTreeWalker(ids.docArticle, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  let count = 0;
  for (const node of nodes) {
    if (count >= DOC_MARK_CAP) break;
    const text = node.nodeValue;
    const ranges = docFindRanges(text, terms).slice(0, DOC_MARK_CAP - count);
    if (!ranges.length) continue;
    count += ranges.length;
    node.replaceWith(docMarked(text, ranges));
  }
  return count;
}
function showDocArticle(html, terms, anchor, keepScroll) {
  const scroll = ids.docArticle.scrollTop;
  const template = document.createElement('template');
  template.innerHTML = html;
  ids.docArticle.replaceChildren(template.content);
  highlightDocArticle(terms);
  ids.docArticle.scrollTop = keepScroll ? scroll : 0;
  setupTaskBoxes();
  if (keepScroll) return;
  if (anchor && scrollDocAnchor(anchor)) return;
  const first = ids.docArticle.querySelector('mark');
  if (first) scrollDocTo(first, true);
}
// Task-list boxes: the server renders them disabled; only a working note that is not being edited lets them be ticked.
let taskBusy = false;
const taskBoxesAllowed = () => Boolean(docCurrent?.note) && !docEditing;
const taskBoxesEnabled = () => taskBoxesAllowed() && !taskBusy;
function taskBoxText(box) {
  const item = box.closest('li');
  let text = '';
  for (const node of item ? item.childNodes : []) {
    if (node.nodeType === Node.ELEMENT_NODE && /^(UL|OL)$/.test(node.tagName)) continue;
    text += node.textContent;
  }
  return text.replace(/\s+/g, ' ').trim().slice(0, 120);
}
function setupTaskBoxes() {
  const allowed = taskBoxesEnabled();
  for (const box of ids.docArticle.querySelectorAll('input.task-box')) {
    box.disabled = !allowed;
    if (taskBoxesAllowed()) box.removeAttribute('title');
    else box.title = 'This document is read-only here.';
    const label = taskBoxText(box);
    if (label) box.setAttribute('aria-label', label);
  }
}
function setTaskBoxesDisabled(disabled) {
  for (const box of ids.docArticle.querySelectorAll('input.task-box')) box.disabled = disabled;
}
async function toggleTaskBox(box) {
  const wanted = box.checked;
  if (!taskBoxesAllowed() || taskBusy) { box.checked = !wanted; return; }
  const doc = docCurrent;
  taskBusy = true;
  setTaskBoxesDisabled(true);
  setDocError('');
  try {
    const result = await request('/api/notes/task', {
      method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({id: doc.id, version: doc.version, line: Number(box.dataset.line), done: wanted})
    });
    setUndo(result.undo);
    showToast(wanted ? 'Box ticked' : 'Box unticked', {undo: true});
    // Reload in place only if the person is still on that note (another document may have been opened meanwhile).
    await Promise.all([loadNotes(), docCurrent?.id === doc.id ? openDoc(doc.id, {nav: 'keep'}) : null]);
  } catch (error) {
    box.checked = !wanted;
    if (docCurrent?.id !== doc.id) return;
    if (error.status === 409) await openDoc(doc.id, {nav: 'keep'}); // the reload clears the error line: set it after
    setDocError(error.status === 409 ? 'The note changed on disk: it has been reloaded. Tick the box again if needed.' : error.message);
  } finally {
    taskBusy = false;
    if (ids.docArticle.contains(box) || ids.docArticle.querySelector('input.task-box')) setupTaskBoxes();
  }
}
// nav: 'root' (picked from the list or created), 'link' (internal link, pushes history), 'back', 'keep' (reload in place).
async function openDoc(id, {nav = 'root', terms = [], anchor = ''} = {}) {
  if (nav !== 'keep' && docDirty() && !confirm('Discard the unsaved changes to this note?')) return;
  if (nav === 'root') docHistory = [];
  else if (nav === 'link' && docCurrent) docHistory.push({id: docCurrent.id, terms: docMarks});
  else if (nav === 'back') docHistory.pop();
  const quiet = nav === 'keep' && docCurrent !== null;
  if (nav !== 'keep') { docEditing = false; docNote = null; docMarks = terms; }
  docSelectedId = id;
  const requestId = ++docRenderRequest;
  setDocError('');
  if (!quiet) {
    docCurrent = null;
    ids.docPaneEmpty.textContent = 'Loading the document…';
    renderDocPane();
  }
  markDocSelection();
  try {
    const doc = await request(`/api/docs/render?id=${encodeURIComponent(id)}`);
    if (requestId !== docRenderRequest) return;
    doc.project = displayProject(doc.project);
    docCurrent = doc;
    renderDocPane();
    showDocArticle(doc.html, docMarks, anchor, quiet);
  } catch (error) {
    if (requestId !== docRenderRequest || error.stale) return;
    if (error.status === 404) {
      docSelectedId = null;
      docCurrent = null;
      docEditing = false;
      docNote = null;
      ids.docPaneEmpty.textContent = 'This document no longer exists.';
    } else if (!quiet) {
      ids.docPaneEmpty.textContent = 'Document unavailable.';
      setDocError(error.message);
    } else setDocError(error.message);
    renderDocPane();
    markDocSelection();
  }
}
function docGoBack() {
  const entry = docHistory[docHistory.length - 1];
  if (entry) openDoc(entry.id, {nav: 'back', terms: entry.terms});
}
async function startDocEdit() {
  if (!docCurrent || !docCurrent.note || docEditing) return;
  const id = docCurrent.id;
  ids.docEdit.disabled = true;
  setDocError('');
  try {
    const note = await request(`/api/notes/content?id=${encodeURIComponent(id)}`);
    if (!docCurrent || docCurrent.id !== id) return;
    docNote = note;
    docEditing = true;
    ids.docEditor.value = note.content;
    renderDocPane();
    ids.docEditor.focus();
  } catch (error) {
    if (!error.stale) setDocError(error.status === 404 ? 'This note no longer exists.' : error.message);
  } finally {
    ids.docEdit.disabled = false;
  }
}
function cancelDocEdit() {
  if (docSaving) return;
  if (docDirty() && !confirm('Discard the unsaved changes to this note?')) return;
  docEditing = false;
  docNote = null;
  setDocError('');
  renderDocPane();
  ids.docEdit.focus();
}
async function saveDoc() {
  if (!docCurrent || !docEditing || docNote === null || docSaving) return;
  docSaving = true;
  setDocError('');
  renderDocPane();
  try {
    const result = await request('/api/notes', {
      method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({id: docNote.id, version: docNote.version, content: ids.docEditor.value})
    });
    setUndo(result.undo);
    docEditing = false;
    docNote = null;
    docSaving = false;
    showToast('Note saved', {undo: true});
    await Promise.all([loadNotes(), openDoc(docCurrent.id, {nav: 'keep'})]);
    if (view === 'search') runDocSearch();
    ids.docEdit.focus();
  } catch (error) {
    setDocError(error.status === 409
      ? `${error.message} Your changes stay in the field: copy them, then cancel and reopen the note.`
      : error.message);
  } finally {
    docSaving = false;
    renderDocPane();
  }
}
// ---------- Deleting a note ----------
// Only a working note has a Delete button (the server says so: `deletable`). The dialog asks first; when other pages still link to the note it
// lists them instead (each opens in the reader) and offers no Delete, so that nothing breaks the next save. The toast offers Undo.
let noteToDelete = null; // {id, version, title} of the note the open dialog is about
function showDeleteNoteDialog(title, count, pages, error = '') {
  const linked = count > 0;
  ids.deleteNoteHeading.textContent = `Delete the note “${title}”?`;
  ids.deleteNoteText.textContent = linked
    ? `This note is linked from ${plural(count, 'page')}. Remove those links first, or ask your agent.`
    : 'The note is removed from this brain. You can undo it right after.';
  ids.deleteNoteLinks.hidden = !linked;
  ids.deleteNoteLinks.replaceChildren(...pages.map(page => {
    const item = element('li');
    const open = element('button', 'link-button', page.title);
    open.type = 'button';
    open.title = `Open ${page.id}`;
    open.addEventListener('click', () => openLinkingPage(page.id));
    item.append(open, element('span', 'delete-note-path', page.id));
    return item;
  }));
  if (count > pages.length) ids.deleteNoteLinks.append(element('li', 'delete-note-more', `and ${plural(count - pages.length, 'more page')}`));
  ids.deleteNoteError.textContent = error;
  ids.deleteNoteError.hidden = !error;
  ids.deleteNoteConfirm.hidden = linked;
  ids.deleteNoteConfirm.disabled = false;
  ids.deleteNoteCancel.textContent = linked ? 'Close' : 'Cancel';
}
function openLinkingPage(id) {
  ids.deleteNoteDialog.close();
  if (view !== 'docs' && view !== 'search') setView('docs');
  openDoc(id, {nav: 'root'});
}
async function askDeleteNote() {
  const doc = docCurrent;
  if (!doc || !doc.deletable || docEditing || docSaving || ids.docDelete.getAttribute('aria-busy') === 'true') return;
  ids.docDelete.setAttribute('aria-busy', 'true'); // not `disabled`: a disabled button would lose the focus the dialog gives back to it
  setDocError('');
  try {
    const info = await request(`/api/notes/backlinks?id=${encodeURIComponent(doc.id)}`);
    if (!docCurrent || docCurrent.id !== doc.id) return;
    noteToDelete = {id: doc.id, version: doc.version, title: info.title};
    showDeleteNoteDialog(info.title, info.count, info.pages);
    ids.deleteNoteDialog.showModal();
  } catch (error) {
    if (!error.stale) setDocError(error.status === 404 ? 'This note no longer exists.' : error.message);
  } finally {
    ids.docDelete.removeAttribute('aria-busy');
  }
}
// The pane after the note is gone: nothing selected, the lists read again (and with them the number next to Sync).
function clearDocPane() {
  docRenderRequest += 1;
  docSelectedId = null;
  docCurrent = null;
  docHistory = [];
  docEditing = false;
  docNote = null;
  ids.docPaneEmpty.textContent = 'Choose a document to read it.';
  setDocError('');
  renderDocPane();
  markDocSelection();
}
async function confirmDeleteNote() {
  const target = noteToDelete;
  if (!target) return;
  ids.deleteNoteConfirm.disabled = true;
  ids.deleteNoteError.hidden = true;
  try {
    const result = await request('/api/notes', {
      method: 'DELETE', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({id: target.id, version: target.version})
    });
    noteToDelete = null;
    setUndo(result.undo);
    ids.deleteNoteDialog.close();
    clearDocPane();
    showToast('Note deleted', {undo: true});
    await refresh();
    await loadNotes(); // the list as it is drawn last: the focus goes to its first note (or, with none left, to New note)
    (ids.docList.querySelector('.doc-item') || ids.newNoteButton).focus();
  } catch (error) {
    const data = error.data || {};
    if (error.status === 409 && Array.isArray(data.backlinks)) showDeleteNoteDialog(target.title, data.count, data.backlinks);
    else if (error.status === 409 || error.status === 404) {
      // The note is not what the person saw (or is gone): say so in the pane, which shows it as it is now.
      ids.deleteNoteDialog.close();
      await openDoc(target.id, {nav: 'keep'});
      setDocError(error.message);
    } else showDeleteNoteDialog(target.title, 0, [], error.message);
  }
}
ids.docDelete.addEventListener('click', askDeleteNote);
ids.deleteNoteConfirm.addEventListener('click', confirmDeleteNote);
ids.deleteNoteDialog.addEventListener('close', () => { noteToDelete = null; });

function refreshDocsView() {
  loadNotes();
  if (view === 'search') runDocSearch();
  else renderDocsView();
  if (docSelectedId && !docEditing && !docSaving) openDoc(docSelectedId, {nav: 'keep'});
}
function newNoteFolder() {
  const register = ids.newNoteProject.value;
  if (register === INBOX_REGISTER) return 'inbox/';
  return register ? register.replace(/state\/actions\.md$/, 'notes/') : '';
}
function updateNewNoteWhere() {
  ids.newNoteWhere.textContent = `File created: ${newNoteFolder()}YYYY-MM-DD-title.md`;
}
function openNewNote() {
  closePopover(false);
  ids.newNoteProject.replaceChildren(new Option('Inbox (to triage)', INBOX_REGISTER), ...snapshot.registers.map(register => new Option(register.label, register.path)));
  const paths = [...ids.newNoteProject.options].map(option => option.value);
  const preferred = ids.docProject.value === INBOX_REGISTER ? INBOX_REGISTER : projectScope;
  ids.newNoteProject.value = paths.includes(preferred) ? preferred : INBOX_REGISTER;
  ids.newNoteTitle.value = '';
  ids.newNoteContent.value = '';
  newNoteBar.closeMenu(false);
  ids.newNoteError.hidden = true;
  ids.saveNewNote.disabled = false;
  updateNewNoteWhere();
  ids.newNoteDialog.showModal();
  ids.newNoteTitle.focus();
}
async function createNote(event) {
  event.preventDefault();
  if (!ids.newNoteForm.reportValidity()) return;
  ids.saveNewNote.disabled = true;
  ids.newNoteError.hidden = true;
  try {
    const result = await request('/api/notes', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({title: ids.newNoteTitle.value.trim(), register: ids.newNoteProject.value, content: ids.newNoteContent.value})
    });
    setUndo(result.undo);
    ids.newNoteDialog.close();
    if (docDirty() && !confirm('Discard the unsaved changes to the open document?')) {
      if (isDocsView()) await loadNotes();
      showToast('Note created', {undo: true});
      return;
    }
    docEditing = false;
    docNote = null;
    docSelectedId = null;
    docCurrent = null;
    if (!docScopeMatch({register: ids.newNoteProject.value})) {
      projectScope = '';
      ids.docProject.value = '';
      renderProjectNav();
    }
    if (ids.docType.value && ids.docType.value !== 'note') ids.docType.value = ''; // the new note must show in the list
    setView('docs');
    showToast('Note created', {undo: true});
    await openDoc(result.id, {nav: 'root'});
  } catch (error) {
    ids.newNoteError.textContent = error.message;
    ids.newNoteError.hidden = false;
  } finally {
    ids.saveNewNote.disabled = false;
  }
}
