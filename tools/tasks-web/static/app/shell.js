'use strict';

// ---------- Toast ----------
function hideToast() { ids.toast.hidden = true; }
// `warnings`: what the actions tool said about a write that went through (open subtasks left unticked by a closing): added to the
// message, which then stays longer and takes the warning style.
function showToast(message, {undo = false, warnings = []} = {}) {
  ids.toastText.textContent = warnings.length ? `${message}. ${warnings.join(' ')}` : message;
  ids.toast.classList.toggle('is-warning', warnings.length > 0);
  ids.toastAction.hidden = !undo || !undoState.available;
  ids.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, warnings.length ? 10000 : undo ? 6000 : 3500);
}
ids.toast.addEventListener('mouseenter', () => clearTimeout(toastTimer));
ids.toast.addEventListener('focusin', () => clearTimeout(toastTimer));
ids.toast.addEventListener('mouseleave', () => { clearTimeout(toastTimer); toastTimer = setTimeout(hideToast, 2500); });
ids.toastAction.addEventListener('click', () => { ids.toastAction.hidden = true; hideToast(); undoLast(); });

// ---------- Sidebar (full or icon rail), drawer and the "More options" menu ----------
// 'collapsed' is the icon rail (the sidebar column shrinks to --sidebar-rail-w, only the icons stay); under 900 px the drawer always shows
// the full sidebar.
const SIDEBAR_KEY = 'actions-brain-sidebar-v1';
const narrowQuery = window.matchMedia('(max-width: 900px)');
function readSidebarCollapsed() {
  try { return localStorage.getItem(SIDEBAR_KEY) === 'collapsed'; } catch { return false; }
}
function updateSidebarToggle() {
  const narrow = narrowQuery.matches;
  const open = narrow ? ids.app.classList.contains('drawer-open') : !ids.app.classList.contains('sidebar-collapsed');
  ids.sidebarToggle.setAttribute('aria-expanded', String(open));
  const label = narrow ? (open ? 'Close menu' : 'Open menu') : open ? 'Collapse the sidebar' : 'Expand the sidebar';
  ids.sidebarToggle.setAttribute('aria-label', label);
  ids.sidebarToggle.title = `${label} ([)`;
  ids.mainContent.inert = narrow && open;
}
function openDrawer() {
  ids.app.classList.add('drawer-open');
  ids.scrim.hidden = false;
  updateSidebarToggle();
  (ids.sidebar.querySelector('.nav-item[aria-current="page"]') || ids.todayButton).focus();
}
function closeDrawer(refocus = true) {
  if (!ids.app.classList.contains('drawer-open')) return;
  ids.app.classList.remove('drawer-open');
  ids.scrim.hidden = true;
  updateSidebarToggle();
  if (refocus) ids.sidebarToggle.focus();
}
let slideTimer = 0;
function toggleSidebar() {
  if (narrowQuery.matches) {
    if (ids.app.classList.contains('drawer-open')) closeDrawer(); else openDrawer();
    return;
  }
  closeMoreMenu(false);
  closeBrainMenu(false);
  hideRailTip();
  ids.app.classList.add('is-sliding'); // eases the width between full and rail (CSS), only for this change
  clearTimeout(slideTimer);
  slideTimer = setTimeout(() => ids.app.classList.remove('is-sliding'), 260);
  const collapsed = ids.app.classList.toggle('sidebar-collapsed');
  try { localStorage.setItem(SIDEBAR_KEY, collapsed ? 'collapsed' : 'open'); } catch { /* Not remembered. */ }
  updateSidebarToggle();
}
narrowQuery.addEventListener('change', () => { closeDrawer(false); hideRailTip(); updateSidebarToggle(); });

