'use strict';

// Runs before the first paint (no defer), so that nothing moves once the page shows.
// 1. The widths the person chose by dragging the handles of the sidebar, of the Mac window's card and of the detail panel
//    (app/shell.js keeps them under `corvus-width<variable>`).
// 2. Corvus's macOS window (window.py) opens the page with ?shell=mac: its title bar is transparent and the page runs under it,
//    like the other Mac apps. The page is marked, so that app.css leaves room for the window buttons and lays the sidebar out in
//    two columns. The mark is kept for the reloads of that window, which may drop the query. A browser tab never gets it.
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
  if (shell !== 'mac') return;
  try { sessionStorage.setItem(KEY, shell); } catch { /* the mark is only lost on reload */ }
  document.documentElement.classList.add('mac-window');
})();
