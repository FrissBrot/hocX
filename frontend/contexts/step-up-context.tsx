"use client";

import { ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { StepUpDialog } from "@/components/security/step-up-dialog";
import { setStepUpHandler } from "@/lib/api/client";

/**
 * Registriert den Step-up-Dialog für browserApiFetch (lib/api/client.ts): meldet das Backend
 * 403 step_up_required, öffnet sich der Dialog, und die Aktion wird nach der Bestätigung einmal
 * wiederholt. Gleichzeitige Anfragen teilen sich einen Dialog.
 */
export function StepUpProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pending = useRef<Promise<boolean> | null>(null);
  const resolver = useRef<((confirmed: boolean) => void) | null>(null);

  const request = useCallback(() => {
    if (pending.current) return pending.current;
    pending.current = new Promise<boolean>((resolve) => {
      resolver.current = resolve;
      setOpen(true);
    });
    return pending.current;
  }, []);

  useEffect(() => setStepUpHandler(request), [request]);

  function done(confirmed: boolean) {
    setOpen(false);
    resolver.current?.(confirmed);
    resolver.current = null;
    pending.current = null;
  }

  return (
    <>
      {children}
      <StepUpDialog open={open} onDone={done} />
    </>
  );
}
