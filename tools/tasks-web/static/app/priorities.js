'use strict';

// ---------- Priorities (the /priorities ranking, shown on Focus) ----------
// The file `priorities/<brain>.md` written by the /priorities skill, parsed by GET /api/priorities (see "Priorities file" in REFERENCE.md).
// It has no view of its own: Focus (app/actions.js, `renderToday`) shows its sections among the blocks of the brain's own actions.
let prioData = null; // the last answer for this brain: {exists, sections, version, stale, ...}
let prioRequest = 0;
let prioError = '';
const PRIO_ID = /\b[A-Z]{2,5}-\d{3}\b/g;
function resetPriorities() {
  prioRequest += 1;
  prioData = null;
  prioError = '';
}
async function loadPriorities() {
  const requestId = ++prioRequest;
  try {
    const data = await request('/api/priorities');
    if (requestId !== prioRequest) return;
    const unchanged = prioData && !prioError && data.exists === prioData.exists && data.version === prioData.version && data.stale === prioData.stale && data.today === prioData.today;
    prioData = data;
    prioError = '';
    if (view === 'today' && !unchanged) render();
  } catch (error) {
    if (requestId !== prioRequest || error.stale) return;
    prioError = error.message;
  }
}
// The file when it is today's (`stale` false), else null: only a fresh ranking takes part in Focus.
function freshPriorities() { return prioData?.exists && !prioData.stale ? prioData : null; }
function prioSection(key) { return freshPriorities()?.sections.find(section => section.key === key) || null; }
// The action IDs a section cites (the Now items, to leave out the actions they already name).
function prioCitedIds(section) { return new Set(section ? section.html.match(PRIO_ID) || [] : []); }
// The quiet line under Focus's title: where the ranking comes from, or why it is not there. With a project chosen, the ranking is
// cut to the items about it (`prioScoped`): `scopedItems` is how many are left.
function prioSourceLine(scopedItems = 0) {
  if (!prioData?.exists) return '';
  if (prioData.stale) {
    const generated = prioData.generated ? new Date(prioData.generated) : null;
    const when = generated && !Number.isNaN(generated.getTime()) ? `dates from ${DAY_FORMAT.format(generated)}` : 'has no valid date';
    return `The /priorities ranking ${when}: run /priorities in Claude Code to refresh it.`;
  }
  if (projectScope && !scopedItems) return `No /priorities item cites the actions of ${scopeLabel(projectScope)}.`;
  const generated = new Date(prioData.generated);
  const ranked = `Ranked by /priorities at ${TIME_FORMAT.format(generated)}${projectScope ? `, the items about ${scopeLabel(projectScope)}` : ''}`;
  return [ranked, ...(prioData.next_meeting ? [`next meeting ${prioData.next_meeting}`] : [])].join(' · ');
}
// The ranking covers the whole brain: with a project chosen, a section keeps only its items that cite an action of the brain whose
// register is in scope (the same test as the rest of Focus), drafts included with their item; its count is theirs. The text of a
// draft does not count as a citation. Without a project, the section as it is.
function prioScoped(section) {
  if (!section || !projectScope) return section;
  const scoped = new Set(snapshot.actions.filter(action => inScope(action.register)).map(action => action.id));
  const cites = node => {
    const copy = node.cloneNode(true);
    for (const draft of copy.querySelectorAll('.prio-draft')) draft.remove();
    return (copy.textContent.match(PRIO_ID) || []).some(id => scoped.has(id));
  };
  const template = document.createElement('template');
  template.innerHTML = section.html; // the server's safe rendering, as in prioBody
  let count = 0;
  for (const node of [...template.content.children]) {
    if (node.matches('ul, ol')) {
      for (const item of [...node.children]) if (cites(item)) count += 1; else item.remove();
      if (!node.children.length) node.remove();
    } else if (!cites(node)) node.remove();
  }
  return {...section, html: template.innerHTML, count};
}
// The action IDs of a rendered section become buttons when the action is in the brain's snapshot; the others stay text.
function linkActionIds(root) {
  const known = new Map(snapshot.actions.map(action => [action.id, action]));
  if (!known.size) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.parentElement.closest('a, button, .prio-draft') && node.nodeValue.match(PRIO_ID)?.some(id => known.has(id))) nodes.push(node);
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
// Each draft is a native <details>, closed by default, with a Copy message button added at the end of its opened box.
function addDraftCopy(root) {
  for (const draft of root.querySelectorAll('.prio-draft')) {
    const button = element('button', 'prio-draft-copy');
    button.type = 'button';
    button.append(svgIcon(ICONS.copy), element('span', '', 'Copy message'));
    draft.append(button);
  }
}
const draftKey = draft => draft.querySelector('summary')?.textContent || '';
async function copyDraft(button) {
  const body = button.closest('.prio-draft').querySelector('.prio-draft-body');
  try {
    await navigator.clipboard.writeText(body.textContent);
    showToast('Message copied');
  } catch {
    const range = document.createRange();
    range.selectNodeContents(body);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    showToast('Copy failed: select the text and copy it');
  }
}
function prioBody(section) {
  const body = element('div', 'prio-body');
  const template = document.createElement('template');
  template.innerHTML = section.html; // rendered by the server's safe Markdown renderer (raw HTML is escaped there)
  body.append(template.content);
  linkActionIds(body);
  addDraftCopy(body);
  return body;
}
// The ID of an item opens its action; a draft's button copies its message.
ids.todayView.addEventListener('click', event => {
  const copy = event.target instanceof Element ? event.target.closest('.prio-draft-copy') : null;
  if (copy) {
    event.preventDefault(); // a button inside <details> must not toggle it
    copyDraft(copy);
    return;
  }
  const button = event.target instanceof Element ? event.target.closest('.prio-id') : null;
  const action = button && snapshot.actions.find(item => item.id === button.dataset.actionId);
  if (action) openEditor(action);
});
window.addEventListener('focus', () => { if (view === 'today') loadPriorities(); });
