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
  widgetRef?: React.RefObject<HTMLDivElement>;
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

    return () => {
      delete window[callbackName];
      delete window[expiredCallbackName];
    };
  }, [callbackName, expiredCallbackName, onSolved, onExpired]);

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
