"use client";

import { createContext, useContext, useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

const STEP_KEYS = ["assignment", "element", "upload"] as const;

// Der aktuelle Schritt ergibt sich aus der Route (/<token>, /<token>/<abgabe>,
// /<token>/<abgabe>/<element>). Nur "Fertig" nach erfolgreichem Upload ist reiner
// Client-Zustand des Upload-Formulars - der meldet ihn ueber diesen Kontext.
type FlowContextValue = { done: boolean; setDone: (done: boolean) => void };

const FlowContext = createContext<FlowContextValue>({ done: false, setDone: () => {} });

export function FlowProvider({ children }: { children: React.ReactNode }) {
  const [done, setDone] = useState(false);
  return <FlowContext.Provider value={{ done, setDone }}>{children}</FlowContext.Provider>;
}

export function useFlowDone() {
  return useContext(FlowContext).setDone;
}

function useCurrentStep(): number | null {
  const pathname = usePathname() ?? "/";
  const { done } = useContext(FlowContext);
  const depth = pathname.split("/").filter(Boolean).length;
  if (depth === 0) return null;
  if (depth >= 3 && done) return STEP_KEYS.length;
  return Math.min(depth, STEP_KEYS.length) - 1;
}

// Desktop: senkrechte Schrittliste in der Seitenleiste.
export function FlowStepList() {
  const t = useTranslations("abgabebox.flow");
  const current = useCurrentStep();
  if (current === null) return null;
  return (
    <ol className="flow-steps">
      {STEP_KEYS.map((key, i) => {
        const state = i < current ? "done" : i === current ? "active" : "todo";
        return (
          <li key={key} className={`flow-step flow-step-${state}`} aria-current={state === "active" ? "step" : undefined}>
            <span className="flow-step-mark">{state === "done" ? "✓" : i + 1}</span>
            <span className="flow-step-text">
              <span className="flow-step-label">{t(`steps.${key}.label`)}</span>
              <span className="flow-step-hint">{t(`steps.${key}.hint`)}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

// Mobile: "Schritt x von 3" plus Fortschrittsbalken in der Kopfzeile.
export function FlowStepBar() {
  const t = useTranslations("abgabebox.flow");
  const current = useCurrentStep();
  if (current === null) return null;
  return (
    <div className="flow-bar">
      <span className="flow-bar-text">
        {current < STEP_KEYS.length ? t("stepOf", { step: current + 1, total: STEP_KEYS.length }) : t("finished")}
      </span>
      <span className="flow-bar-track" aria-hidden="true">
        {STEP_KEYS.map((key, i) => (
          <span key={key} className={`flow-bar-segment${i <= current ? " flow-bar-segment-on" : ""}`} />
        ))}
      </span>
    </div>
  );
}
