import { redirect } from "next/navigation";

// Gestaltungs-Komponenten liegen seit dem Bereich «Vorlagen» bei den Bausteinen.
export default function Page() {
  redirect("/elements");
}
