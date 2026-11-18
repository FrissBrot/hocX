export function StatusBanner({
  tone,
  message
}: {
  tone: "neutral" | "success" | "warning" | "error";
  message: string;
}) {
  return <p className={`status-banner status-${tone}`} role={tone === "warning" || tone === "error" ? "alert" : undefined}>{message}</p>;
}
