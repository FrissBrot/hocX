// Öffentliche Statusseite (HOCX_STATUS_PAGE_URL, optional): Die Update-Seite verweist darauf, wenn
// ein Update länger dauert. Nur einfache https-Adressen - gleiche Regel wie deploy.sh
// (DEPLOY_STATUS_URL_RE) und infra/maintenance/maintenance.html (STATUS_URL_RE).
const STATUS_URL_RE = /^https:\/\/[A-Za-z0-9.-]+(:[0-9]{1,5})?(\/[A-Za-z0-9._~/-]*)?$/;

export function cleanStatusPageUrl(raw: string | null | undefined): string | null {
  const value = (raw ?? "").trim();
  return STATUS_URL_RE.test(value) ? value : null;
}
