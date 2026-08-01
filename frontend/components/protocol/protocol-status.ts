import { BadgeVariant } from "@/components/ui/badge";

export function protocolStatusLabel(status: string): string {
  switch (status) {
    case "geplant":
      return "Geplant";
    case "vorbereitet":
      return "Vorbereitet";
    case "durchgeführt":
      return "Durchgeführt";
    case "abgeschlossen":
      return "Abgeschlossen";
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
