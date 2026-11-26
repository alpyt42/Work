# Corvus

Corvus is the local app of Work: it shows the actions and the notes of your brains, and lets you change them without an agent. It opens in a window of its own on macOS, Windows and Linux, or in a browser tab. Everything stays on your computer: the server listens on `127.0.0.1` only, keeps no copy of your data and writes every change into the brain's own Markdown files, which your agents read too. Back to the [root README](../../README.md).

![Corvus on macOS: the Today view, with the rail of views and the project card](../../docs/images/tasks-web-today.png)

This guide first lists what Corvus does, then shows how its parts fit together, how to install it and how to launch it. It ends with a tour of the views and the keyboard shortcuts.

## What it does

Corvus brings the registers of every brain into one window, so that the day's work can be read and updated in a few clicks.

- Today gathers what is overdue, due today, in progress, waiting on someone else and due in the week ahead.
- Every action can be changed in place (status, owner, due date, priority, subtasks, notes), and every change can be undone.
- The Board, the Timeline and the Docs view show the same actions as columns, as dates and next to the notes of each project.
- One search field looks through the actions and every Markdown document of the brain.
- A selector switches between your brains without restarting anything, and each brain keeps its own colour and logo.
- Sync saves and sends the changes of each brain, and brings in the changes made on another computer.
- The sidebar and the detail panel can be resized, and the page follows the light or dark setting of the system.

## How it works

The window only displays a page. A small server on your computer reads the brains and writes the changes, and Sync is the only part that talks to the network.

```mermaid
flowchart LR
  W["Corvus window<br/>or a browser tab"] -- "HTTP on 127.0.0.1:8765" --> S["Local server<br/>tasks-web.py"]
  S -- "Reads and writes<br/>through action.py" --> B["Brains<br/>Markdown and Git"]
  B -- "Sync: save, send,<br/>check, bring in" --> R["Each brain's<br/>online copy"]
```

The diagram shows why Corvus and your agents never disagree: both go through the same files and the same `action.py` rules, and a brain only leaves the computer when you ask Sync to send it. The page itself loads nothing from the Internet (no CDN, no outside font or script). Two features use the network: Sync, with each brain's own Git remote, and Update, which looks for a newer release of Work.

## Install and launch

Corvus can be installed as an app or started from a terminal; both open the same page.

**As an app.** Run this once from the root of Work:

```sh
uv run tools/tasks-web/install-app.py
```

It adds a **Corvus** entry: an app to drag to the Dock on macOS, a Start Menu shortcut on Windows, an entry of the applications menu on Linux. A click starts the local server when it is not running and opens the page. On macOS and Windows it opens in a native window (pywebview, downloaded once by `uv` at install). On Linux, and whenever the native window cannot open, it opens in a Chrome, Chromium or Edge app window, and failing that in the default browser. Clicking the icon again brings back the open window. **Quit Corvus…**, in the **⋯** menu, stops the server and closes the window; closing the window alone leaves the server running, so the next launch is immediate.

**From a terminal.** From the root of Work:

```sh
uv run tools/tasks-web/tasks-web.py
```

