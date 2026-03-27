"use client";

import { useState } from "react";

export function useSaveStatus() {
  const [status, setStatus] = useState<"saved" | "saving" | "error">("saved");
  return { status, setStatus };
}

