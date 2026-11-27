'use strict';

// Runs before the first paint (no defer), so that nothing moves once the page shows.
// 1. The widths the person chose by dragging the handles of the sidebar, of the app window's card and of the detail panel
//    (app/shell.js keeps them under `corvus-width<variable>`).
// 2. A Corvus window opens the page with ?shell=mac (the macOS window of window.py) or ?shell=app (its window on Windows and Linux,
//    and the app window of launch.py's fallback). Both get the mark `app-window`, the layout of the app: a 52 px top row and a
//    sidebar of two columns (app.css). The macOS window also gets `mac-window`: its title bar is transparent and the page runs
//    under it, like the other Mac apps, so the page leaves room for the window buttons and the window moves by its empty parts.
//    The marks are kept for the reloads of that window, which may drop the query. A browser tab never gets them.
(() => {
  for (const variable of ['--sidebar-full-w', '--list-w', '--panel-w']) {
    let width = '';
    try { width = localStorage.getItem(`corvus-width${variable}`) || ''; } catch { /* no storage: the default widths */ }
    if (/^\d{2,4}px$/.test(width)) document.documentElement.style.setProperty(variable, width);
  }
})();
(() => {
  const KEY = 'corvus-shell';
  let shell = '';
  try { shell = new URLSearchParams(location.search).get('shell') || sessionStorage.getItem(KEY) || ''; } catch { /* no storage */ }
  if (shell !== 'mac' && shell !== 'app') return;
  try { sessionStorage.setItem(KEY, shell); } catch { /* the mark is only lost on reload */ }
  document.documentElement.classList.add('app-window');
  if (shell === 'mac') document.documentElement.classList.add('mac-window');
})();