Then open `http://127.0.0.1:8765/` (`--port N` for another port, `Ctrl+C` to stop). `--brain <folder>` picks the default brain and `WORK_DIR` another Work root. The details of each system are in [Install the app](REFERENCE.md#install-the-app).

## Tour

The tour follows the sidebar from top to bottom: the views of the day, then the brains, Sync and the window itself.

### Today

The opening view lists your overdue actions, those due today, those in progress, the follow-ups to make with others and what you wait on, then the week ahead. Each action appears once, in the first section that fits.

### Priorities

The ranking written by the `/priorities` agent skill for the current brain: what to do now, what to prepare, the conflicts and the follow-ups. An action ID in an item opens that action, and each follow-up carries a draft of the message with a button to copy it.

![The Priorities view](../../docs/images/tasks-web-priorities.png)

### Actions and the detail panel

Actions are listed by project and group, each with its progress and its overdue count. A click on the status or the due date changes it in place; a click on a row opens the detail panel with the fields, the subtasks and the history of notes. Every write goes through `action.py` and can be undone. Dragging the left edge of the panel widens it.

![Actions grouped by project](../../docs/images/tasks-web-actions.png)

![An action in the detail panel](../../docs/images/tasks-web-action-panel.png)

### Board

Four columns, To do, In progress, Waiting and Recently done. Dragging a card changes its status. The board shows your own cards unless you switch to Everyone.

![The Board](../../docs/images/tasks-web-board.png)

### Timeline

The actions with a deadline sit on a chronological frieze (2 weeks, 6 weeks or a quarter), one lane per project, overdue first. Those without a deadline wait in a tray below: dropping one on a day plans it.

![The Timeline](../../docs/images/tasks-web-timeline.png)

### Docs and search

The notes, sources, workstreams, journal and project pages of the brain, with a reader and a Markdown editor for working notes. The search field, in every view, looks through the actions and every Markdown document at once.

![Docs, with a note open](../../docs/images/tasks-web-docs.png)

### Brains

The brain's name at the top of the sidebar opens the brain menu: it switches brain without restarting the server, and **Add brain** creates a new private brain with its own Git repository. Each brain has its own colour and pixel logo, so the brain being edited is always visible. A sideways swipe over the sidebar moves to the next brain.

![The brain menu](../../docs/images/tasks-web-brain-menu.png)

### Sync

Each brain is a Git repository. The Sync view shows one card per brain and says what is waiting: notes to save and send, or changes made on another computer. **Save and send** records the changed notes and sends them to the brain's online copy, through the brain's own Git hooks. Corvus checks the online copies when it opens and every ten minutes; when a brain is behind, its card and the sidebar offer **Sync**, which brings the changes in as a fast-forward only, never with a merge commit or a rewrite of history.

![The Sync view, with a brain to bring up to date](../../docs/images/tasks-web-sync.png)

### Sidebar, window and dark mode

On the left, a rail holds the views and, at the bottom, Archives, Tools, Sync and Settings. Next to it, the project card lists the projects of the brain; its edge can be dragged to widen it. The sidebar button, or the `[` key, folds the card away; the pointer on a view then shows the card over the page, with that view named above the projects, and a project chosen there opens in that view. On macOS the window has no separate title bar: its three buttons sit at the top of the rail. The page follows the light or dark setting of the system.

![The card folded away, shown again over the page from the Timeline icon, in dark mode](../../docs/images/tasks-web-rail-dark.png)

### Update

When a newer release of Work exists, an **Update** button appears in the sidebar. The dialog shows the release notes and, once confirmed, a step bar through the install; the brains are never touched.

![The Update dialog with its step bar](../../docs/images/tasks-web-update.png)

## Keyboard shortcuts

The single keys do not apply while typing in a field. `?` shows their help, and the tooltips recall them.

| Key | Effect |
|---|---|
| `/` | Search the actions and the documents |
| `n` | New action |
| `0` to `5` | Priorities, Today, Actions, Board, Timeline, Docs |
| `j` `k`, `↓` `↑` | Next or previous action (Today, Actions, Board, Timeline) |
| `←` `→` `↑` `↓` | On a Timeline chip: by date, and by project |
| Alt `←` `→` | On a Timeline chip: move its deadline by a day (with Shift, a week) |
| Enter | Open the details of the selected action |
| `s` | Status menu of the selected action |
| `d` | Due date of the selected action |
| Esc | Close the menu, the drawer or the panel; in the search field, clear it and go back to the view it left |
| ⌘ Enter | Save the panel now, create the action, or save the note being edited |
| ⌘ Z | Undo the last write |
| `[` | Fold the project card or the sidebar, or open it again (the drawer, under 900 px) |
| `?` | Shortcuts help |
| ⌘ B, I, U, K, ⇧ ⌘ X | In a note being written: bold, italic, underline, link, strikethrough |

In a list, only the selected row (otherwise the first one) is in the tab order: Tab goes through its buttons, and `j` and `k` move to the others.

## Reference

[`REFERENCE.md`](REFERENCE.md) holds the details:
- [Install the app](REFERENCE.md#install-the-app) and the [layout](REFERENCE.md#layout).
- The views and their routes: [Priorities](REFERENCE.md#priorities), [Today](REFERENCE.md#today), [Actions](REFERENCE.md#actions-and-detail-panel), [Board](REFERENCE.md#board), [Timeline](REFERENCE.md#timeline), [Groups](REFERENCE.md#groups), [Docs and Search](REFERENCE.md#docs-and-search), [Archives](REFERENCE.md#archives), [Tools](REFERENCE.md#tools), [Sync](REFERENCE.md#sync), [Update](REFERENCE.md#update) and [Settings](REFERENCE.md#settings).
- [Several brains](REFERENCE.md#several-brains).
- The [priorities file format](REFERENCE.md#priorities-file).
- [Data and security](REFERENCE.md#data-and-security).
- The [code layout](REFERENCE.md#code-layout).
