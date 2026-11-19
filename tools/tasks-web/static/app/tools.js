'use strict';

// ---------- Tools ----------
async function loadTools() {
  ids.toolsCatalog.replaceChildren(element('p', 'loading-note', 'Loading tools…'));
  try {
    tools = (await request('/api/tools')).tools;
    const groups = [...new Set(tools.map(tool => tool.group))];
    const sections = [];
    for (const group of groups) {
      const section = element('details', 'tool-group');
      section.open = true;
      const summary = element('summary', 'tool-group-heading');
      summary.append(svgIcon(ICONS.chevron, 'fold-chevron'), element('span', '', group), element('span', 'tool-group-count', String(tools.filter(tool => tool.group === group).length)));
      section.append(summary);
      for (const tool of tools.filter(item => item.group === group)) {
        const row = element('div', 'tool-row');
        const copy = element('div', 'tool-copy');
        const name = element('div', 'tool-name');
        name.append(element('span', '', tool.label));
        if (tool.confirm) name.append(element('span', 'tool-writes', 'writes to the brain'));
        const description = element('p', '', tool.description);
        description.title = `${tool.description}\n${tool.command}`;
        copy.append(name, description);
        if (tool.unavailable) copy.append(element('p', 'error-note', tool.unavailable));
        const button = element('button', 'button button-small', 'Run');
        button.type = 'button';
        button.setAttribute('aria-label', `Run ${tool.label}`);
        button.title = tool.unavailable || tool.command;
        button.disabled = Boolean(tool.unavailable);
        button.dataset.unavailable = tool.unavailable ? 'true' : '';
        button.addEventListener('click', () => runTool(tool, button));
        row.append(copy, button);
        section.append(row);
      }
      sections.push(section);
    }
    ids.toolsCatalog.replaceChildren(...sections);
    render();
  } catch (error) {
    ids.toolsCatalog.replaceChildren(element('p', 'error-note', error.message));
  }
}
function countTools() {
  ids.resultCount.textContent = tools.length ? plural(tools.length, 'tool') : '';
}
async function runTool(tool, button) {
  if (tool.confirm && !confirm(tool.confirm)) return;
  const buttons = ids.toolsCatalog.querySelectorAll('button');
  buttons.forEach(item => { item.disabled = true; });
  button.textContent = 'Running…';
  ids.toolResultTitle.textContent = tool.label;
  ids.toolResultCommand.textContent = tool.command;
  ids.toolResultCommand.hidden = false;
  ids.toolResultStatus.textContent = 'Running';
  ids.toolResultStatus.className = '';
  ids.toolResultEmpty.hidden = true;
  ids.toolResultOutput.hidden = false;
  ids.toolResultOutput.textContent = 'The command is running. Its output will appear here.';
  try {
    const result = await request('/api/tools/run', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tasks-Token': token},
      body: JSON.stringify({id: tool.id})
    });
    ids.toolResultStatus.textContent = result.ok ? 'Done' : 'Failed';
    ids.toolResultStatus.className = result.ok ? 'tool-status-ok' : 'tool-status-error';
    ids.toolResultOutput.textContent = result.output + (result.truncated ? '\n\n[Output truncated]' : '');
    if (tool.confirm && result.ok) {
      detailCache.clear();
      await refresh();
    }
  } catch (error) {
    ids.toolResultStatus.textContent = 'Failed';
    ids.toolResultStatus.className = 'tool-status-error';
    ids.toolResultOutput.textContent = error.message;
  } finally {
    buttons.forEach(item => { item.disabled = Boolean(item.dataset.unavailable); });
    button.textContent = 'Run';
  }
}

