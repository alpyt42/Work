'use strict';

// ---------- Editor: the detail panel (create and edit) ----------
const NEW_GROUP = '__new';
let editorAction = null;
let editorInitial = '';
let editorReturnFocus = null;
// Autosave (an existing action): a change is sent shortly after it is committed; one write at a time, the newest job replaces a queued one.
const AUTOSAVE_DELAY = 400;
let autosaveTimer = null;
let autosaveBusy = false;
let autosaveNext = null;
let autosavePromise = null;
let editorAdopt = null; // the id whose fresh line the next refresh adopts in place (no reopen: a note being typed survives)
function groupChoice() {
  return ids.editorGroup.value === NEW_GROUP ? {fresh: true, text: ids.editorGroupNew.value} : {slug: ids.editorGroup.value};
}
function groupValue() {
  const choice = groupChoice();
  return choice.fresh ? groupSlug(choice.text) : choice.slug;
}
// keep: a current group missing from the project's list stays as a selected option (opening); otherwise (project change) it comes back as a new group to type.
function fillGroupOptions(choice = groupChoice(), keep = false) {
  const register = snapshot.registers.find(item => item.path === ids.editorProject.value);
  const slugs = new Set(register?.groups || []);
  if (keep && choice.slug) slugs.add(choice.slug);
  if (choice.fresh && slugs.has(groupSlug(choice.text))) choice = {slug: groupSlug(choice.text)};
  const fresh = Boolean(choice.fresh || (choice.slug && !slugs.has(choice.slug)));
  const sorted = [...slugs].sort((a, b) => groupLabel(a).localeCompare(groupLabel(b), LOCALE) || a.localeCompare(b));
  ids.editorGroup.replaceChildren(new Option('No group', ''), ...sorted.map(slug => new Option(groupLabel(slug), slug)), new Option('New group…', NEW_GROUP));
  ids.editorGroup.value = fresh ? NEW_GROUP : choice.slug || '';
  ids.editorGroupNew.value = choice.fresh ? choice.text : fresh ? groupLabel(choice.slug) : '';
  showGroupField();
}
function showGroupField(focus = false) {
  const choice = groupChoice();
  const slug = groupValue();
  const register = snapshot.registers.find(item => item.path === ids.editorProject.value);
  ids.editorGroupNewLabel.hidden = !choice.fresh;
  ids.editorGroupHint.textContent = !choice.fresh ? (slug ? `Saved as: ${slug}` : 'Optional: groups related actions together.') :
    !choice.text.trim() ? 'Enter a label: it will be converted to an identifier.' :
    !slug ? 'No letter or digit: no group.' :
    `${(register?.groups || []).includes(slug) ? 'Existing group' : 'New group'}: ${slug}`;
  if (focus && choice.fresh) ids.editorGroupNew.focus();
}
function formAction() {
  return {
    title: ids.editorActionTitle.value.replace(/[\r\n]+/g, ' ').trim(), owner: ids.editorOwner.value.trim(),
    state: ids.editorState.value, priority: ids.editorPriority.value,
    due: ids.editorDue.value, scheduled: ids.editorScheduled.value, group: groupValue()
  };
}
function editorOpen() { return !ids.editor.hidden; }
function editorSignature() { return JSON.stringify([ids.editorProject.value, formAction()]); }
function editorDirty() { return editorOpen() && editorSignature() !== editorInitial; }
function unsentChanges() { return Boolean(editorAction) && editorDirty(); }
function setSaveState(text) { ids.editorSaveState.textContent = text; }
function updateSaveState() {
  if (!editorOpen() || !editorAction) { setSaveState(''); return; }
  if (autosaveBusy) setSaveState('Saving…');
  else if (!ids.editorError.hidden) setSaveState('Not saved');
  else if (editorDirty()) setSaveState('Unsaved changes');
  else setSaveState(ids.editorSaveState.dataset.saved ? 'Saved' : '');
}
function updateEditorButtons() {
  if (editorAction) updateSaveState();
  else ids.saveEditor.disabled = false;
}
function scheduleAutosave(delay = AUTOSAVE_DELAY) {
  if (!editorOpen() || !editorAction) return;
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  if (editorDirty()) autosaveTimer = setTimeout(flushAutosave, delay);
  updateSaveState();
}
// Sends what the panel holds now (a change in flight finishes first). Returns a promise to await, or null when there is nothing to send.
function flushAutosave() {
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  if (!editorOpen() || !editorAction || !editorDirty()) return autosavePromise;
  const action = formAction();
  if (action.title === '') {
    ids.editorError.textContent = 'The title cannot be empty: this change is not saved.';
    ids.editorError.hidden = false;
    setSaveState('Not saved');
    return autosavePromise;
  }
  autosaveNext = {id: editorAction.id, action, signature: editorSignature()};
  if (!autosaveBusy) autosavePromise = runAutosave();
  return autosavePromise;
}
async function runAutosave() {
  autosaveBusy = true;
  try {
    while (autosaveNext) {
      const job = autosaveNext;
      autosaveNext = null;
      const version = editorAction?.id === job.id ? ids.editor.dataset.version : findAction(job.id)?.version;
      setSaveState('Saving…');
      try {
        const result = await request(`/api/actions/${encodeURIComponent(job.id)}`, {
          method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
          body: JSON.stringify({version, action: job.action})
        });
        setUndo(result.undo);
        showToast('Action updated', {undo: true, warnings: result.warnings || []});
        if (editorOpen() && editorAction?.id === job.id) {
          editorInitial = job.signature;
          editorAdopt = job.id; // the refresh below hands the panel its fresh version
          ids.editorError.hidden = true;
          ids.editorSaveState.dataset.saved = '1';
        }
        await refresh();
      } catch (error) {
        if (editorOpen() && editorAction?.id === job.id) {
          ids.editorError.textContent = error.status === 409
            ? 'The register changed since you opened this action: this change is not saved. Close the panel and reopen the action.'
            : error.message;
          ids.editorError.hidden = false;
          if (autosaveNext?.id === job.id) autosaveNext = null; // no automatic retry
        } else showError(`${job.id} not saved: ${error.message}`);
      }
    }
  } finally {
    autosaveBusy = false;
    updateSaveState();
  }
}
// The open panel, an existing action: the id whose later highlights follow.
function markOpenAction() {
  const id = editorOpen() && editorAction ? editorAction.id : null;
  for (const item of ids.todayView.querySelectorAll('.has-open')) item.classList.remove('has-open');
  for (const button of ids.todayView.querySelectorAll('.prio-id[data-action-id]')) {
    const open = id !== null && button.dataset.actionId === id;
    button.classList.toggle('is-open', open);
    if (open) button.closest('li')?.classList.add('has-open');
  }
  for (const button of document.querySelectorAll('.doc-action[data-action-id]')) button.classList.toggle('is-open', id !== null && button.dataset.actionId === id);
}
function sizeTitleField() {
  ids.editorActionTitle.style.height = 'auto';
  ids.editorActionTitle.style.height = `${Math.min(ids.editorActionTitle.scrollHeight + 2, 320)}px`;
}
// The title wraps again when its width changes (the panel's handle, the window, the fonts once loaded): its height follows, so that
// no line is cut. Only a change of width counts, not the height this sets.
let titleFieldWidth = 0;
new ResizeObserver(([entry]) => {
  if (entry.contentRect.width === titleFieldWidth) return;
  titleFieldWidth = entry.contentRect.width;
  if (titleFieldWidth) sizeTitleField();
}).observe(ids.editorActionTitle);
document.fonts?.ready.then(() => { if (!ids.editor.hidden) sizeTitleField(); });
function renderStamps(action) {
  if (!action) { ids.editorStamps.hidden = true; ids.editorStamps.replaceChildren(); return; }
  const pairs = [
    ['Created', action.created_at ? formatStamp(action.created_at) : 'Not set'],
    ['Updated', action.updated_at ? formatStamp(action.updated_at) : 'Not set']
  ];
  if (closed(action)) pairs.push(['Closed', action.done ? formatDay(action.done) : 'Not set']);
  ids.editorStamps.replaceChildren(...pairs.flatMap(([label, value]) => [element('dt', '', label), element('dd', '', value)]));
  ids.editorStamps.hidden = false;
}
// preset (creation only): {register, group (slug), state}. focus: 'auto' (title when creating, heading when editing), 'title', 'none'.
function openEditor(action = null, preset = null, {focus = 'auto'} = {}) {
  const same = action && editorAction && editorAction.id === action.id;
  if (unsentChanges()) {
    flushAutosave(); // captures the open action's values before the panel moves on
    if (same) return true;
  } else if (editorDirty() && !same && !confirm('Discard the unsaved changes to this action?')) return false;
  closePopover(false);
  if (!editorOpen()) editorReturnFocus = document.activeElement;
  const historyRequest = ++editorHistoryRequest;
  editorAction = action;
  ids.editor.dataset.actionId = action?.id || '';
  ids.editor.dataset.version = action?.version || '';
  ids.editorTitle.textContent = action ? action.id : 'New action';
  const target = !action && preset?.register && snapshot.registers.find(register => register.path === preset.register);
  ids.editorHint.textContent = action ? action.project : target ? `${target.label}${preset.group ? `, group ${groupLabel(preset.group)}` : ''}${preset.due ? `, due ${formatDay(preset.due)}` : ''}` : '';
  ids.editorProjectField.hidden = Boolean(action);
  ids.editorProject.disabled = Boolean(action);
  ids.editorProject.value = action?.register || preset?.register || defaultRegister();
  ids.editorActionTitle.value = action?.raw_title || '';
  fillGroupOptions({slug: action?.group || (!action && preset?.group) || ''}, true);
  ids.editorHistory.hidden = !action;
  noteState = null;
  noteBusy = false;
  closeNoteForm(false);
  ids.noteInput.value = '';
  updateNoteWords();
  ids.addNoteButton.disabled = true;
  ids.editorHistoryList.replaceChildren(element('li', 'note-empty', 'Loading…'));
  ids.editorHistoryCount.textContent = '';
  ids.editorSubtasks.hidden = !action;
  ids.subtaskInput.value = '';
  ids.subtaskError.hidden = true;
  renderSubtasks({subtasks: []});
  ids.editorOwner.value = action?.owner || snapshot.owner;
  ids.editorState.value = action?.state || (!action && preset?.state) || ' ';
  ids.editorPriority.value = action?.priority || '';
  ids.editorDue.value = action?.due || (!action && preset?.due) || '';
  ids.editorScheduled.value = action?.scheduled || '';
  delete ids.editorSaveState.dataset.saved;
  setSaveState('');
  ids.editorFoot.hidden = Boolean(action); // an existing action saves itself and closes with × or a click outside: no footer
  ids.deleteEditor.hidden = !action;
  renderStamps(action);
  setEditorBusy(false);
  ids.editorError.hidden = true;
  ids.editor.hidden = false;
  ids.app.classList.add('has-panel');  // the list makes room for the panel, or the panel covers the view (app.css)
  ids.editor.setAttribute('aria-label', action ? `Action ${action.id}` : 'New action');
  sizeTitleField();
  editorInitial = editorSignature();
  updateEditorButtons();
  markOpenAction();
  if (focus === 'title' || (focus === 'auto' && !action)) ids.editorActionTitle.focus();
  else if (focus === 'auto') ids.editorTitle.focus({preventScroll: true});
  if (action) {
    loadDetails(action).then(details => {
      if (historyRequest !== editorHistoryRequest || !editorOpen()) return;
      renderDetails(details);
    }).catch(error => {
      if (historyRequest !== editorHistoryRequest || !editorOpen()) return;
      ids.editorHistoryList.replaceChildren(element('li', 'note-empty', `History unavailable: ${error.message}`));
    });
  }
  return true;
}
function closeEditor({force = false, refocus = true} = {}) {
  if (!editorOpen()) return true;
  if (!force && unsentChanges()) {
    flushAutosave();
    if (formAction().title === '') { ids.editorActionTitle.focus(); return false; } // an empty title is not sent: the panel stays, with its message
  } else if (!force && editorDirty() && !confirm('Discard the unsaved changes to this action?')) return false;
  clearTimeout(autosaveTimer);
  autosaveTimer = null;
  const wasEditing = editorAction?.id;
  ids.editor.hidden = true;
  ids.app.classList.remove('has-panel');
  editorHistoryRequest += 1;
  editorAction = null;
  noteState = null;
  setSaveState('');
  markOpenAction();
  if (refocus) {
    const row = wasEditing && rowFor(wasEditing);
    const target = row?.querySelector(ROW_MAIN) || (editorReturnFocus?.isConnected && !ids.editor.contains(editorReturnFocus) ? editorReturnFocus : null);
    (target || ids.resultCount).focus({preventScroll: true});
  }
  editorReturnFocus = null;
  return true;
}
// After a refresh: an unchanged panel follows the register (new version), a vanished action closes it.
function syncEditorAfterRefresh() {
  if (!editorOpen() || !editorAction) return;
  const fresh = findAction(editorAction.id);
  if (!fresh) { closeEditor({force: true, refocus: false}); return; }
  if (editorAdopt && editorAction.id === editorAdopt) {
    editorAction = fresh;
    ids.editor.dataset.version = fresh.version;
    renderStamps(fresh);
    editorAdopt = null;
    updateSaveState();
    return;
  }
  if (fresh.version !== editorAction.version && !editorDirty()) openEditor(fresh, null, {focus: 'none'});
}
// The history, newest first: the register appends, so the last sub-bullet leads and the source closes the list. Only the order
// on screen changes: each note keeps its `index` in the register, which is what a deletion sends.
function renderNotes(details) {
  noteState = {id: details.id, version: details.details_version, notes: details.notes};
  const shown = details.notes.filter(note => !/^-?\s*(created|updated)\s*:/i.test(note.text)).reverse();
  ids.editorHistoryList.replaceChildren();
  if (!shown.length) ids.editorHistoryList.append(element('li', 'note-empty', 'No notes yet.'));
  for (const note of shown) {
    const item = element('li', `note-item${note.deletable ? '' : ' note-source'}`);
    const text = note.text.replace(/^-\s+/, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    const body = element('span', 'note-text');
    const dated = text.match(/^(\d{2}\/\d{2}): ([\s\S]*)$/);
    if (dated) body.append(element('span', 'note-date', dated[1]), dated[2]);
    else body.textContent = text;
    item.append(body);
    if (note.deletable) {
      const button = iconButton('icon-button note-delete', 'Delete the note', ICONS.trash);
      button.addEventListener('click', () => deleteNote(note));
      item.append(button);
    }
    ids.editorHistoryList.append(item);
  }
  const count = shown.filter(note => note.deletable).length;
  ids.editorHistoryCount.textContent = count ? String(count) : '';
  setNoteBusy(false);
}
// The details of the open action: its history and its subtasks, which share one version (the lock of every write to them).
function renderDetails(details) {
  renderNotes(details);
  renderSubtasks(details);
}
// A write to the details (history or subtasks) is in flight: both wait for it, since the next one needs the version it returns.
function setNoteBusy(busy) {
  noteBusy = busy;
  ids.addNoteButton.disabled = busy || !noteState;
  ids.submitNote.disabled = busy || !noteState;
  ids.editorHistoryList.querySelectorAll('.note-delete').forEach(button => { button.disabled = busy; });
  setSubtaskBusy(busy);
}
function showNoteError(error) {
  ids.noteError.textContent = error.status === 409 ? 'The history changed in the register: close and reopen the action to reload it.' : error.message;
  ids.noteError.hidden = false;
}
// Words as the actions tool counts them: separated by spaces, a Markdown link counting as its label.
function wordCount(text) { return text.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').split(/\s+/).filter(Boolean).length; }
const HISTORY_WORDS = 35; // the caps of tools/brain/action.py, which refuses more (and says so)
const SUBTASK_WORDS = 15;
const SUBTASKS_MAX = 10;
// "12/35 words" next to the field, in the danger colour past the cap: the tool would refuse the note.
function wordMeter(node, text, cap) {
  const words = wordCount(text);
  node.textContent = words ? `${words}/${cap} words` : '';
  node.classList.toggle('is-over', words > cap);
  return words;
}
function updateNoteWords() { wordMeter(ids.noteWords, ids.noteInput.value, HISTORY_WORDS); }
function forgetDetails(id, fresh) {
  for (const key of [...detailCache.keys()]) if (key.startsWith(`${id}:`)) detailCache.delete(key);
  detailCache.set(`${id}:${fresh.version}`, Promise.resolve(fresh));
}
function openNoteForm() {
  ids.noteForm.hidden = false;
  ids.addNoteButton.setAttribute('aria-expanded', 'true');
  ids.noteInput.focus();
  ids.noteForm.scrollIntoView({block: 'nearest'});
}
function closeNoteForm(focus = true) {
  ids.noteForm.hidden = true;
  ids.noteError.hidden = true;
  ids.addNoteButton.setAttribute('aria-expanded', 'false');
  if (focus && editorOpen()) ids.addNoteButton.focus();
}
// One write to the details of the open action (`send` returns the refreshed details), then the panel and the lists follow.
// A refusal goes to `onError` (the history's or the subtasks' message line), with the tool's own words for a 400.
async function changeDetails(send, onError) {
  const session = editorHistoryRequest;
  const id = noteState.id;
  setNoteBusy(true);
  ids.noteError.hidden = true;
  ids.subtaskError.hidden = true;
  try {
    const fresh = await send();
    setUndo(fresh.undo);
    forgetDetails(id, fresh);
    if (session !== editorHistoryRequest || !editorOpen()) return null;
    renderDetails(fresh);
    // The action line changed ("updated"): its new version keeps the panel and later saves in step.
    editorAction = {...editorAction, version: fresh.version, updated_at: fresh.updated_at};
    ids.editor.dataset.version = fresh.version;
    renderStamps(editorAction);
    refreshQuietly();
    return fresh;
  } catch (error) {
    if (session === editorHistoryRequest && editorOpen()) {
      setNoteBusy(false);
      onError(error);
    }
    return null;
  }
}
function changeNotes(send) { return changeDetails(send, showNoteError); }
async function submitNote() {
  if (noteBusy || !noteState) return;
  const note = ids.noteInput.value.replace(/\s*[\r\n\u2028\u2029]+\s*/g, ' ').trim();
  if (!note) {
    showNoteError(new Error('Enter a note before adding it.'));
    ids.noteInput.focus();
    return;
  }
  const {id, version} = noteState;
  const fresh = await changeNotes(() => request(`/api/actions/${encodeURIComponent(id)}/notes`, {
    method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
    body: JSON.stringify({details_version: version, note})
  }));
  if (fresh?.unchanged) showNoteError(new Error('This note is already in the history: nothing was added.'));
  else if (fresh) {
    ids.noteInput.value = '';
    updateNoteWords();
  }
  if (editorOpen()) ids.noteInput.focus();
}
async function deleteNote(note) {
  if (noteBusy || !noteState || !confirm('Delete this note from the register?')) return;
  const {id, version} = noteState;
  const fresh = await changeNotes(() => request(`/api/actions/${encodeURIComponent(id)}/notes/${note.index}`, {
    method: 'DELETE', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
    body: JSON.stringify({details_version: version, text: note.text})
  }));
  if (!editorOpen()) return;
  (ids.editorHistoryList.querySelector('.note-delete') || ids.addNoteButton).focus();
}

// ---------- Subtasks (detail panel) ----------
// The checklist of the open action, in the register's order (the owner orders it; a ticked step stays where it is, struck
// through). Tick in place, add, rename, move up or down, delete: each is one write of `action.py subtask` under the details
// version, one undo step, and the answer is the refreshed details.
let subtaskState = []; // the subtasks of the open action, as the last details gave them
let subtaskEditing = -1; // the index being renamed
function renderSubtasks(details) {
  subtaskState = details.subtasks || [];
  subtaskEditing = -1;
  const done = subtaskState.filter(item => item.done).length;
  const total = subtaskState.length;
  ids.editorSubtasksCount.textContent = total ? `${done}/${total}` : '';
  ids.editorSubtasksCount.title = total ? `${done} of ${plural(total, 'subtask')} done` : '';
  ids.editorSubtasksBar.hidden = !total;
  ids.editorSubtasksBar.style.setProperty('--p', total ? done / total : 0);
  renderSubtaskList();
  ids.subtaskForm.hidden = total >= SUBTASKS_MAX;
  updateSubtaskHint();
}
function renderSubtaskList() {
  subtaskEditing = -1;
  ids.editorSubtaskList.replaceChildren(...subtaskState.map(subtaskItem));
  ids.editorSubtaskList.hidden = !subtaskState.length;
  setSubtaskBusy(noteBusy);
}
function subtaskItem(item) {
  const li = element('li', `subtask-item${item.done ? ' is-done' : ''}`);
  li.dataset.index = String(item.index);
  const tick = element('label', 'subtask-tick'); // the box with room around it to hit; the text is its label too
  const box = element('input', 'subtask-check');
  box.type = 'checkbox';
  box.id = `subtask-${item.index}`;
  box.checked = item.done;
  box.addEventListener('change', () => tickSubtask(item, box.checked));
  box.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); box.click(); } }); // not the panel's form
  tick.append(box);
  const text = element('label', 'subtask-text', item.text);
  text.htmlFor = box.id;
  if (item.done_on) text.title = `Done on ${formatDay(item.done_on)}`;
  const tools = element('span', 'subtask-actions');
  const last = subtaskState.length - 1;
  const up = subtaskButton('subtask-up', `Move “${item.text}” up`, ICONS.up, 'Move up', item.index === 0, () => moveSubtask(item, -1));
  const down = subtaskButton('subtask-down', `Move “${item.text}” down`, ICONS.down, 'Move down', item.index === last, () => moveSubtask(item, 1));
  const rename = subtaskButton('subtask-rename-button', `Rename “${item.text}”`, ICONS.edit, 'Rename', false, () => startSubtaskRename(item.index));
  const remove = subtaskButton('subtask-delete', `Delete “${item.text}”`, ICONS.trash, 'Delete (can be undone)', false, () => removeSubtask(item));
  tools.append(up, down, rename, remove);
  li.append(tick, text, tools);
  return li;
}
// `edge`: the first one cannot go up, the last one down; it stays disabled whatever the busy state.
function subtaskButton(className, label, icon, title, edge, onClick) {
  const button = iconButton(`icon-button ${className}`, label, icon, title);
  if (edge) button.dataset.edge = '1';
  button.disabled = edge;
  button.addEventListener('click', onClick);
  return button;
}
function setSubtaskBusy(busy) {
  const off = busy || !noteState;
  ids.subtaskInput.disabled = off;
  ids.submitSubtask.disabled = off;
  for (const control of ids.editorSubtaskList.querySelectorAll('input, button')) control.disabled = off || control.dataset.edge === '1';
}
// The limits are shown before the write: the words of the text being typed, and how many subtasks the action holds.
function updateSubtaskHint(text = subtaskEditing >= 0 ? '' : ids.subtaskInput.value) {
  const total = subtaskState.length;
  const words = wordCount(text);
  ids.subtaskHint.classList.toggle('is-over', words > SUBTASK_WORDS);
  if (total >= SUBTASKS_MAX && subtaskEditing < 0) {
    ids.subtaskHint.textContent = `${SUBTASKS_MAX} subtasks, the most an action holds: split the work into several actions.`;
    return;
  }
  const length = words ? `${words}/${SUBTASK_WORDS} words` : `${SUBTASK_WORDS} words at most`;
  ids.subtaskHint.textContent = `${length} · ${total} of ${SUBTASKS_MAX} subtasks${words > SUBTASK_WORDS ? ': too long, name one step' : ''}`;
}
function showSubtaskError(error) {
  if (error.status === 409) {
    ids.subtaskError.textContent = 'The action changed in the register: its subtasks were reloaded. Try again.';
    reloadDetails();
  } else {
    ids.subtaskError.textContent = error.message;
    renderSubtaskList(); // a refused tick goes back to what the register says
  }
  ids.subtaskError.hidden = false;
}
function subtaskSend(method, suffix, body) {
  const {id, version} = noteState;
  return () => request(`/api/actions/${encodeURIComponent(id)}/subtasks${suffix}`, {
    method, headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
    body: JSON.stringify({details_version: version, ...body})
  });
}
// After a write the list is drawn again: the focus goes back to the same place (`part` of the item at `index`, else the field).
function focusSubtask(index, part = '.subtask-check') {
  if (!editorOpen()) return;
  const items = [...ids.editorSubtaskList.querySelectorAll('.subtask-item')];
  const item = items[Math.min(index, items.length - 1)];
  const target = item && [item.querySelector(part), item.querySelector('.subtask-check')].find(control => control && !control.disabled);
  (target || (ids.subtaskForm.hidden ? null : ids.subtaskInput))?.focus();
}
async function addSubtask() {
  if (noteBusy || !noteState) return;
  const text = ids.subtaskInput.value.replace(/\s+/g, ' ').trim();
  if (!text) {
    showSubtaskError(new Error('Enter a subtask before adding it.'));
    ids.subtaskInput.focus();
    return;
  }
  const fresh = await changeDetails(subtaskSend('POST', '', {text}), showSubtaskError);
  if (fresh) ids.subtaskInput.value = '';
  updateSubtaskHint();
  if (editorOpen()) (ids.subtaskForm.hidden ? focusSubtask(subtaskState.length - 1) : ids.subtaskInput.focus());
}
async function tickSubtask(item, done) {
  if (noteBusy || !noteState) return;
  await changeDetails(subtaskSend('PATCH', `/${item.index}`, {done}), showSubtaskError);
  focusSubtask(item.index);
}
async function moveSubtask(item, step) {
  if (noteBusy || !noteState) return;
  const to = item.index + step;
  const fresh = await changeDetails(subtaskSend('PATCH', `/${item.index}`, {to}), showSubtaskError);
  focusSubtask(fresh ? to : item.index, step < 0 ? '.subtask-up' : '.subtask-down');
}
async function removeSubtask(item) {
  if (noteBusy || !noteState) return;
  const fresh = await changeDetails(subtaskSend('DELETE', `/${item.index}`, {}), showSubtaskError);
  if (fresh) {
    showToast('Subtask deleted', {undo: true});
    if (subtaskState.length) focusSubtask(item.index); else ids.subtaskInput.focus();
  }
}
// Rename in place: Enter (or leaving the field) saves, Esc puts the text back.
function startSubtaskRename(index) {
  if (noteBusy || !noteState) return;
  renderSubtaskList();
  const item = subtaskState[index];
  const li = ids.editorSubtaskList.querySelector(`.subtask-item[data-index="${index}"]`);
  if (!item || !li) return;
  subtaskEditing = index;
  const input = element('input', 'subtask-rename');
  input.value = item.text;
  input.maxLength = 300;
  input.autocomplete = 'off';
  input.setAttribute('aria-label', `New text of “${item.text}”`);
  input.setAttribute('aria-describedby', 'subtaskHint');
  li.classList.add('is-editing');
  li.querySelector('.subtask-text').replaceWith(input);
  let settled = false;
  const finish = async save => {
    if (settled) return;
    settled = true;
    const text = input.value.replace(/\s+/g, ' ').trim();
    if (!save || !text || text === item.text) {
      renderSubtaskList();
      updateSubtaskHint();
      focusSubtask(index, '.subtask-rename-button');
      return;
    }
    const fresh = await changeDetails(subtaskSend('PATCH', `/${index}`, {text}), showSubtaskError);
    updateSubtaskHint();
    focusSubtask(index, fresh ? '.subtask-check' : '.subtask-rename-button');
  };
  input.addEventListener('input', () => updateSubtaskHint(input.value));
  input.addEventListener('keydown', event => {
    if (event.isComposing) return;
    if (event.key === 'Enter') { event.preventDefault(); finish(true); }
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); finish(false); }
  });
  input.addEventListener('blur', () => { if (input.isConnected) finish(true); });
  input.focus();
  input.select();
  updateSubtaskHint(input.value);
}
// The details of the open action read again (after an undo, or when the register changed under a write).
function reloadDetails() {
  const action = editorAction && findAction(editorAction.id);
  if (!action || !editorOpen()) return;
  const session = editorHistoryRequest;
  for (const key of [...detailCache.keys()]) if (key.startsWith(`${action.id}:`)) detailCache.delete(key);
  loadDetails(action).then(details => {
    if (session === editorHistoryRequest && editorOpen() && !noteBusy) renderDetails(details);
  }).catch(() => { /* The next refresh will catch up. */ });
}
function setEditorBusy(busy) {
  ids.saveEditor.disabled = busy;
  ids.deleteEditor.disabled = busy;
  ids.saveEditor.setAttribute('aria-busy', String(busy));
}
// No confirmation: Undo (and Git) restore a deleted action. Checks `version` and `details_version`, then stacks the undo.
async function removeAction(id, version, detailsVersion = null) {
  const details = detailsVersion ?? (await loadDetails({id, version})).details_version;
  const result = await request(`/api/actions/${encodeURIComponent(id)}`, {
    method: 'DELETE', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
    body: JSON.stringify({version, details_version: details})
  });
  for (const key of [...detailCache.keys()]) if (key.startsWith(`${id}:`)) detailCache.delete(key);
  setUndo(result.undo);
}
async function deleteEditor() {
  const id = ids.editor.dataset.actionId;
  if (!id || ids.deleteEditor.disabled || noteBusy) return;
  const index = visibleRows().findIndex(row => row.dataset.id === id);
  setEditorBusy(true);
  ids.editorError.hidden = true;
  try {
    await removeAction(id, ids.editor.dataset.version, noteState?.id === id ? noteState.version : null);
    closeEditor({force: true, refocus: false});
    await refresh();
    showToast('Action deleted', {undo: true});
    focusAction(id, 'title', index);
  } catch (error) {
    ids.editorError.textContent = error.status === 409 ? 'The register changed: close and reopen the action before deleting it.' : error.message;
    ids.editorError.hidden = false;
  } finally {
    setEditorBusy(false);
  }
}
async function deleteFromRow(action, button) {
  if (button.disabled) return;
  closePopover(false);
  const index = visibleRows().findIndex(row => row.dataset.id === action.id);
  button.disabled = true;
  try {
    await removeAction(action.id, action.version);
    if (editorAction?.id === action.id) closeEditor({force: true, refocus: false});
    await refresh();
    showToast('Action deleted', {undo: true});
    focusAction(action.id, 'title', index);
  } catch (error) {
    const conflict = error.status === 409;
    if (conflict) await refresh();
    showError(conflict ? `The register changed: the list was refreshed, check ${action.id} and try again.` : error.message);
    button.disabled = false;
  }
}
// The form's submit (Enter in the title, ⌘ Enter): an existing action sends its changes now, a new action is created.
async function saveEditor(event) {
  event.preventDefault();
  if (editorAction) { flushAutosave(); return; }
  if (ids.saveEditor.disabled) return;
  if (!ids.editorForm.reportValidity()) return;
  const action = formAction();
  setEditorBusy(true);
  try {
    const result = await request('/api/actions', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({register: ids.editorProject.value, action})
    });
    setUndo(result.undo);
    closeEditor({force: true, refocus: false});
    await refresh();
    showToast(`Action ${result.id} created`, {undo: true});
    focusAction(result.id);
  } catch (error) {
    ids.editorError.textContent = error.status === 409 ? 'The register changed since you opened it: copy your changes, close the panel, then reopen the action.' : error.message;
    ids.editorError.hidden = false;
  } finally {
    setEditorBusy(false);
    updateEditorButtons();
  }
}
// Quick edits from a row or a card: the whole line goes back with one field changed (the group is left as it is).
async function patchAction(action, changes, message, {anchor = null, part = 'title'} = {}) {
  const index = visibleRows().findIndex(row => row.dataset.id === action.id);
  const keepFocus = anchor !== null || (document.activeElement && activeRoot()?.contains(document.activeElement));
  if (anchor) anchor.disabled = true;
  try {
    const result = await request(`/api/actions/${encodeURIComponent(action.id)}`, {
      method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({version: action.version, action: {
        title: action.raw_title, owner: action.owner, state: action.state, priority: action.priority,
        due: action.due, scheduled: action.scheduled, ...changes
      }})
    });
    setUndo(result.undo);
    showToast(message, {undo: true, warnings: result.warnings || []});
    await refresh();
  } catch (error) {
    await refresh();
    showError(error.status === 409 ? `The register changed: the list was refreshed, check ${action.id} and try again.` : error.message);
  }
  if (keepFocus && ACTION_VIEWS.includes(view)) focusAction(action.id, part, index);
}
function updateStatus(action, state, anchor = null) {
  if (state === action.state) return Promise.resolve();
  return patchAction(action, {state}, 'Status updated', {anchor, part: 'status'});
}
function updateDue(action, due, anchor = null) {
  if (due === action.due) return Promise.resolve();
  return patchAction(action, {due}, due ? 'Due date updated' : 'Due date removed', {anchor, part: 'due'});
}
