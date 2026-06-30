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

export function protocolStatusClassName(status: string): string {
  switch (status) {
    case "geplant":
      return "status-pill-planned";
    case "vorbereitet":
      return "status-pill-prepared";
    case "durchgeführt":
      return "status-pill-conducted";
    case "abgeschlossen":
      return "status-pill-completed";
    default:
      return "";
  }
}
