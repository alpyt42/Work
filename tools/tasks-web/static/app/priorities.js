'use strict';

// ---------- Priorities ----------
// The file `priorities/<brain>.md` written by the /priorities skill, parsed by GET /api/priorities (see "Priorities file" in the README).
let prioData = null; // the last answer for this brain: {exists, sections, version, stale, ...}
let prioRequest = 0;
let prioError = '';
const PRIO_ID = /\b[A-Z]{2,5}-\d{3}\b/g;
function resetPriorities() {
  prioRequest += 1;
  prioData = null;
  prioError = '';
  ids.prioCount.textContent = '';
  ids.prioButton.title = 'Priorities (0)';
  ids.prioView.replaceChildren();
}
async function loadPriorities() {
  const requestId = ++prioRequest;
  try {
    const data = await request('/api/priorities');
    if (requestId !== prioRequest) return;
    const unchanged = prioData && !prioError && data.exists === prioData.exists && data.version === prioData.version && data.stale === prioData.stale && data.today === prioData.today;
    prioData = data;
    prioError = '';
    const now = data.exists ? (data.sections.find(section => section.key === 'now')?.count || 0) : 0;
    ids.prioCount.textContent = now ? String(now) : '';
    ids.prioButton.title = `Priorities (0)${now ? `: ${now} to do now` : ''}`;
    if (view === 'priorities' && !unchanged) renderPriorities();
  } catch (error) {
    if (requestId !== prioRequest || error.stale) return;
    prioError = error.message;
    if (view === 'priorities') renderPriorities();
  }
}
// The action IDs of a rendered section become buttons when the action is in the brain's snapshot; the others stay text.
function linkActionIds(root) {
  const known = new Map(snapshot.actions.map(action => [action.id, action]));
  if (!known.size) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.parentElement.closest('a, button') && node.nodeValue.match(PRIO_ID)?.some(id => known.has(id))) nodes.push(node);
  }
  for (const node of nodes) {
    const text = node.nodeValue;
    const parts = [];
    let last = 0;
    for (const match of text.matchAll(PRIO_ID)) {
      if (!known.has(match[0])) continue;
      if (match.index > last) parts.push(document.createTextNode(text.slice(last, match.index)));
      const button = element('button', 'prio-id', match[0]);
      button.type = 'button';
      button.dataset.actionId = match[0];
      button.title = `Open ${match[0]}`;
      parts.push(button);
      last = match.index + match[0].length;
    }
    if (last < text.length) parts.push(document.createTextNode(text.slice(last)));
    node.replaceWith(...parts);
  }
}
function prioHeader(data) {
  const head = element('header', 'prio-head');
  const line = element('div', 'prio-title-line');
  line.append(element('h2', 'prio-title', data.title || 'Priorities'));
  if (data.stale) {
    const badge = element('span', 'prio-badge', "Not today's");
    badge.title = data.generated ? `Generated on ${data.generated}` : 'No valid generation date';
    line.append(badge);
  }
  head.append(line);
  const generated = data.generated ? new Date(data.generated) : null;
  const facts = [];
  if (generated && !Number.isNaN(generated.getTime())) facts.push(`Generated: ${relativeTime(generated)} (${TIME_FORMAT.format(generated)}, ${DAY_YEAR_FORMAT.format(generated)})`);
  else facts.push('Generation date unknown');
  if (data.horizon) facts.push(`Horizon ${data.horizon.replace('..', ' to ')}`);
  if (data.next_meeting) facts.push(`Next meeting: ${data.next_meeting}`);
  head.append(element('p', 'prio-facts', facts.join(' · ')));
  if (data.stale) head.append(element('p', 'prio-hint', 'Run /priorities in Claude Code to refresh it.'));
  return head;
}
function prioBody(section) {
  const body = element('div', 'prio-body');
  const template = document.createElement('template');
  template.innerHTML = section.html; // rendered by the server's safe Markdown renderer (raw HTML is escaped there)
  body.append(template.content);
  linkActionIds(body);
  return body;
}
function renderPriorities() {
  const scroll = ids.prioView.scrollTop;
  ids.resultCount.textContent = '';
  if (prioError && !prioData) {
    ids.prioView.replaceChildren(element('p', 'error-banner', prioError));
    return;
  }
  if (!prioData) {
    ids.prioView.replaceChildren(element('p', 'empty-inline', 'Loading…'));
    return;
  }
  if (!prioData.exists) {
    const box = element('div', 'empty-state');
    box.append(element('h2', '', 'No priorities for this brain yet.'), element('p', '', 'Run /priorities in Claude Code.'));
    ids.prioView.replaceChildren(box);
    return;
  }
  const nodes = [];
  if (prioError) nodes.push(element('p', 'error-banner', prioError));
  nodes.push(prioHeader(prioData));
  const total = prioData.sections.reduce((sum, section) => sum + (section.key === 'warnings' ? 0 : section.count), 0);
  ids.resultCount.textContent = total ? plural(total, 'item') : '';
  for (const section of prioData.sections.filter(item => item.key === 'warnings')) {
    const notice = element('section', 'prio-notice');
    notice.setAttribute('role', 'note');
    notice.setAttribute('aria-label', section.title);
    notice.append(element('h3', 'prio-notice-title', section.title), prioBody(section));
    nodes.push(notice);
  }
  const cards = prioData.sections.filter(item => item.key !== 'warnings');
  if (!cards.length) nodes.push(element('p', 'empty-inline', 'Nothing to do in this horizon.'));
  cards.forEach((section, index) => {
    const card = element('section', `prio-card prio-${section.key}`);
    const title = element('h3', 'prio-card-title');
    title.id = `prio-section-${index}`;
    title.append(element('span', '', section.title), element('span', 'section-count', String(section.count)));
    card.setAttribute('aria-labelledby', title.id);
    card.append(title, prioBody(section));
    nodes.push(card);
  });
  ids.prioView.replaceChildren(...nodes);
  ids.prioView.scrollTop = scroll;
}
ids.prioView.addEventListener('click', event => {
  const button = event.target instanceof Element ? event.target.closest('.prio-id') : null;
  const action = button && snapshot.actions.find(item => item.id === button.dataset.actionId);
  if (action) openEditor(action);
});
window.addEventListener('focus', () => { if (view === 'priorities') loadPriorities(); });
