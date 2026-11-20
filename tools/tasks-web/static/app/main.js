'use strict';

// ---------- Wiring ----------
const newNoteBar = mountMarkdownToolbar(ids.newNoteToolbar, ids.newNoteContent);
mountMarkdownToolbar(ids.docEditorToolbar, ids.docEditor);
for (const [name, id] of Object.entries(NAV_BUTTONS)) ids[id].addEventListener('click', () => setView(name));
ids.newButton.addEventListener('click', () => openEditor());
ids.newNoteButton.addEventListener('click', openNewNote);
ids.sidebarToggle.addEventListener('click', toggleSidebar);
ids.sidebarClose.addEventListener('click', () => closeDrawer());
ids.scrim.addEventListener('click', () => closeDrawer());
ids.projectChipClear.addEventListener('click', () => { setProjectScope(''); ids.resultCount.focus(); });
// Archives: archive the project or client chosen in the sidebar, unarchive the one open, read its documents, confirm.
ids.archiveScopeButton.addEventListener('click', () => {
  const target = scopeArchive();
  if (target) askArchive('archive', target.folder, target.label, ids.archiveScopeButton);
});
ids.archiveUnarchive.addEventListener('click', () => {
  const item = archivesData?.archives.find(entry => entry.folder === archiveSelected);
  if (item) askArchive('unarchive', item.folder, archiveName(item), ids.archiveUnarchive);
});
ids.archiveBack.addEventListener('click', () => {
  archiveDocOpen = null;
  archiveDocRequest += 1;
  if (archiveProject) renderArchivePane(); else if (archiveSelected) openArchive(archiveSelected);
  ids.archivePaneTitle.focus({preventScroll: true});
});
ids.archiveBody.addEventListener('click', event => {
  const link = event.target.closest('a.doc-link');
  if (!link || !ids.archiveBody.contains(link)) return;
  event.preventDefault();
  openArchiveDoc(link.dataset.doc);
});
ids.archiveConfirm.addEventListener('click', confirmArchive);
ids.archiveDialog.addEventListener('cancel', event => { if (archiveAsk?.busy) event.preventDefault(); }); // never closed halfway through a move
ids.archiveDialog.addEventListener('close', () => {
  const ask = archiveAsk;
  if (ask?.busy) return;
  archiveAsk = null;
  if (ask?.returnFocus?.isConnected && !editorOpen()) ask.returnFocus.focus({preventScroll: true});
});
ids.searchInput.addEventListener('input', () => { if (ids.searchInput.value.trim()) scheduleDocSearch(); else runDocSearch(); });
ids.searchInput.addEventListener('keydown', event => {
  if (event.isComposing) return;
  if (event.key === 'Enter') { event.preventDefault(); if (ids.searchInput.value.trim()) runDocSearch(); }
  else if (event.key === 'Escape' && (ids.searchInput.value || view === 'search')) { // clears the search and goes back to the view it left
    event.preventDefault();
    ids.searchInput.value = '';
    runDocSearch();
    ids.searchInput.blur();
  }
});
ids.docProject.addEventListener('change', () => {
  if (ids.docProject.value && projectScope) { projectScope = ''; populateGroupFilter(); renderProjectNav(); }
  refreshDocLists();
  renderFilterChips();
  saveUIState();
});
ids.docType.addEventListener('change', () => {
  if (view === 'search') runDocSearch(); // the server keeps the best documents of that type, not the best of all filtered here
  else renderDocsView(); // the Docs list is already loaded: only filtered again
  renderFilterChips();
  saveUIState();
});
ids.docBack.addEventListener('click', docGoBack);
ids.docEdit.addEventListener('click', startDocEdit);
ids.docCancel.addEventListener('click', cancelDocEdit);
ids.docSave.addEventListener('click', saveDoc);
ids.docEditor.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') { event.preventDefault(); saveDoc(); }
});
ids.docArticle.addEventListener('change', event => {
  const box = event.target.closest?.('input.task-box');
  if (box && ids.docArticle.contains(box)) toggleTaskBox(box);
});
ids.docArticle.addEventListener('click', event => {
  const link = event.target.closest('a.doc-link');
  if (!link || !ids.docArticle.contains(link)) return;
  event.preventDefault();
  const id = link.dataset.doc;
  const anchor = link.dataset.anchor || '';
  if (docCurrent && id === docCurrent.id) { if (anchor) scrollDocAnchor(anchor); return; }
  openDoc(id, {nav: 'link', anchor});
});
ids.addBrainForm.addEventListener('submit', createBrain);
ids.addBrainName.addEventListener('input', () => { ids.addBrainName.value = ids.addBrainName.value.toLowerCase(); });
ids.closeAddBrain.addEventListener('click', () => ids.addBrainDialog.close());
ids.cancelAddBrain.addEventListener('click', () => ids.addBrainDialog.close());
ids.newNoteForm.addEventListener('submit', createNote);
ids.newNoteProject.addEventListener('change', updateNewNoteWhere);
ids.closeNewNote.addEventListener('click', () => ids.newNoteDialog.close());
ids.cancelNewNote.addEventListener('click', () => ids.newNoteDialog.close());
ids.groupFilter.addEventListener('change', titleGroupFilter);
ids.boardOwner.addEventListener('change', storeBoardEveryone);
for (const node of [ids.groupFilter, ids.ownerFilter, ids.boardOwner, ids.scopeFilter]) {
  node.addEventListener('change', () => { render(); saveUIState(); });
}
// The Board's switch: everyone's cards, or back to one's own.
ids.boardEveryone.addEventListener('click', () => {
  ids.boardOwner.value = ids.boardOwner.value === '' ? OWNER_MINE : '';
  storeBoardEveryone();
  render();
  saveUIState();
});
ids.resetFilters.addEventListener('click', () => {
  projectScope = '';
  if (isDocsView()) {
    ids.docProject.value = '';
    ids.docType.value = '';
    refreshDocLists();
  } else {
    ids.groupFilter.value = '';
    // Each view clears the owner filter it shows; on the Board a person gives way to the position the switch was left in.
    if (view !== 'board') ids.ownerFilter.value = '';
    else if (isPerson(ids.boardOwner.value)) ids.boardOwner.value = readBoardEveryone() ? '' : OWNER_MINE;
    ids.scopeFilter.value = 'active';
  }
  populateGroupFilter();
  renderProjectNav();
  render();
  saveUIState();
  (isDocsView() ? ids.docProject : ids.resultCount).focus();
});
ids.foldAllButton.addEventListener('click', setAllFolds);
ids.brainButton.addEventListener('click', () => { if (brainMenuOpen()) closeBrainMenu(); else openBrainMenu(); });
ids.brainButton.addEventListener('keydown', event => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); openBrainMenu(); }
});
ids.brainMenu.addEventListener('keydown', event => {
  const key = event.key;
  const items = brainMenuItems();
  if (key === 'ArrowDown') setBrainActive(brainMenuIndex + 1);
  else if (key === 'ArrowUp') setBrainActive(brainMenuIndex - 1);
  else if (key === 'Home') setBrainActive(0);
  else if (key === 'End') setBrainActive(items.length - 1);
  else if (key === 'Enter' || key === ' ') activateBrainItem(items[brainMenuIndex]);
  else if (key === 'Escape') { event.stopPropagation(); closeBrainMenu(); }
  else if (key === 'Tab') closeBrainMenu(false);
  else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    // Type-ahead: the next entry whose name starts with the typed letter.
    const letter = key.toLocaleLowerCase(LOCALE);
    const ordered = [...items.keys()].map(offset => (brainMenuIndex + 1 + offset) % items.length);
    const next = ordered.find(position => items[position].textContent.trim().toLocaleLowerCase(LOCALE).startsWith(letter));
    if (next !== undefined) setBrainActive(next);
    return;
  } else return;
  event.preventDefault();
});
ids.brainMenu.addEventListener('focusout', event => {
  if (!ids.brainSwitch.contains(event.relatedTarget)) closeBrainMenu(false);
});
ids.editorTitle.tabIndex = -1;
ids.closeEditor.addEventListener('click', () => closeEditor());
ids.cancelEditor.addEventListener('click', () => closeEditor());
ids.editorForm.addEventListener('submit', saveEditor);
ids.editorForm.addEventListener('input', updateEditorButtons);
ids.editorForm.addEventListener('change', updateEditorButtons);
ids.deleteEditor.addEventListener('click', deleteEditor);
ids.editorActionTitle.addEventListener('input', sizeTitleField);
ids.editorActionTitle.addEventListener('keydown', event => {
  // The title is one line in the register: Enter saves (Shift+Enter is ignored as well).
  if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); if (!event.shiftKey) ids.editorForm.requestSubmit(); }
});
ids.editorProject.addEventListener('change', () => fillGroupOptions());
ids.editorGroup.addEventListener('change', () => showGroupField(true));
ids.editorGroupNew.addEventListener('input', () => showGroupField());
ids.addNoteButton.addEventListener('click', openNoteForm);
ids.closeNoteForm.addEventListener('click', () => closeNoteForm());
ids.submitNote.addEventListener('click', submitNote);
ids.noteInput.addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeNoteForm(); }
  else if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); if (!event.shiftKey) submitNote(); }
});
ids.noteInput.addEventListener('input', updateNoteWords);
ids.submitSubtask.addEventListener('click', addSubtask);
ids.subtaskInput.addEventListener('input', () => updateSubtaskHint());
ids.subtaskInput.addEventListener('keydown', event => {
  if (event.isComposing) return;
  // Enter adds the subtask (never submits the panel); Esc clears a typed text, and closes the panel on an empty field.
  if (event.key === 'Enter') { event.preventDefault(); addSubtask(); }
  else if (event.key === 'Escape' && ids.subtaskInput.value) {
    event.preventDefault();
    event.stopPropagation();
    ids.subtaskInput.value = '';
    ids.subtaskError.hidden = true;
    updateSubtaskHint();
  }
});

