import { parseDocumentId } from "@/lib/verify";

// Logo eines Mandanten für die Prüfseite, serverseitig über das interne Netz vom Hauptbackend
// (öffentlicher Endpoint /api/tenants/{public_id}/profile-image). Same-origin, damit die CSP der
// Abgabebox bei img-src 'self' bleiben kann (sie wird beim Build festgelegt, das Release-Image
// kennt die Hauptdomain nicht). Die Prüfseite zeigt das Logo nur, wenn der Mandant die Anzeige
// freigegeben hat (View document_verification_public); auch das XMP der PDFs enthält die
// public_id nur dann. Das Profilbild selbst ist über den Hauptendpunkt ohnehin öffentlich - diese
// Route ist kein Zugriffsschutz, sondern nur ein same-origin-Proxy.
const backendBase = process.env.HOCX_INTERNAL_API_URL ?? "http://backend:8000";
const MAX_BYTES = 2 * 1024 * 1024;
// Nur Rasterformate - ein SVG wäre same-origin ausgeliefert ein aktives Dokument.
const ALLOWED_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);

export async function GET(_request: Request, { params }: { params: Promise<{ tenantId: string }> }) {
  const { tenantId } = await params;
  const id = parseDocumentId(tenantId);
  if (!id) {
    return new Response(null, { status: 404 });
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${backendBase}/api/tenants/${id}/profile-image`, { cache: "no-store", redirect: "error" });
  } catch {
    return new Response(null, { status: 502 });
  }
  const type = (upstream.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (!upstream.ok || !ALLOWED_TYPES.has(type)) {
    return new Response(null, { status: 404 });
  }
  const body = await upstream.arrayBuffer();
  if (body.byteLength > MAX_BYTES) {
    return new Response(null, { status: 404 });
  }
  return new Response(body, {
    headers: {
      "Content-Type": type,
      "Cache-Control": "public, max-age=300",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'; sandbox",
    },
  });
}