// In the rail the labels are visually hidden (still read by screen readers), so each entry shows its label, and its count when it has
// one, in a small bubble to its right on hover and keyboard focus. The bubble is fixed to the page: the sidebar scrolls and would clip it.
const RAIL_ITEMS = '.nav-item, .update-button, .brain-button, #moreButton';
let railTipItem = null;
function railActive() { return !narrowQuery.matches && ids.app.classList.contains('sidebar-collapsed'); }
function railTipParts(item) {
  if (item === ids.brainButton) return [ids.brainName.textContent.trim(), ''];
  if (item === ids.moreButton) return [item.getAttribute('aria-label') || '', ''];
  const label = (item.querySelector('.nav-label') || item.querySelector('#updateButtonLabel'))?.textContent.trim() || '';
  return [label, item.querySelector('.nav-count')?.textContent.trim() || ''];
}
function hideRailTip() {
  ids.railTip.hidden = true;
  if (railTipItem?.dataset.title) { railTipItem.title = railTipItem.dataset.title; delete railTipItem.dataset.title; }
  railTipItem = null;
}
function showRailTip(item) {
  if (!railActive() || !item || item === railTipItem || brainMenuOpen() || !ids.moreMenu.hidden) return;
  hideRailTip();
  const [label, count] = railTipParts(item);
  if (!label) return;
  ids.railTip.replaceChildren(element('span', '', label), ...(count ? [element('span', 'rail-tip-count', count)] : []));
  ids.railTip.hidden = false;
  const box = item.getBoundingClientRect();
  const tip = ids.railTip.getBoundingClientRect();
  ids.railTip.style.left = `${Math.round(box.right + 8)}px`;
  ids.railTip.style.top = `${Math.round(Math.max(4, Math.min(box.top + (box.height - tip.height) / 2, innerHeight - tip.height - 4)))}px`;
  if (item.title) { item.dataset.title = item.title; item.removeAttribute('title'); } // no second, native tooltip
  railTipItem = item;
}
ids.sidebar.addEventListener('mouseover', event => {
  const item = event.target instanceof Element ? event.target.closest(RAIL_ITEMS) : null;
  if (item) showRailTip(item); else hideRailTip();
});
ids.sidebar.addEventListener('mouseleave', hideRailTip);
ids.sidebar.addEventListener('focusin', event => { if (event.target instanceof Element && event.target.matches(`${RAIL_ITEMS}:focus-visible`)) showRailTip(event.target); });
ids.sidebar.addEventListener('focusout', hideRailTip);
ids.sidebar.addEventListener('click', hideRailTip);
ids.sidebar.querySelector('.sidebar-scroll').addEventListener('scroll', hideRailTip, {passive: true});
function moreItems() { return [...ids.moreMenu.querySelectorAll('.menu-item')]; }
function openMoreMenu() {
  closePopover(false);
  hideRailTip();
  ids.moreMenu.hidden = false;
  ids.moreButton.setAttribute('aria-expanded', 'true');
  moreItems()[0].focus();
}
function closeMoreMenu(refocus = true) {
  if (ids.moreMenu.hidden) return;
  ids.moreMenu.hidden = true;
  ids.moreButton.setAttribute('aria-expanded', 'false');
  if (refocus) ids.moreButton.focus();
}
ids.moreButton.addEventListener('click', () => { if (ids.moreMenu.hidden) openMoreMenu(); else closeMoreMenu(); });
ids.moreMenu.addEventListener('keydown', event => {
  const items = moreItems();
  const index = items.indexOf(document.activeElement);
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
  } else if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault();
    items[event.key === 'Home' ? 0 : items.length - 1].focus();
  } else if (event.key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    closeMoreMenu();
  } else if (event.key === 'Tab') closeMoreMenu(false);
});
ids.refreshButton.addEventListener('click', async () => {
  closeMoreMenu();
  if (!await loadBrains()) refresh();
});
ids.undoButton.addEventListener('click', () => {
  if (ids.undoButton.getAttribute('aria-disabled') === 'true') return;
  closeMoreMenu();
  undoLast();
});
ids.shortcutsButton.addEventListener('click', () => { closeMoreMenu(false); ids.shortcutsDialog.showModal(); });
ids.quitButton.addEventListener('click', () => { closeMoreMenu(false); ids.quitDialog.showModal(); });
ids.quitConfirm.addEventListener('click', async () => {
  ids.quitConfirm.disabled = true;
  try {
    await request('/api/shutdown', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: '{}'
    });
    ids.quitDialog.close();
    document.body.replaceChildren(element('main', 'stopped-screen', 'Actions Brain has stopped. You can close this tab. Relaunch the app from the Dock to open it again.'));
    window.close();
  } catch (error) {
    ids.quitConfirm.disabled = false;
    ids.quitDialog.close();
    showToast(`Could not stop: ${error.message}`);
  }
});

