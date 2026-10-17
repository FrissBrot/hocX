import { NextRequest, NextResponse } from "next/server";

import { contentSecurityPolicy, createNonce, NONCE_HEADER } from "@/lib/csp";

// Nonce-CSP (Security-Audit SEC-012): pro Request eine neue Nonce auf Request (für Next und
// app/layout.tsx) und Antwort. Gleiches Muster wie frontend/proxy.ts.
export function proxy(request: NextRequest) {
  const nonce = createNonce();
  const csp = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(NONCE_HEADER, nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: ["/((?!api/|api$|_next/static|_next/image|favicon\\.ico|robots\\.txt|friendly-challenge).*)"],
};
