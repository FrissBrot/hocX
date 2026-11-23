import "@/app/styles/block-config.css";
import "@/app/styles/event-dialog.css";
import "@/app/styles/events-protocols.css";
import "@/app/styles/lists-protocols.css";
import "@/app/styles/protocol-list.css";

// Bereichs-CSS dieser Route (design/DESIGN.md Abschnitt 10). Das Editor-CSS lädt nur
// protocols/[id] (eigenes Layout), die Liste braucht es nicht (S7).
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
