'use strict';

// ---------- Timeline ----------
// The logic is in timeline-view.js (range, scale, placement, lanes, summary, tray, keyboard neighbours); this draws it. Wide: a frieze fitted
// to the width, one lane per project, a sticky overdue zone, a tray of the actions with no deadline under it. Narrow (under 700 px): an
// agenda, one row per day. Dates are formatted like everywhere else in the app (the browser's locale).
const TL = {chipH: 72, gap: 6, pad: 6, minLane: 52, agenda: 700, slim: 44, tight: 104}; // tight: a chip narrower than this drops the owner's name
const SHORT_FORMAT = new Intl.DateTimeFormat(LOCALE, {day: 'numeric', month: 'short'});
const WHEN_FORMAT = new Intl.DateTimeFormat(LOCALE, {weekday: 'short', day: 'numeric'});
const WEEKDAY_FORMAT = new Intl.DateTimeFormat(LOCALE, {weekday: 'short'});
const WEEKDAY_NARROW = new Intl.DateTimeFormat(LOCALE, {weekday: 'narrow'});
const MONTH_FORMAT = new Intl.DateTimeFormat(LOCALE, {month: 'long'});
const MONTH_YEAR_FORMAT = new Intl.DateTimeFormat(LOCALE, {month: 'long', year: 'numeric'});
const TL_STATS = [
  {key: 'overdue', label: 'Overdue', spot: true},
  {key: 'week', label: 'This week', spot: true},
  {key: 'next', label: 'Next 2 weeks', spot: true},
  {key: 'none', label: 'No deadline'},
  {key: 'vague', label: 'Vague'}
];
function dayText(iso, format = LONG_FORMAT) { return format.format(parseDay(iso)); }
function entryName(entry) {
  const action = entry.action;
  const parts = [`${action.id}: ${action.title}`, `Status: ${statusLabel(action.state)}`];
  if (entry.done && TimelineView.isPlainDate(action.done)) parts.push(`Done on ${dayText(action.done)}`);
  else parts.push(`Due ${dayText(entry.date)}${entry.overdue ? `, ${plural(entry.overdue, 'day')} overdue` : ''}${entry.done ? ' (done)' : ''}`);
  if (entry.scheduled) parts.push(`Scheduled ${dayText(entry.scheduled)}`);
  parts.push(`Project: ${action.project}`, `Owner: ${action.owner}`);
  if (action.subtasks?.total) parts.push(`Subtasks: ${subtaskSummary(action)}`);
  return `${parts.join('. ')}.`;
}
function entryTitle(entry) {
  const action = entry.action;
  const lines = [`${action.id} ${action.title}`, `${action.project} · ${action.owner}`];
  if (entry.done && TimelineView.isPlainDate(action.done)) lines.push(`Done on ${dayText(action.done)}`);
  else lines.push(`Due on ${dayText(entry.date)}${entry.overdue ? ` (${plural(entry.overdue, 'day')} overdue)` : ''}`);
  if (entry.scheduled) lines.push(`Scheduled for ${dayText(entry.scheduled)}`);
  if (!entry.done) lines.push('Drag onto a day to move it, Alt+← → to move it by a day');
  return lines.join('\n');
}
function openFromTimeline(action) {
  selectAction(action.id, {focus: false, scroll: false});
  openEditor(action);
}
// The first name of the owner, only when it is not the person of this brain (the others are who the eye looks for).
function ownerBadge(action) {
  const name = isMine(action) ? '' : timelineOwners.get(action.owner) || TimelineView.firstName(action.owner);
  if (!name) return null;
  const badge = element('span', 'tl-who', name);
  badge.setAttribute('aria-hidden', 'true');
  return badge;
}
function toneOf(action) { return groupTone(action.register); } // the project's thin accent: a colour of the group palette, by register