// ---------- Keyboard ----------
function isTyping(target) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}
function focusSearch() {
  ids.searchInput.focus();
  ids.searchInput.select();
}
function handleEscape(event) {
  if (document.querySelector('dialog[open]')) return;
  if (dismissInfoTip()) { event.preventDefault(); return; }
  if (popoverState) { event.preventDefault(); closePopover(); return; }
  if (!ids.moreMenu.hidden) { event.preventDefault(); closeMoreMenu(); return; }
  if (ids.app.classList.contains('drawer-open')) { event.preventDefault(); closeDrawer(); return; }
  if (editorOpen() && (ids.editor.contains(document.activeElement) || !isTyping(document.activeElement))) {
    if (!ids.noteForm.hidden && ids.noteForm.contains(document.activeElement)) { event.preventDefault(); closeNoteForm(); return; }
    event.preventDefault();
    closeEditor();
  }
}
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.isComposing) return;
  const key = event.key;
  const typing = isTyping(event.target);
  if ((event.metaKey || event.ctrlKey) && !event.shiftKey && !event.altKey && key.toLowerCase() === 'z') {
    if (typing || document.querySelector('dialog[open]')) return;
    event.preventDefault();
    undoLast();
    return;
  }
  if ((event.metaKey || event.ctrlKey) && key === 'Enter' && editorOpen() && ids.editor.contains(event.target) && !ids.noteForm.contains(event.target) && !ids.editorSubtasks.contains(event.target)) {
    event.preventDefault();
    ids.editorForm.requestSubmit();
    return;
  }
  if (key === 'Escape') { handleEscape(event); return; }
  if (event.metaKey || event.ctrlKey || typing) return;
  if (document.querySelector('dialog[open]') || popoverState || brainMenuOpen() || !ids.moreMenu.hidden) return;
  const digit = /^[0-5]$/.test(key) ? key : /^Digit[0-5]$/.test(event.code) && !event.altKey ? event.code.slice(5) : null;
  const inRows = ACTION_VIEWS.includes(view);
  const onBody = event.target === document.body || event.target === ids.mainContent || event.target === ids.editorTitle;
  if (key === '/') { event.preventDefault(); focusSearch(); }
  else if (key === '?') { event.preventDefault(); ids.shortcutsDialog.showModal(); }
  else if (key === '[') { event.preventDefault(); toggleSidebar(); }
  else if (digit && !event.altKey) { event.preventDefault(); setView(['priorities', 'today', 'list', 'board', 'timeline', 'docs'][Number(digit)]); }
  else if (key === 'n' && !event.altKey) { event.preventDefault(); openEditor(); }
  else if (inRows && (key === 'j' || key === 'ArrowDown') && !event.altKey) {
    if (key === 'ArrowDown' && !onBody && !activeRoot().contains(event.target)) return;
    event.preventDefault();
    moveSelection(1);
  } else if (inRows && (key === 'k' || key === 'ArrowUp') && !event.altKey) {
    if (key === 'ArrowUp' && !onBody && !activeRoot().contains(event.target)) return;
    event.preventDefault();
    moveSelection(-1);
  } else if (inRows && key === 'Enter' && onBody && event.target !== ids.editorTitle) {
    const action = selectedAction();
    if (action) { event.preventDefault(); openEditor(action); }
  } else if (inRows && (key === 's' || key === 'd') && !event.altKey) {
    const action = selectedAction();
    const row = action && rowFor(action.id);
    if (!row) return;
    event.preventDefault();
    // A timeline chip has no status or date button of its own: the menus open from the chip.
    const main = row.querySelector(ROW_MAIN) || row;
    if (key === 's') openStatusMenu(action, row.querySelector('.status-button') || main);
    else openDueMenu(action, row.querySelector('.due-button') || row.querySelector('.status-button') || main);
  }
});

