export function StatusBanner({
  tone,
  message
}: {
  tone: "neutral" | "success" | "error";
  message: string;
}) {
  return <p className={`status-banner status-${tone}`}>{message}</p>;
}