// Dragging: a chip or a tray card is picked up by its action ID; a day of the frieze takes it.
function startTimelineDrag(event, action, kind) {
  if (event.target.closest?.('button:not(.tl-chip, .tl-card-main)')) { event.preventDefault(); return; }
  closePopover(false);
  timelineDrag = {id: action.id, kind};
  event.dataTransfer.setData('text/plain', action.id);
  event.dataTransfer.effectAllowed = 'move';
  const source = event.currentTarget;
  setTimeout(() => source.classList.add('is-dragging'), 0); // after the browser has taken the drag image
  ids.timelineView.classList.add(kind === 'chip' ? 'is-dragging-chip' : 'is-dragging-card');
}
function endTimelineDrag() {
  timelineDrag = null;
  ids.timelineView.classList.remove('is-dragging-chip', 'is-dragging-card');
  ids.timelineView.querySelectorAll('.is-dragging, .is-drop').forEach(node => node.classList.remove('is-dragging', 'is-drop'));
  showTimelineDrop(null);
}
// A chip: status, ID, the owner's first name (dropped when the chip is tight), the title on up to three lines. In the days it ends on its
// due day, and the last day of the chip is the deadline mark; near the left edge it shrinks to the room it has, and a flipped chip (not
// even the least room on its left) starts on its day instead, with the mark at its start.
function timelineChip(entry, {when = false, where = false, spot = ''} = {}) {
  const action = entry.action;
  const dim = spot && !TimelineView.inSpot(action, spot, today());
  const cell = element('div', `tl-cell ${statusInfo(action.state).cls} ${toneOf(action)}${entry.overdue ? ' is-overdue' : ''}${entry.done ? ' is-done' : ''}${entry.dueW ? ' has-due' : ''}${entry.dueW && entry.w < TL.tight ? ' is-tight' : ''}${entry.flip ? ' is-flip' : ''}${dim ? ' is-dim' : ''}`);
  cell.dataset.id = action.id;
  cell.setAttribute('role', 'listitem');
  if (entry.dueW) {
    cell.dataset.col = String(entry.column);
    cell.style.setProperty('--due-w', `${entry.dueW}px`);
  }
  const button = element('button', 'tl-chip');
  button.type = 'button';
  button.tabIndex = -1;
  button.setAttribute('aria-label', entryName(entry));
  button.title = entryTitle(entry);
  const top = element('span', 'tl-chip-top');
  top.append(statusIcon(action.state), element('span', 'tl-chip-id', action.id));
  const pill = subtaskPill(action);
  if (pill) top.append(pill);
  const badge = ownerBadge(action);
  if (badge) top.append(badge);
  // The overdue zone says "overdue" and has little room: its chips carry no flag and no hourglass (the tooltip has the scheduled date).
  if (entry.sched && !entry.marker && !entry.late) top.append(svgIcon(ICONS.hourglass, 'tl-chip-sched'));
  if (entry.overdue && !entry.late) top.append(svgIcon(ICONS.late, 'tl-chip-flag'));
  // The date leads the title when the chip's position does not say it (overdue zone, crowded axis).
  const title = element('span', 'tl-chip-title');
  if (when) title.append(element('span', 'tl-chip-when', `${dayText(entry.date, entry.late ? SHORT_FORMAT : WHEN_FORMAT)} · `));
  title.append(action.title);
  button.append(top, title);
  if (where) button.append(element('span', 'tl-chip-where', shortProject(action.project)));
  cell.append(button);
  if (entry.dueW) {
    const due = element('span', 'tl-due'); // the due day itself: as wide as its column, in the status colour, with a solid edge
    due.setAttribute('aria-hidden', 'true');
    cell.append(due);
  }
  cell.addEventListener('click', () => openFromTimeline(action));
  if (!entry.done) {
    cell.draggable = true;
    cell.addEventListener('dragstart', event => startTimelineDrag(event, action, 'chip'));
  }
  return cell;
}
// The scheduled date: a small hollow marker on its day, a dashed line to the chip it belongs to.
function timelineMarker(entry, top) {
  const marker = element('div', `tl-marker ${statusInfo(entry.action.state).cls}`);
  marker.setAttribute('aria-hidden', 'true');
  marker.title = `${entry.id} is scheduled for ${dayText(entry.scheduled)}, due on ${dayText(entry.date)}`;
  marker.append(svgIcon(ICONS.hourglass, 'tl-marker-icon'));
  marker.style.left = `${entry.marker.x - 9}px`;
  marker.style.top = `${top + TL.chipH / 2 - 9}px`;
  marker.addEventListener('click', () => openFromTimeline(entry.action));
  return marker;
}
function absolute(className, left, width) {
  const node = element('div', className);
  node.setAttribute('aria-hidden', 'true');
  node.style.left = `${left}px`;
  node.style.width = `${width}px`;
  return node;
}
function timelineHead(span, sc, late, summary) {
  const dense = sc.density === 'day';
  const head = element('div', 'tl-head');
  head.setAttribute('aria-hidden', 'true');
  head.style.height = `${dense ? 78 : 46}px`;
  const corner = element('div', 'tl-corner');
  const slim = sc.lateW <= TL.slim;
  const lateHead = element('div', `tl-late-head${summary.overdue ? ' has-late' : ''}${slim ? ' is-slim' : ''}`);
  lateHead.title = slim ? `No overdue action before ${dayText(span.start, SHORT_FORMAT)}` : '';
  if (slim) lateHead.append(svgIcon(ICONS.check, 'tl-late-ok'));
  else lateHead.append(element('span', 'tl-late-title', 'Overdue'), element('span', 'tl-late-count', String(late)), element('span', 'tl-late-caption', `before ${dayText(span.start, SHORT_FORMAT)}`));
  const days = element('div', 'tl-days-head');
  days.style.width = `${sc.total}px`;
  const todayDay = span.days.find(day => day.today);
  if (todayDay) days.append(absolute('tl-today-head', sc.xs[todayDay.index], sc.xs[todayDay.index + 1] - sc.xs[todayDay.index]));
  span.months.forEach((month, index) => {
    const cell = absolute('tl-month', sc.xs[month.start], sc.xs[month.start + month.span] - sc.xs[month.start]);
    const date = parseDay(`${month.year}-${String(month.month).padStart(2, '0')}-01`);
    cell.append(element('span', '', (index === 0 || month.month === 1 ? MONTH_YEAR_FORMAT : MONTH_FORMAT).format(date)));
    days.append(cell);
  });
  for (const week of span.weekSpans) {
    const width = sc.xs[week.start + week.span] - sc.xs[week.start];
    const cell = absolute('tl-week', sc.xs[week.start], width);
    const first = span.days[week.start];
    cell.title = `Week ${week.week}, from ${dayText(first.iso)}`;
    cell.append(element('span', 'tl-week-no', `W${week.week}`));
    if (width >= 120) cell.append(element('span', 'tl-week-from', dayText(first.iso, SHORT_FORMAT)));
    days.append(cell);
  }
  for (const day of span.days) {
    const cell = absolute(`tl-day${day.weekend ? ' is-weekend' : ''}${day.today ? ' is-today' : ''}`, sc.xs[day.index], sc.xs[day.index + 1] - sc.xs[day.index]);
    if (dense) {
      if (!day.weekend || sc.endW >= 15) {
        cell.append(element('span', 'tl-dow', WEEKDAY_NARROW.format(parseDay(day.iso))), element('span', 'tl-dom', String(day.day)));
      }
      cell.title = dayText(day.iso);
      cell.dataset.day = String(day.index);
    }
    if (dense) days.append(cell);
  }
  head.append(corner, lateHead, days);
  return head;
}
function timelineLane(lane, span, sc, spot) {
  const node = element('div', `tl-lane ${groupTone(lane.register)}`);
  node.dataset.register = lane.register;
  node.setAttribute('role', 'group');
  node.setAttribute('aria-label', lane.project);
  const rows = Math.max(lane.tracks, lane.lateTracks);
  node.style.minHeight = `${rows ? Math.max(TL.minLane, TL.pad * 2 + rows * TL.chipH + (rows - 1) * TL.gap) : TL.minLane}px`; // the label may need more
  const trackTop = track => TL.pad + track * (TL.chipH + TL.gap);

  const label = element('div', 'tl-label');
  label.title = lane.project;
  const [client, ...rest] = lane.project.split(' / ');
  const head = element('span', 'tl-label-head');
  head.append(element('span', 'group-dot'), element('span', 'tl-label-client', rest.length ? client : ''));
  if (lane.undated) {
    const count = element('button', 'tl-label-count', `${lane.undated} undated`);
    count.type = 'button';
    count.tabIndex = -1;
    count.title = `Show the ${plural(lane.undated, 'open action')} of ${lane.project} that have no date, in the tray below`;
    count.addEventListener('click', () => showTray(lane.project, lane.register));
    head.append(count);
  } else head.append(element('span', 'tl-label-done', 'all dated'));
  label.append(head, element('span', 'tl-label-mission', rest.length ? rest.join(' / ') : lane.project));
  // The two buttons of a label are for the pointer: the summary strip, the tray's search and `n` do the same from the keyboard.
  const add = iconButton('icon-button tl-label-add', `Add an action to ${lane.project}`, ICONS.plus);
  add.tabIndex = -1;
  add.addEventListener('click', () => openEditor(null, {register: lane.register}));
  label.append(add);

  const late = element('div', 'tl-late');
  late.setAttribute('role', 'list');
  late.setAttribute('aria-label', `${lane.project}, overdue`);
  const body = element('div', 'tl-days');
  body.setAttribute('role', 'list');
  body.setAttribute('aria-label', `${lane.project}, planned`);
  body.style.width = `${sc.total}px`;
  for (let week = 0; week < span.weeks; week += 1) {
    body.append(absolute('tl-weekline', sc.xs[week * 7], 1), absolute('tl-shade', sc.xs[week * 7 + 5], sc.xs[week * 7 + 7] - sc.xs[week * 7 + 5]));
  }
  const today = span.days.find(day => day.today);
  if (today) body.append(absolute('tl-today', sc.xs[today.index], sc.xs[today.index + 1] - sc.xs[today.index]));
  const showWhen = sc.dayW < 40;
  for (const entry of lane.entries) {
    const top = trackTop(entry.track);
    if (entry.late) {
      const chip = timelineChip(entry, {when: true, spot});
      chip.style.top = `${top}px`;
      late.append(chip);
      continue;
    }
    const chip = timelineChip(entry, {when: showWhen, spot});
    chip.style.left = `${entry.x}px`;
    chip.style.width = `${entry.w}px`;
    chip.style.top = `${top}px`;
    body.append(chip);
    if (entry.marker) {
      const join = absolute('tl-join', entry.marker.x, Math.max(0, entry.x - entry.marker.x));
      join.style.top = `${top + TL.chipH / 2}px`;
      body.append(join, timelineMarker(entry, top));
    }
  }
  node.append(label, late, body);
  return node;
}
function timelineFrieze(span, sc, result, summary, late) {
  const canvas = element('div', 'tl-canvas');
  canvas.style.width = `${sc.labelW + sc.lateW + sc.total}px`;
  canvas.style.setProperty('--label-w', `${sc.labelW}px`);
  canvas.style.setProperty('--late-w', `${sc.lateW}px`);
  canvas.style.setProperty('--head-h', `${sc.density === 'day' ? 78 : 46}px`);
  canvas.append(timelineHead(span, sc, late, summary));
  if (!result.total) {
    const guide = element('p', 'tl-guide');
    const undated = TimelineView.tray(timelineBase).counts;
    guide.textContent = undated.none + undated.vague > 0
      ? 'Nothing is planned in this range. Drag an action from the tray below onto a day to give it a deadline.'
      : 'Nothing is planned in this range. Give an action a due date, or click a day to create one.';
    canvas.append(guide);
  }
  canvas.append(...result.lanes.map(lane => timelineLane(lane, span, sc, timelineSpot)));
  const drop = element('div', 'tl-drop');
  drop.hidden = true;
  drop.setAttribute('aria-hidden', 'true');
  drop.append(element('span', 'tl-drop-label'));
  canvas.append(drop);
  return canvas;
}
function agendaList(label, entries, options) {
  const list = element('div', 'tl-ag-items');
  list.setAttribute('role', 'list');
  list.setAttribute('aria-label', label);
  list.append(...entries.map(entry => timelineChip(entry, options)));
  return list;
}
// One row per day, weekends shaded; the overdue actions first, the weeks under their own headings.
function timelineAgenda(span, result, spot) {
  const root = element('div', 'tl-agenda');
  if (result.late.length) {
    const section = element('section', 'tl-ag-section tl-ag-late');
    section.setAttribute('aria-labelledby', 'tl-ag-late-title');
    const title = element('h3', '', `Overdue (${result.late.length})`);
    title.id = 'tl-ag-late-title';
    section.append(title, agendaList('Overdue actions', result.late, {when: true, where: true, spot}));
    root.append(section);
  }
  const days = TimelineView.agenda(result, span.days);
  for (let first = 0; first < days.length; first += 7) {
    const week = days.slice(first, first + 7);
    const section = element('section', 'tl-ag-section');
    const head = week[0].day;
    const title = element('h3', '', `W${head.week} · ${dayText(week[0].day.iso, SHORT_FORMAT)} to ${dayText(week[6].day.iso, SHORT_FORMAT)}`);
    title.id = `tl-ag-week-${head.weekYear}-${head.week}`;
    section.setAttribute('aria-labelledby', title.id);
    section.append(title);
    for (const {day, entries, markers} of week) {
      const empty = !entries.length && !markers.length;
      const row = element('div', `tl-ag-day${day.weekend ? ' is-weekend' : ''}${day.today ? ' is-today' : ''}${empty ? ' is-empty' : ''}`);
      const date = element('div', 'tl-ag-date');
      date.append(element('span', 'tl-dow', WEEKDAY_FORMAT.format(parseDay(day.iso))), element('span', 'tl-dom', String(day.day)));
      if (day.today) date.append(element('span', 'tl-ag-today', 'Today'));
      row.append(date);
      if (empty) row.setAttribute('aria-hidden', 'true');
      else {
        const list = agendaList(dayText(day.iso), entries, {where: true, spot});
        for (const entry of markers) {
          const marker = element('div', `tl-marker tl-marker-wide ${statusInfo(entry.action.state).cls}`);
          marker.setAttribute('aria-hidden', 'true');
          marker.title = `${entry.id} is scheduled for ${dayText(entry.scheduled)}, due on ${dayText(entry.date)}`;
          marker.append(svgIcon(ICONS.hourglass, 'tl-marker-icon'), element('span', '', entry.id));
          marker.addEventListener('click', () => openFromTimeline(entry.action));
          list.append(marker);
        }
        row.append(list);
      }
      section.append(row);
    }
    root.append(section);
  }
  return root;
}