// ---------- Info tips and popovers ----------
// A small ⓘ button with something to read. Two kinds, both closed by Esc:
// - a tooltip (the title of the view): opens on hover and on keyboard focus, linked to its button by aria-describedby, no interaction inside;
// - a popover (the online copy of a brain), for a panel that holds a link: a disclosure. The button has aria-expanded and aria-controls and
//   toggles the panel (click, Enter, Space); the pointer opens it too and may move from the button into the panel; Tab from the button
//   reaches the link; Esc, a click outside, or the focus leaving the button and the panel closes it.
function infoOf(node) { return node instanceof Element ? node.closest('.info') : null; }
function isPopover(info) { return info.classList.contains('info-pop'); }
function infoButton(info) { return info.querySelector('.info-button'); }
// Open the panel under its button, kept inside the window (above the button when there is no room below).
function openInfo(info) {
  if (info.classList.contains('is-dismissed')) return;
  info.classList.add('is-open');
  if (isPopover(info)) infoButton(info).setAttribute('aria-expanded', 'true');
  const tip = info.querySelector('.info-tip');
  info.classList.remove('is-above');
  tip.style.left = '0px';
  const rect = tip.getBoundingClientRect();
  const over = rect.right - (document.documentElement.clientWidth - 12);
  if (over > 0) tip.style.left = `${-over}px`;
  if (rect.bottom > document.documentElement.clientHeight - 8 && info.getBoundingClientRect().top > rect.height) info.classList.add('is-above');
}
function closeInfo(info) {
  info.classList.remove('is-open', 'is-dismissed', 'is-above');
  delete info.dataset.pinned;
  if (isPopover(info)) infoButton(info).setAttribute('aria-expanded', 'false');
}
// Closed on purpose (Esc, a second click): it stays closed until the pointer and the focus have left and returned.
function dismissInfo(info) {
  closeInfo(info);
  info.classList.add('is-dismissed');
}
// Esc closes the panel that is open, and nothing else that time. A popover gives the focus back to its button.
function dismissInfoTip() {
  const info = document.querySelector('.info.is-open');
  if (!info) return false;
  dismissInfo(info);
  if (isPopover(info)) infoButton(info).focus();
  return true;
}
function togglePopover(info) {
  if (info.classList.contains('is-open') && info.dataset.pinned) { dismissInfo(info); return; }
  info.classList.remove('is-dismissed');
  openInfo(info);
  info.dataset.pinned = '1';
}
document.addEventListener('pointerover', event => { const info = infoOf(event.target); if (info) openInfo(info); });
document.addEventListener('focusin', event => { const info = infoOf(event.target); if (info && !isPopover(info)) openInfo(info); });
document.addEventListener('pointerout', event => {
  const info = infoOf(event.target);
  if (info && !info.contains(event.relatedTarget) && !info.dataset.pinned && !info.matches(':focus-within')) closeInfo(info);
});
document.addEventListener('focusout', event => {
  const info = infoOf(event.target);
  if (!info || info.contains(event.relatedTarget)) return;
  delete info.dataset.pinned;
  if (!info.matches(':hover')) closeInfo(info);
});
document.addEventListener('click', event => {
  const button = event.target instanceof Element ? event.target.closest('.info-pop .info-button') : null;
  if (button) togglePopover(infoOf(button));
});
document.addEventListener('pointerdown', event => {
  for (const info of document.querySelectorAll('.info-pop[data-pinned]')) if (!info.contains(event.target)) closeInfo(info);
});
// The online copy of a brain: "Git", then its URL as a link to the repository's page (plain text when there is no safe page), or why there is none.
// A page served by an older server sends no `url` at all: it is asked to restart rather than told there is no online copy.
// A URL may wrap after a slash (not in the middle of a word when it can be avoided).
function breakableUrl(node, text) {
  for (const part of text.split(/(?<=\/)/)) node.append(part, document.createElement('wbr'));
  return node;
}
function onlineCopyPopover(card) {
  const id = `gitInfo-${card.name}`;
  const known = 'url' in card;
  const label = !known ? 'Restart tasks-web to see the online copy' : card.url ? `Online copy: ${card.url}` : 'No online copy';
  const info = element('span', 'info info-pop');
  const button = element('button', 'info-button');
  button.type = 'button';
  button.id = id;
  button.dataset.focusKey = `info:${card.name}`;
  button.setAttribute('aria-label', label);
  button.setAttribute('aria-expanded', 'false');
  button.setAttribute('aria-controls', `${id}Panel`);
  button.append(svgIcon(ICONS.info));
  const panel = element('span', 'info-tip');
  panel.id = `${id}Panel`;
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', 'Online copy');
  const box = element('span', 'info-tip-box');
  box.append(element('span', 'info-tip-line info-tip-head', 'Git'));
  if (known && card.url && typeof card.web_url === 'string' && /^https?:\/\//i.test(card.web_url)) {
    const link = element('a', 'info-tip-line info-link');
    link.href = card.web_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.append(breakableUrl(element('span', 'info-link-text'), card.url), element('span', 'sr-only', ' (opens in a new tab)'), svgIcon(ICONS.open));
    box.append(link);
  } else {
    const line = element('span', 'info-tip-line');
    if (known && card.url) breakableUrl(line, card.url); else line.textContent = known ? 'No online copy' : 'Restart tasks-web to see the online copy';
    box.append(line);
  }
  panel.append(box);
  info.append(button, panel);
  return info;
}