// ---------- Markdown toolbar (new note dialog and note editor share it) ----------
// The text edits live in md-edit.js; this is the buttons, the arrow menu and the keyboard.
const MAC_KEYS = /Mac|iPhone|iPad|iPod/i.test(navigator.userAgentData?.platform || navigator.platform || '');
const MD_TOOLS = [
  [
    {id: 'bold', label: 'Bold', icon: ICONS.bold, key: 'b'},
    {id: 'italic', label: 'Italic', icon: ICONS.italic, key: 'i'},
    {id: 'underline', label: 'Underline', icon: ICONS.underline, key: 'u'},
    {id: 'strike', label: 'Strikethrough', icon: ICONS.strike, key: 'x', shift: true}
  ],
  [
    {id: 'bullets', label: 'Bulleted list', icon: ICONS.bullets},
    {id: 'numbers', label: 'Numbered list', icon: ICONS.numbers},
    {id: 'tasks', label: 'Checklist', icon: ICONS.tasks},
    {id: 'quote', label: 'Quote', icon: ICONS.quote}
  ],
  [
    {id: 'code', label: 'Inline code', icon: ICONS.code},
    {id: 'link', label: 'Link', icon: ICONS.link, key: 'k'},
    {id: 'arrow', label: 'Arrow', icon: ICONS.arrow, title: 'Arrow (hold for more)'}
  ]
];
const MD_ARROWS = [['→', 'Right arrow'], ['←', 'Left arrow'], ['⇒', 'Double arrow'], ['↔', 'Both directions']];
// The shortcut is ⌘ on a Mac (Ctrl+B, F, K... are text-editing keys there) and Ctrl elsewhere.
function mdKeys(tool) {
  const letter = tool.key.toUpperCase();
  return MAC_KEYS
    ? {label: `${tool.shift ? '⇧' : ''}⌘${letter}`, aria: `Meta+${tool.shift ? 'Shift+' : ''}${letter}`}
    : {label: `Ctrl+${tool.shift ? 'Shift+' : ''}${letter}`, aria: `Control+${tool.shift ? 'Shift+' : ''}${letter}`};
}
function mountMarkdownToolbar(bar, area) {
  const buttons = [];
  for (const group of MD_TOOLS) {
    const box = element('div', 'md-group');
    for (const tool of group) {
      const keys = tool.key ? mdKeys(tool) : null;
      const button = iconButton('icon-button md-tool', tool.label, tool.icon, keys ? `${tool.label} (${keys.label})` : tool.title || tool.label);
      button.dataset.tool = tool.id;
      button.tabIndex = buttons.length ? -1 : 0; // roving tabindex: one stop in the Tab order
      if (keys) button.setAttribute('aria-keyshortcuts', keys.aria);
      buttons.push(button);
      box.append(button);
    }
    bar.append(box);
  }
  const arrowButton = buttons.find(button => button.dataset.tool === 'arrow');
  arrowButton.setAttribute('aria-haspopup', 'menu');
  arrowButton.setAttribute('aria-expanded', 'false');
  const menu = element('div', 'menu md-menu');
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', 'Arrows');
  menu.hidden = true;
  for (const [symbol, name] of MD_ARROWS) {
    const item = element('button', 'menu-item');
    item.type = 'button';
    item.setAttribute('role', 'menuitem');
    const glyph = element('span', 'md-glyph', symbol);
    glyph.setAttribute('aria-hidden', 'true');
    item.append(glyph, element('span', 'menu-item-text', name));
    item.addEventListener('click', () => { closeMenu(false); run('arrow', symbol); });
    menu.append(item);
  }
  bar.append(menu);

  // One edit, applied the way typing is, so the browser's undo and redo keep working; setRangeText is the fallback.
  function run(id, argument) {
    if (area.disabled || area.readOnly) return;
    const value = area.value;
    const change = MarkdownEdit.edit(id, value, area.selectionStart, area.selectionEnd, argument);
    if (!change.text && change.from === change.to) return;
    const expected = value.slice(0, change.from) + change.text + value.slice(change.to);
    area.focus();
    area.setSelectionRange(change.from, change.to);
    try { if (change.text) document.execCommand('insertText', false, change.text); else document.execCommand('delete'); } catch { /* handled below */ }
    if (area.value !== expected) {
      if (area.value !== value) area.value = value;
      area.setRangeText(change.text, change.from, change.to, 'end');
      area.dispatchEvent(new Event('input', {bubbles: true}));
    }
    area.setSelectionRange(change.select[0], change.select[1]);
  }
  let held = false;
  function openMenu() {
    menu.hidden = false;
    arrowButton.setAttribute('aria-expanded', 'true');
    menu.style.left = `${Math.max(0, Math.min(arrowButton.offsetLeft, bar.clientWidth - menu.offsetWidth))}px`;
    menu.style.top = `${arrowButton.offsetTop + arrowButton.offsetHeight + 2}px`;
    menu.firstElementChild.focus();
  }
  function closeMenu(refocus = true) {
    held = false;
    if (menu.hidden) return;
    menu.hidden = true;
    arrowButton.setAttribute('aria-expanded', 'false');
    if (refocus) arrowButton.focus();
  }

  // Keep the field focused (and its selection) while a button is pressed with the mouse.
  bar.addEventListener('mousedown', event => { if (event.target.closest('.md-tool, .menu-item')) event.preventDefault(); });
  bar.addEventListener('click', event => {
    const button = event.target.closest('.md-tool');
    if (!button) return;
    if (held) { held = false; return; } // the press that opened the menu is not a click on the arrow
    run(button.dataset.tool);
  });
  // A long press on the arrow opens the menu of the other arrows (the contextual menu key does too).
  let pressTimer = 0;
  arrowButton.addEventListener('pointerdown', event => {
    held = false;
    if (event.button === 0) pressTimer = setTimeout(() => { held = true; openMenu(); }, 450);
  });
  for (const type of ['pointerup', 'pointerleave', 'pointercancel']) arrowButton.addEventListener(type, () => clearTimeout(pressTimer));
  arrowButton.addEventListener('contextmenu', event => { event.preventDefault(); openMenu(); });
  bar.addEventListener('focusin', event => {
    const index = buttons.indexOf(event.target);
    if (index >= 0) buttons.forEach((button, position) => { button.tabIndex = position === index ? 0 : -1; });
  });
  bar.addEventListener('focusout', event => { if (!bar.contains(event.relatedTarget)) closeMenu(false); });
  bar.addEventListener('keydown', event => {
    if (menu.contains(event.target) || event.altKey || event.ctrlKey || event.metaKey) return;
    const index = buttons.indexOf(event.target);
    if (index < 0) return;
    const last = buttons.length - 1;
    if (event.key === 'ArrowRight') buttons[index === last ? 0 : index + 1].focus();
    else if (event.key === 'ArrowLeft') buttons[index === 0 ? last : index - 1].focus();
    else if (event.key === 'Home') buttons[0].focus();
    else if (event.key === 'End') buttons[last].focus();
    else if (event.key === 'ArrowDown' && event.target === arrowButton) openMenu();
    else return;
    event.preventDefault();
  });
  menu.addEventListener('keydown', event => {
    const items = [...menu.children];
    const index = items.indexOf(document.activeElement);
    if (event.key === 'ArrowDown') items[(index + 1) % items.length].focus();
    else if (event.key === 'ArrowUp') items[(index + items.length - 1) % items.length].focus();
    else if (event.key === 'Home') items[0].focus();
    else if (event.key === 'End') items[items.length - 1].focus();
    else if (event.key === 'Escape') { event.stopPropagation(); closeMenu(); } // closes the menu, not the dialog
    else if (event.key === 'Tab') { closeMenu(false); return; }
    else return;
    event.preventDefault();
  });
  document.addEventListener('pointerdown', event => { if (!menu.hidden && !menu.contains(event.target) && !arrowButton.contains(event.target)) closeMenu(false); });

  area.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.isComposing || event.altKey) return;
    if (MAC_KEYS ? !event.metaKey || event.ctrlKey : !event.ctrlKey || event.metaKey) return;
    const key = /^[a-z]$/i.test(event.key) ? event.key.toLowerCase() : /^Key[A-Z]$/.test(event.code) ? event.code.slice(3).toLowerCase() : '';
    const tool = MD_TOOLS.flat().find(item => item.key === key && Boolean(item.shift) === event.shiftKey);
    if (!tool) return;
    event.preventDefault();
    run(tool.id);
  });
  return {closeMenu};
}