// The strip under the toolbar: counts of the open actions. Overdue, this week and the next two weeks spotlight those actions (the
// others dim); No deadline and Vague open the tray.
function renderSummary(summary) {
  const windows = {
    overdue: `Due before ${dayText(summary.today, SHORT_FORMAT)}`,
    week: `Due from ${dayText(summary.today, SHORT_FORMAT)} to ${dayText(summary.weekEnd, SHORT_FORMAT)}`,
    next: `Due from ${dayText(summary.nextStart, SHORT_FORMAT)} to ${dayText(summary.nextEnd, SHORT_FORMAT)}`,
    none: 'Open actions with no due date: see the tray',
    vague: 'Open actions whose deadline is a wording, not a date: see the tray'
  };
  ids.timelineSummary.replaceChildren(...TL_STATS.map(stat => {
    const count = summary[stat.key];
    const button = element('button', `tl-stat tl-stat-${stat.key}${count ? '' : ' is-zero'}`);
    button.type = 'button';
    button.dataset.stat = stat.key;
    button.title = windows[stat.key];
    button.append(element('span', 'tl-stat-n', String(count)), element('span', 'tl-stat-label', stat.label));
    if (stat.spot) button.setAttribute('aria-pressed', String(timelineSpot === stat.key));
    else button.setAttribute('aria-controls', 'timelineTray');
    return button;
  }));
}
function setTimelineSpot(kind) {
  timelineSpot = timelineSpot === kind ? '' : kind;
  render();
  if (timelineSpot) ids.timelineScroll.querySelector('.tl-cell:not(.is-dim), .tl-ag-day .tl-cell:not(.is-dim)')?.scrollIntoView({block: 'nearest', inline: 'nearest'});
}

