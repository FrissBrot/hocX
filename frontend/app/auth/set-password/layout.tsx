import "@/app/styles/login.css";
import "@/app/styles/invite-setup.css";

import { ConfirmProvider } from "@/contexts/confirm-context";

// Bereichs-CSS dieser Route (design/DESIGN.md Abschnitt 10): Ziffernfelder aus dem Login und die
// Schritte des Erstlogins über eine Einladung. ConfirmProvider für «Später einrichten».
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <ConfirmProvider>{children}</ConfirmProvider>;
}
