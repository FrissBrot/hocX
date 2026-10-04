import { BadgeVariant } from "@/components/ui/badge";

export function protocolStatusLabel(status: string, t: (key: string) => string): string {
  switch (status) {
    case "geplant":
      return t("status.geplant");
    case "vorbereitet":
      return t("status.vorbereitet");
    case "durchgeführt":
      return t("status.durchgeführt");
    case "abgeschlossen":
      return t("status.abgeschlossen");
    default:
      return status;
  }
}

export function protocolStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "geplant":
      return "info";
    case "vorbereitet":
      return "warning";
    case "durchgeführt":
      return "success";
    case "abgeschlossen":
      return "neutral";
    default:
      return "neutral";
  }
}