// The tray: open actions with no date, by project, vague deadlines first. Cards are dragged onto a day, or get a date from the menu.
function applyTray() {
  ids.timelineTray.classList.toggle('is-collapsed', !timelineTrayOpen);
  ids.timelineTrayBody.hidden = !timelineTrayOpen;
  ids.timelineTrayToggle.setAttribute('aria-expanded', String(timelineTrayOpen));
}
function setTrayOpen(open) {
  timelineTrayOpen = open;
  applyTray();
  saveUIState();
}
// Open the tray, on a search; `register` (the project the search is about) comes unfolded.
function showTray(query = '', register = '') {
  ids.timelineTraySearch.value = query;
  if (register) for (const kind of ['vague', 'none']) timelineFolded.delete(`${kind}|${register}`);
  setTrayOpen(true);
  renderTray(timelineBase);
  ids.timelineTray.scrollIntoView({block: 'nearest'});
  ids.timelineTraySearch.focus({preventScroll: true});
}
// A row of the tray: status, ID, title (one line, cut at the end; the tooltip has it all), the owner. A vague wording goes on a second,
// small italic line under the title, so the title always wins; a row without one stays on one line.
function trayCard(action, text) {
  const item = element('li', `tl-card ${statusInfo(action.state).cls} ${toneOf(action)}`);
  item.dataset.id = action.id;
  item.draggable = true;
  item.addEventListener('dragstart', event => startTimelineDrag(event, action, 'card'));
  const main = element('button', 'tl-card-main');
  main.type = 'button';
  main.tabIndex = -1;
  main.setAttribute('aria-label', `${action.id}: ${action.title}. Status: ${statusLabel(action.state)}. ${text ? `Deadline: ${text}` : 'No deadline'}. Project: ${action.project}. Owner: ${action.owner}.${action.subtasks?.total ? ` Subtasks: ${subtaskSummary(action)}.` : ''}`);
  main.title = `${action.id} ${action.title}\n${action.project} · ${action.owner}${text ? `\nDeadline: ${text}` : ''}\nDrag onto a day to plan it`;
  const line = element('span', 'tl-card-line');
  line.append(statusIcon(action.state), element('span', 'tl-card-id', action.id), element('span', 'tl-card-title', action.title));
  const pill = subtaskPill(action);
  if (pill) line.append(pill);
  const badge = ownerBadge(action);
  if (badge) line.append(badge);
  main.append(line);
  if (text) main.append(element('span', 'tl-card-note', text));
  const date = iconButton('icon-button tl-card-date', `Set a due date for ${action.id}`, ICONS.calendar, 'Set a due date (d)');
  date.tabIndex = -1;
  date.addEventListener('click', event => { event.stopPropagation(); selectAction(action.id, {focus: false, scroll: false}); openDueMenu(action, date); });
  item.append(main, date);
  item.addEventListener('click', event => { if (!event.target.closest('.tl-card-date')) openFromTimeline(action); });
  return item;
}
// A section of the tray (`kind`: vague or none), one group per project; a group folds to its heading (kept in session storage).
function traySection(kind, title, groups, count) {
  const id = `tl-tray-${kind}`;
  const section = element('section', 'tl-tray-section');
  section.id = id;
  section.setAttribute('aria-labelledby', `${id}-title`);
  const head = element('h3', '');
  head.id = `${id}-title`;
  head.append(element('span', '', title), element('span', 'section-count', String(count)));
  section.append(head);
  const columns = element('div', 'tl-tray-groups');
  groups.forEach((group, index) => {
    const key = `${kind}|${group.register}`;
    const folded = timelineFolded.has(key);
    const box = element('div', `tl-group ${groupTone(group.register)}${folded ? ' is-folded' : ''}`);
    const list = element('ul', 'tl-cards');
    list.id = `${id}-${index}`;
    list.hidden = folded;
    list.append(...group.items.map(item => trayCard(item.action, item.text)));
    const toggle = element('button', 'tl-group-toggle');
    toggle.type = 'button';
    toggle.title = group.project;
    toggle.setAttribute('aria-expanded', String(!folded));
    toggle.setAttribute('aria-controls', list.id);
    toggle.append(svgIcon(ICONS.chevron, 'fold-chevron'), element('span', 'group-dot'), element('span', 'tl-group-text', group.project), element('span', 'tl-group-count', String(group.items.length)));
    toggle.addEventListener('click', () => {
      if (timelineFolded.has(key)) timelineFolded.delete(key); else timelineFolded.add(key);
      const now = timelineFolded.has(key);
      list.hidden = now;
      box.classList.toggle('is-folded', now);
      toggle.setAttribute('aria-expanded', String(!now));
      markSelection(); // the tray's Tab stop goes to a row that is still shown
      saveUIState();
    });
    const name = element('h4', 'tl-group-name');
    name.append(toggle);
    box.append(name, list);
    columns.append(box);
  });
  section.append(columns);
  return section;
}
function renderTray(base) {
  const data = TimelineView.tray(base, {query: ids.timelineTraySearch.value, order: snapshot.registers.map(register => register.path)});
  const all = TimelineView.tray(base, {order: []}).counts;
  ids.timelineTrayCount.textContent = String(all.none);
  ids.timelineTrayMore.textContent = all.vague ? `+ ${all.vague} vague` : '';
  const nodes = [];
  if (data.counts.vague) nodes.push(traySection('vague', 'Vague deadlines', data.vague, data.counts.vague));
  if (data.counts.none) nodes.push(traySection('none', 'No deadline', data.none, data.counts.none));
  if (!nodes.length) {
    nodes.push(element('p', 'tl-tray-empty', all.none + all.vague ? 'No action matches this search.' : 'Every open action has a deadline.'));
  }
  ids.timelineTrayList.replaceChildren(...nodes);
  ids.timelineTray.hidden = false;
  ids.timelineTrayHint.hidden = !(all.none + all.vague);
}

