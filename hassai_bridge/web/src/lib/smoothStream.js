import { useEffect, useRef, useState } from "react";

/**
 * Reveal `target` smoothly while `active` (ChatGPT-like flow).
 * Catches up faster when far behind big network chunks; ~1–3 chars/frame when close.
 */
export function useSmoothStreamText(target, active) {
  const raw = String(target || "");
  const [shown, setShown] = useState(raw);
  const shownRef = useRef(raw);
  const targetRef = useRef(raw);
  const activeRef = useRef(Boolean(active));

  targetRef.current = raw;
  activeRef.current = Boolean(active);

  // Snap when not streaming (final markdown / history load).
  useEffect(() => {
    if (active) return;
    shownRef.current = raw;
    setShown(raw);
  }, [active, raw]);

  // One rAF loop for the whole streaming turn — don't restart on every chunk.
  useEffect(() => {
    if (!active) return undefined;

    let raf = 0;
    let lastTs = 0;

    const tick = (ts) => {
      if (!activeRef.current) {
        shownRef.current = targetRef.current;
        setShown(targetRef.current);
        return;
      }

      const goal = targetRef.current;
      let cur = shownRef.current;

      if (!goal.startsWith(cur) && cur !== goal) {
        // Prefix mismatch (edit/retry) — jump to the longest shared prefix then continue.
        let i = 0;
        const n = Math.min(cur.length, goal.length);
        while (i < n && cur[i] === goal[i]) i += 1;
        cur = goal.slice(0, i);
        shownRef.current = cur;
        setShown(cur);
      }

      if (cur.length < goal.length) {
        const dt = lastTs ? Math.min(33, ts - lastTs) : 16;
        lastTs = ts;
        const behind = goal.length - cur.length;
        const perMs = behind > 160 ? 0.6 : behind > 64 ? 0.3 : behind > 20 ? 0.15 : 0.1;
        let step = Math.max(1, Math.round(perMs * dt));
        if (behind > 200) step = Math.max(step, Math.ceil(behind / 16));
        const next = goal.slice(0, cur.length + step);
        shownRef.current = next;
        setShown(next);
      } else {
        lastTs = ts;
      }

      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active]);

  return active ? shown : raw;
}
