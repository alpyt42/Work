'use strict';

// The sideways scroll that moves to the previous or the next brain: two fingers on a trackpad, or Shift and the wheel of a mouse.
// It comes as a burst of wheel events; the burst is one gesture until the events stop for GAP ms, its momentum included.
// A gesture counts only when it starts mostly
// sideways and nothing under the pointer can scroll that way (the Board and the Timeline keep their own sideways scrolling);
// it switches once, when its sideways travel passes THRESHOLD, and the rest of the burst is swallowed.
// No DOM here: the page feeds each wheel event to `step` and applies what it returns; the tests run this same file under node.
const BrainSwipe = (() => {
  const GAP = 180;         // ms without an event that end a gesture
  const START = 6;         // px of travel before the gesture's direction is judged
  const SIDEWAYS = 1.5;    // a swipe moves at least this many times more sideways than up or down
  const THRESHOLD = 100;   // px of sideways travel that switch brain: a short flick is enough

  function idle() { return {phase: 'idle', at: -Infinity, dx: 0, dy: 0}; }

  // One wheel event: {dx, dy, time (ms), ignore (a pinch, a text field…), scrollsLeft, scrollsRight (something under
  // the pointer can still scroll that way)}. Returns {state, prevent (cancel the browser's own handling), action}, where action is
  // null, {type: 'progress', direction, amount} (amount from 0 to 1) or {type: 'switch', direction}; direction 1 is the next brain.
  function step(state, event) {
    const fresh = event.time - state.at > GAP;
    const next = fresh ? {phase: 'deciding', at: event.time, dx: 0, dy: 0} : {...state, at: event.time};
    if (next.phase === 'ignored' || (next.phase === 'deciding' && event.ignore)) {
      return {state: {...next, phase: 'ignored'}, prevent: false, action: null};
    }
    if (next.phase === 'done') return {state: next, prevent: true, action: null};
    next.dx += event.dx;
    next.dy += event.dy;
    if (next.phase === 'deciding') {
      const sideways = Math.abs(next.dx) >= SIDEWAYS * Math.abs(next.dy);
      const blocked = next.dx > 0 ? event.scrollsRight : event.scrollsLeft;
      if (Math.abs(next.dx) + Math.abs(next.dy) < START) {
        // Too short to judge: hold the browser back only when its own back-and-forward swipe would take it.
        return {state: next, prevent: sideways && !blocked && next.dx !== 0, action: null};
      }
      if (!sideways || blocked) return {state: {...next, phase: 'ignored'}, prevent: false, action: null};
      next.phase = 'tracking';
    }
    const direction = next.dx > 0 ? 1 : -1;
    if (Math.abs(next.dx) >= THRESHOLD) return {state: {...next, phase: 'done'}, prevent: true, action: {type: 'switch', direction}};
    return {state: next, prevent: true, action: {type: 'progress', direction, amount: Math.abs(next.dx) / THRESHOLD}};
  }

  // Called once the events stopped for GAP ms: a gesture left halfway is withdrawn ({type: 'cancel'}), anything else ends quietly.
  function settle(state) {
    return {state: idle(), action: state.phase === 'tracking' ? {type: 'cancel'} : null};
  }

  return {GAP, THRESHOLD, idle, step, settle};
})();
if (typeof module !== 'undefined') module.exports = BrainSwipe;