// Timeline controls
for (const button of ids.timelineView.querySelectorAll('[data-range]')) {
  button.addEventListener('click', () => {
    if (timelineRange === button.dataset.range) return;
    timelineRange = button.dataset.range;
    timelineAnchor = true;
    saveUIState();
    render();
  });
}
ids.timelineToday.addEventListener('click', () => scrollTimelineToToday(true));
ids.timelineBack.addEventListener('click', () => scrollTimelineByWeeks(-1));
ids.timelineForward.addEventListener('click', () => scrollTimelineByWeeks(1));
ids.timelineLate.addEventListener('click', focusFirstOverdue);
ids.timelineDone.addEventListener('click', () => { timelineDone = !timelineDone; saveUIState(); render(); });
ids.timelineSummary.addEventListener('click', event => {
  const stat = event.target.closest('.tl-stat');
  if (!stat) return;
  if (stat.dataset.stat === 'none' || stat.dataset.stat === 'vague') {
    showTray();
    ids.timelineTrayList.querySelector(`#tl-tray-${stat.dataset.stat}`)?.scrollIntoView({block: 'nearest'});
  } else if (!stat.classList.contains('is-zero')) setTimelineSpot(stat.dataset.stat);
});
ids.timelineTrayToggle.addEventListener('click', () => setTrayOpen(!timelineTrayOpen));
ids.timelineTraySearch.addEventListener('input', () => renderTray(timelineBase));
ids.timelineTraySearch.addEventListener('keydown', event => {
  const first = event.key === 'ArrowDown' ? visibleTrayCards()[0] : null;
  if (!first) return;
  event.preventDefault();
  selectAndFollow(first.dataset.id);
});
ids.timelineScroll.addEventListener('keydown', timelineKey);
ids.timelineScroll.addEventListener('pointerover', event => { const cell = dueCell(event.target); if (cell) lightDueDay(cell); });
ids.timelineScroll.addEventListener('pointerout', event => {
  const cell = dueCell(event.target);
  if (cell && cell !== dueCell(event.relatedTarget)) lightDueDay(dueCell(document.activeElement)); // back to the focused chip's day, if any
});
ids.timelineScroll.addEventListener('focusin', event => { const cell = dueCell(event.target); if (cell) lightDueDay(cell); });
ids.timelineScroll.addEventListener('focusout', () => lightDueDay(null));
// Focusing a chip or a card selects it, so the quick edits (`s`, `d`) apply to the one you are on.
ids.timelineView.addEventListener('focusin', event => {
  const cell = event.target instanceof Element ? event.target.closest('.tl-chip, .tl-card-main')?.closest('[data-id]') : null;
  if (!cell || cell.dataset.id === selectedId) return;
  selectedId = cell.dataset.id;
  markSelection();
});
ids.timelineTray.addEventListener('keydown', trayKey);
// A plain wheel scrolls the frieze sideways when sideways is the only way it can scroll (Shift+wheel and a trackpad already do).
ids.timelineScroll.addEventListener('wheel', event => {
  const scroll = ids.timelineScroll;
  if (event.ctrlKey || event.deltaX !== 0 || event.deltaY === 0 || scroll.scrollWidth <= scroll.clientWidth + 1 || scroll.scrollHeight > scroll.clientHeight + 1) return;
  scroll.scrollLeft += event.deltaY;
  event.preventDefault();
}, {passive: false});
// Planning by dragging: a day takes a chip or a tray card; the tray takes a chip back (no deadline). The write is the one of the panel.
ids.timelineScroll.addEventListener('dragover', event => {
  if (!timelineDrag) return;
  const target = timelineDayAt(event);
  showTimelineDrop(target);
  if (!target) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
});
ids.timelineScroll.addEventListener('dragleave', event => { if (!ids.timelineScroll.contains(event.relatedTarget)) showTimelineDrop(null); });
ids.timelineScroll.addEventListener('drop', event => {
  if (!timelineDrag) return;
  const target = timelineDayAt(event);
  const action = findAction(timelineDrag.id);
  endTimelineDrag();
  if (!target) return;
  event.preventDefault();
  if (action && !closed(action) && action.due !== target.day.iso) updateDue(action, target.day.iso);
});
ids.timelineTray.addEventListener('dragover', event => {
  if (timelineDrag?.kind !== 'chip') return;
  event.preventDefault();
  ids.timelineTray.classList.add('is-drop');
});
ids.timelineTray.addEventListener('dragleave', event => { if (!ids.timelineTray.contains(event.relatedTarget)) ids.timelineTray.classList.remove('is-drop'); });
ids.timelineTray.addEventListener('drop', event => {
  if (timelineDrag?.kind !== 'chip') return;
  event.preventDefault();
  const action = findAction(timelineDrag.id);
  endTimelineDrag();
  if (action && !closed(action) && action.due) updateDue(action, '');
});
document.addEventListener('dragend', endTimelineDrag);
// An empty day of a project: a click starts a new action due that day, in that project.
function clearGhost() { ids.timelineScroll.querySelector('.tl-ghost')?.remove(); }
ids.timelineScroll.addEventListener('pointermove', event => {
  const body = event.target instanceof Element && event.target.classList.contains('tl-days') ? event.target : null;
  const target = body && !timelineDrag ? timelineDayAt(event) : null;
  if (!target) { clearGhost(); return; }
  let ghost = ids.timelineScroll.querySelector('.tl-ghost');
  if (!ghost) {
    ghost = element('div', 'tl-ghost');
    ghost.setAttribute('aria-hidden', 'true');
    ghost.append(svgIcon(ICONS.plus));
  }
  const sc = timelineModel.sc;
  ghost.style.left = `${sc.xs[target.index]}px`;
  ghost.style.width = `${sc.xs[target.index + 1] - sc.xs[target.index]}px`;
  body.title = `New action due ${dayText(target.day.iso, DAY_FORMAT)}`;
  body.append(ghost);
});
ids.timelineScroll.addEventListener('pointerleave', clearGhost);
ids.timelineScroll.addEventListener('click', event => {
  if (!(event.target instanceof Element) || !event.target.classList.contains('tl-days')) return;
  const target = timelineDayAt(event);
  if (target) openEditor(null, {register: event.target.closest('.tl-lane').dataset.register, due: target.day.iso});
});
// The axis follows the width of the page: drawn again when it changes (and between the frieze and the agenda under 700 px).
let timelineFrame = 0;
new ResizeObserver(() => {
  if (view !== 'timeline' || timelineFrame) return;
  const width = Math.floor(ids.timelineScroll.clientWidth);
  const narrow = ids.mainContent.getBoundingClientRect().width < TL.agenda;
  if (width === 0 || (Math.abs(width - timelineWidth) <= 1 && narrow === timelineNarrow)) return;
  timelineFrame = requestAnimationFrame(() => {
    timelineFrame = 0;
    if (narrow !== timelineNarrow) timelineAnchor = true;
    render();
  });
}).observe(ids.timelineScroll);

// ---------- Start ----------
applyAccent(brainFromUrl() || readStoredBrain());
if (!narrowQuery.matches && readSidebarCollapsed()) ids.app.classList.add('sidebar-collapsed');
updateSidebarToggle();
restoreOwner(ids.ownerFilter, savedUI.owner, '');
restoreOwner(ids.boardOwner, savedUI.boardOwner, readBoardEveryone() ? '' : OWNER_MINE);
ids.scopeFilter.value = ['active', 'all', 'closed'].includes(savedUI.scope) ? savedUI.scope : 'active';
ids.docProject.value = ['', INBOX_REGISTER, 'none'].includes(savedUI.docProject) ? savedUI.docProject : '';
ids.docType.value = ['', ...Object.keys(DOC_TYPE_LABELS)].includes(savedUI.docType) ? savedUI.docType : '';
// The brain is known before anything is requested, so that no view starts on the wrong one.
loadBrains({initial: true}).finally(() => {
  setView(view, false);
  refresh();
});
showUpdatedToast();
checkUpdate();
setInterval(checkUpdate, UPDATE_CHECK_EVERY);
