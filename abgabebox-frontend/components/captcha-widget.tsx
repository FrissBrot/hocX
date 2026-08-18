"use client";

import { useEffect, useId, useRef } from "react";

declare global {
  interface Window {
    [key: string]: unknown;
  }
}

const SCRIPT_SRC = "/friendly-challenge.module.min.js";
const SCRIPT_ID = "friendly-captcha-script";

type Props = {
  sitekey: string;
  onSolved: (solution: string) => void;
  onExpired?: () => void;
  widgetRef?: React.RefObject<HTMLDivElement | null>;
};

export function CaptchaWidget({ sitekey, onSolved, onExpired, widgetRef }: Props) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const callbackName = `frcCallback_${id}`;
  const expiredCallbackName = `frcExpired_${id}`;
  const internalRef = useRef<HTMLDivElement>(null);
  const ref = widgetRef ?? internalRef;

  useEffect(() => {
    window[callbackName] = onSolved;
    window[expiredCallbackName] = () => onExpired?.();

    if (!document.getElementById(SCRIPT_ID)) {
      const script = document.createElement("script");
      script.id = SCRIPT_ID;
      script.src = SCRIPT_SRC;
      script.type = "module";
      script.async = true;
      document.body.appendChild(script);
    }

    // Zweiter Signalweg neben data-callback: das Widget schreibt die geloeste Antwort immer in
    // data-response, unabhaengig davon ob der Callback zuverlaessig feuert (z.B. wenn das Skript
    // erst nach der Widget-Initialisierung nachlaedt) - onSolved dedupliziert mehrfache Aufrufe
    // mit derselben Loesung selbst.
    const node = ref.current;
    let observer: MutationObserver | null = null;
    if (node) {
      observer = new MutationObserver(() => {
        const response = node.getAttribute("data-response");
        if (response && response !== ".") onSolved(response);
      });
      observer.observe(node, { attributes: true, attributeFilter: ["data-response"] });
    }

    return () => {
      delete window[callbackName];
      delete window[expiredCallbackName];
      observer?.disconnect();
    };
  }, [callbackName, expiredCallbackName, onSolved, onExpired, ref]);

  if (!sitekey) return null;

  return (
    <div
      ref={ref}
      className="frc-captcha"
      data-sitekey={sitekey}
      data-callback={callbackName}
      data-expired-callback={expiredCallbackName}
      data-lang="de"
      data-start="auto"
      data-puzzle-endpoint="https://api.friendlycaptcha.com/api/v1/puzzle"
      data-worker-src="/friendly-challenge.worker.min.js"
    />
  );
}
