"use client";

// Undo/Redo für den Visual Designer. Jeder Schritt ist ein unveränderlicher Schnappschuss
// (siehe layout.ts). Änderungen mit demselben ``mergeKey`` innerhalb kurzer Zeit (Tippen in
// einem Feld, Ziehen eines Reglers) ergeben nur einen Schritt.

import { useCallback, useMemo, useReducer } from "react";

const MERGE_WINDOW_MS = 800;
const MAX_STEPS = 100;

type HistoryState<T> = { past: T[]; present: T; future: T[]; lastKey: string | null; lastAt: number };

type Action<T> =
  | { type: "set"; value: T; mergeKey?: string; at: number }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; value: T };

function reducer<T>(state: HistoryState<T>, action: Action<T>): HistoryState<T> {
  switch (action.type) {
    case "set": {
      if (action.value === state.present) return state;
      const merge = action.mergeKey !== undefined && action.mergeKey === state.lastKey && action.at - state.lastAt < MERGE_WINDOW_MS;
      return {
        past: merge ? state.past : [...state.past, state.present].slice(-MAX_STEPS),
        present: action.value,
        future: [],
        lastKey: action.mergeKey ?? null,
        lastAt: action.at,
      };
    }
    case "undo": {
      if (!state.past.length) return state;
      const previous = state.past[state.past.length - 1];
      return { past: state.past.slice(0, -1), present: previous, future: [state.present, ...state.future], lastKey: null, lastAt: 0 };
    }
    case "redo": {
      if (!state.future.length) return state;
      const [next, ...rest] = state.future;
      return { past: [...state.past, state.present], present: next, future: rest, lastKey: null, lastAt: 0 };
    }
    case "reset":
      return { past: [], present: action.value, future: [], lastKey: null, lastAt: 0 };
  }
}

export function useHistory<T>(initial: T) {
  const [state, dispatch] = useReducer(reducer<T>, { past: [], present: initial, future: [], lastKey: null, lastAt: 0 });
  const set = useCallback((value: T, mergeKey?: string) => dispatch({ type: "set", value, mergeKey, at: Date.now() }), []);
  const undo = useCallback(() => dispatch({ type: "undo" }), []);
  const redo = useCallback(() => dispatch({ type: "redo" }), []);
  const reset = useCallback((value: T) => dispatch({ type: "reset", value }), []);
  return useMemo(
    () => ({ value: state.present, set, undo, redo, reset, canUndo: state.past.length > 0, canRedo: state.future.length > 0 }),
    [state.present, state.past.length, state.future.length, set, undo, redo, reset]
  );
}

export { reducer as historyReducer };
