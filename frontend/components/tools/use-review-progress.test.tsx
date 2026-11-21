// Word-Import «Neu analysieren?»: frisch geladener Stand gilt nie als Prüffortschritt, auch wenn
// Effekte ohne Änderung erneut laufen (StrictMode, Fast Refresh im Dev-Server).
import { StrictMode, type ReactNode } from "react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useReviewProgress } from "./use-review-progress";

const strict = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>;

describe("useReviewProgress", () => {
  it("bleibt nach dem Laden ohne Änderung ohne Fortschritt, auch bei erneuten Effektläufen", () => {
    const texts = [{ id: 1 }];
    const lists: unknown[] = [];
    const { result, rerender } = renderHook(({ values }) => useReviewProgress(values), {
      wrapper: strict,
      initialProps: { values: [[], []] as unknown[] },
    });
    expect(result.current.hasProgress()).toBe(false);
    result.current.reset([texts, lists], false);
    rerender({ values: [texts, lists] });
    rerender({ values: [texts, lists] });
    expect(result.current.hasProgress()).toBe(false);
  });

  it("meldet Fortschritt nach einer echten Änderung und setzt beim nächsten Laden zurück", () => {
    const texts = [{ id: 1 }];
    const lists: unknown[] = [];
    const { result, rerender } = renderHook(({ values }) => useReviewProgress(values), {
      wrapper: strict,
      initialProps: { values: [texts, lists] as unknown[] },
    });
    result.current.reset([texts, lists], false);
    const edited = [{ id: 1, approved: true }];
    rerender({ values: [edited, lists] });
    expect(result.current.hasProgress()).toBe(true);

    const reanalyzed = [{ id: 2 }];
    result.current.reset([reanalyzed, lists], false);
    rerender({ values: [reanalyzed, lists] });
    expect(result.current.hasProgress()).toBe(false);
  });

  it("ein wiederhergestellter Entwurf zählt als Fortschritt", () => {
    const draftTexts = [{ id: 1 }];
    const { result, rerender } = renderHook(({ values }) => useReviewProgress(values), {
      wrapper: strict,
      initialProps: { values: [[]] as unknown[] },
    });
    result.current.reset([draftTexts], true);
    rerender({ values: [draftTexts] });
    expect(result.current.hasProgress()).toBe(true);
  });
});
