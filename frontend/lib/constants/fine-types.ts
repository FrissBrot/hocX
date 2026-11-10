// Previously a plain constant (duplicated identically in dashboard/dashboard-view.tsx and
// finances/fines-view.tsx before being unified here). Now a function, not a constant: this
// module has no React component to call useTranslations() in, so each caller passes its own
// `t` (usually `useTranslations("finances")`) - see components/ui/section-tabs.ts for the same
// pattern.
type TFunc = (key: string) => string;

export function fineTypeLabels(t: TFunc): Record<string, string> {
  return {
    late: t("fineTypeLate"),
    absent: t("fineTypeAbsent"),
  };
}
