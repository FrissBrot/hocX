"use client";

// Mobile-Editor erst laden, wenn die Seite ihn wirklich zeigt (ResponsiveView): auf dem PC gehört
// sein Code samt Tiptap nicht ins erste JavaScript der Protokollseite (Editor 1a, L4). Der
// Mobile-Editor selbst bleibt unverändert.
import dynamic from "next/dynamic";

export const LazyMobileProtocolEditor = dynamic(
  () => import("@/components/mobile/mobile-protocol-editor").then((module) => module.MobileProtocolEditor),
  { loading: () => <div className="protocol-loading" role="status" aria-busy="true" /> }
);