// The time axis follows the width of the page: the frieze is measured, drawn, and drawn again once if a scrollbar took some room.
// A chip is wide enough for a few words of title on each of its three lines; a Quarter, whose days are narrow, gets a narrower one.
// minChipW is the narrowest a chip may shrink to, near the left edge of the range, before it starts on its day instead.
function timelineMetrics(width, key) {
  const wide = width >= 900;
  const chipW = wide ? 170 : 140;
  const quarter = key === 'quarter';
  return {labelW: wide ? 200 : 140, lateW: wide ? 148 : 120, chipW: quarter ? chipW - 30 : chipW, minChipW: quarter ? 72 : wide ? 96 : 84};
}
function syncTimelineControls(summary, span, sc) {
  for (const button of ids.timelineView.querySelectorAll('[data-range]')) button.setAttribute('aria-pressed', String(button.dataset.range === timelineRange));
  ids.timelineDone.setAttribute('aria-checked', String(timelineDone));
  ids.timelineLate.hidden = !summary.overdue;
  ids.timelineLate.textContent = `${summary.overdue} overdue`;
  ids.timelineScale.textContent = `${dayText(span.start, SHORT_FORMAT)} – ${dayText(span.end, DAY_YEAR_FORMAT)} · ${plural(span.weeks, 'week')}${sc && sc.density === 'week' ? ', one tick per week' : ''}`;
  const scrolls = Boolean(sc && sc.overflow);
  ids.timelineBack.hidden = ids.timelineForward.hidden = !scrolls;
  ids.timelineView.classList.toggle('is-agenda', timelineNarrow);
}
function renderTimeline(base) {
  timelineBase = base;
  const now = today();
  const span = TimelineView.range(now, timelineRange);
  timelineNarrow = ids.mainContent.getBoundingClientRect().width < TL.agenda;
  const summary = TimelineView.summary(base, now);
  const late = base.filter(action => !closed(action) && TimelineView.isPlainDate(action.due) && action.due < span.start).length;
  const focused = document.activeElement?.closest?.('#timelineView [data-id]')?.dataset.id || null;
  if (timelineTrayOpen === null) timelineTrayOpen = !timelineNarrow;
  timelineOwners = TimelineView.ownerLabels(snapshot.actions.map(action => action.owner)); // from every action, so a name does not change with the filters
  const order = snapshot.registers.map(register => register.path);
  const options = {today: now, start: span.start, end: span.end, showDone: timelineDone, order};
  let sc = null;
  let result;
  const draw = () => {
    const width = Math.floor(ids.timelineScroll.clientWidth || ids.mainContent.getBoundingClientRect().width);
    const metrics = timelineMetrics(width, span.key);
    sc = timelineNarrow ? null : TimelineView.scale({width, weeks: span.weeks, key: span.key, labelW: metrics.labelW, lateW: late ? metrics.lateW : TL.slim});
    result = TimelineView.layout(base, {...options, scale: sc, chipW: metrics.chipW, minChipW: metrics.minChipW, gap: TL.gap});
    timelineModel = {span, sc, result, summary};
    ids.timelineScroll.replaceChildren(timelineNarrow ? timelineAgenda(span, result, timelineSpot) : timelineFrieze(span, sc, result, summary, late));
    ids.timelineScroll.style.scrollPaddingLeft = sc ? `${sc.labelW + sc.lateW}px` : '0';
    ids.timelineScroll.style.scrollPaddingTop = sc ? (sc.density === 'day' ? '80px' : '48px') : '0';
    return width;
  };
  applyTray();
  ids.timelineView.classList.toggle('is-agenda', timelineNarrow);
  if (!base.some(action => !closed(action)) && !(timelineDone && base.length)) {
    timelineModel = null;
    ids.resultCount.textContent = plural(0, 'action');
    renderSummary(summary);
    syncTimelineControls(summary, span, null);
    ids.timelineTray.hidden = true;
    ids.timelineScroll.replaceChildren(emptyState('No open actions.', 'Open actions appear here as lanes, with a deadline on a day or in the tray.'));
    return;
  }
  const width = draw();
  if (!timelineNarrow && Math.abs(Math.floor(ids.timelineScroll.clientWidth) - width) > 1) draw(); // a scrollbar appeared: fit the new width
  timelineWidth = Math.floor(ids.timelineScroll.clientWidth);
  ids.resultCount.textContent = plural(result.total, 'action');
  syncTimelineControls(summary, span, sc);
  renderSummary(summary);
  renderTray(base);
  if (timelineAnchor) {
    timelineAnchor = false;
    scrollTimelineToToday();
  }
  if (focused) rowFor(focused)?.querySelector(ROW_MAIN)?.focus({preventScroll: true});
}
// Bring today into view: only the scroll case (a range that does not fit), or the agenda, has anything to move.
function scrollTimelineToToday(animate = false) {
  const scroll = ids.timelineScroll;
  const cell = scroll.querySelector(timelineNarrow ? '.tl-ag-day.is-today' : '.tl-today-head');
  if (!cell) return;
  cell.classList.add('is-ping');
  setTimeout(() => cell.classList.remove('is-ping'), 1200);
  const box = scroll.getBoundingClientRect();
  const at = cell.getBoundingClientRect();
  if (timelineNarrow) {
    const top = Math.max(0, at.top - box.top + scroll.scrollTop - 44); // under the sticky week heading
    if (animate) scroll.scrollTo(timelineScrollOptions(0, top)); else scroll.scrollTop = top;
    return;
  }
  if (!timelineModel.sc.overflow) return;
  const left = Math.max(0, at.left - box.left + scroll.scrollLeft - timelineModel.sc.labelW - timelineModel.sc.lateW - at.width * 1.5);
  if (animate) scroll.scrollTo(timelineScrollOptions(left, scroll.scrollTop)); else scroll.scrollLeft = left;
}
function timelineScrollOptions(left, top) {
  return {left, top, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'};
}
function scrollTimelineByWeeks(direction) {
  if (timelineModel?.sc) ids.timelineScroll.scrollBy(timelineScrollOptions(direction * timelineModel.sc.xs[7], 0));
}
// The overdue pill: the first overdue chip, focused.
function focusFirstOverdue() {
  const first = timelineModel?.result.late[0] || timelineModel?.result.lanes.flatMap(lane => lane.entries).find(entry => entry.overdue);
  const chip = first && rowFor(first.id)?.querySelector('.tl-chip');
  if (!chip) return;
  chip.focus({preventScroll: true});
  chip.scrollIntoView({block: 'nearest', inline: 'nearest'});
  selectAction(first.id, {focus: false, scroll: false});
}

// Keyboard: left and right walk a project by date (then by ID), up and down change project on the closest date, Home and End go to the
// ends of the project; Alt+← → moves the deadline by a day (with Shift, a week). In the agenda the arrows follow the list.
const TIMELINE_KEYS = {ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down', Home: 'home', End: 'end'};
function timelineKey(event) {
  const cell = event.target instanceof Element ? event.target.closest('.tl-chip')?.closest('[data-id]') : null;
  if (!cell || event.ctrlKey || event.metaKey || !timelineModel) return;
  if (event.altKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
    event.preventDefault();
    if (pendingWrites > 0) return; // one move at a time: the next one starts from the register as it is after this one
    const action = findAction(cell.dataset.id);
    const next = action && !closed(action) ? TimelineView.moveDue(action.due, (event.key === 'ArrowRight' ? 1 : -1) * (event.shiftKey ? 7 : 1)) : null;
    if (next) updateDue(action, next);
    return;
  }
  const direction = TIMELINE_KEYS[event.key];
  if (!direction || event.altKey || event.shiftKey) return;
  event.preventDefault();
  if (timelineNarrow) {
    if (direction === 'home' || direction === 'end') return;
    moveSelection(direction === 'left' || direction === 'up' ? -1 : 1);
    return;
  }
  const next = TimelineView.neighbour(timelineModel.result.lanes, cell.dataset.id, direction);
  if (next) selectAndFollow(next);
}
// The tray: up and down walk the rows (the ones of a folded group are skipped), Home and End jump to the first and last.
function visibleTrayCards() { return [...ids.timelineTrayList.querySelectorAll('.tl-card')].filter(card => card.offsetParent !== null); }
function trayKey(event) {
  if (!event.target.closest?.('.tl-card-main') || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
  const cards = visibleTrayCards();
  const index = cards.indexOf(event.target.closest('.tl-card'));
  const next = event.key === 'ArrowDown' ? cards[index + 1] : event.key === 'ArrowUp' ? cards[index - 1] : event.key === 'Home' ? cards[0] : event.key === 'End' ? cards.at(-1) : undefined;
  if (next === undefined) return;
  event.preventDefault();
  if (next) selectAndFollow(next.dataset.id);
}

// Dropping: the day under the pointer, from the geometry of the axis.
function timelineDayAt(event) {
  const canvas = ids.timelineScroll.querySelector('.tl-canvas');
  const sc = timelineModel?.sc;
  if (!canvas || !sc) return null;
  const index = TimelineView.dayAt(sc, event.clientX - canvas.getBoundingClientRect().left - sc.labelW - sc.lateW);
  return index < 0 ? null : {index, day: timelineModel.span.days[index], canvas};
}
function showTimelineDrop(target) {
  const drop = ids.timelineScroll.querySelector('.tl-drop');
  if (!drop) return;
  drop.hidden = !target;
  if (!target) return;
  const sc = timelineModel.sc;
  drop.style.left = `${sc.labelW + sc.lateW + sc.xs[target.index]}px`;
  drop.style.width = `${sc.xs[target.index + 1] - sc.xs[target.index]}px`;
  drop.firstChild.textContent = dayText(target.day.iso, DAY_FORMAT);
}
// The due day of a chip lights up while the pointer or the focus is on it: its day in the header (the number, or a label when the
// axis is one tick per week) and its column in the project's lane.
let dueLit = null;
function dueCell(node) { return node instanceof Element ? node.closest('.tl-cell[data-col]') : null; }
function lightDueDay(cell) {
  if (cell === dueLit && (!cell || cell.isConnected)) return;
  dueLit = cell;
  const scroll = ids.timelineScroll;
  for (const node of scroll.querySelectorAll('.tl-dueday, .tl-dueday-head')) node.remove();
  for (const node of scroll.querySelectorAll('.tl-day.is-due')) node.classList.remove('is-due');
  const sc = timelineModel?.sc;
  const column = cell ? Number(cell.dataset.col) : -1;
  if (!sc || !(column >= 0) || !cell.parentElement) return;
  const [left, width] = [sc.xs[column], sc.xs[column + 1] - sc.xs[column]];
  cell.parentElement.append(absolute('tl-dueday', left, width));
  const day = scroll.querySelector(`.tl-day[data-day="${column}"]`);
  if (day) day.classList.add('is-due');
  else {
    const mark = absolute('tl-dueday-head', left, width);
    mark.append(element('span', 'tl-dueday-label', dayText(timelineModel.span.days[column].iso, WHEN_FORMAT)));
    scroll.querySelector('.tl-days-head')?.prepend(mark); // under the month and week labels
  }
}
