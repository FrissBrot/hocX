import { redirect } from "next/navigation";

// Früher eigene Seite der Pendenzen-Bussen: die Bussen stehen jetzt gemeinsam unter /fines, Regeln
// und Tarife unter Konfiguration > Bussen-Konfiguration (/fine-settings). Alte Links leiten um.
export default function TodoFinesPage() {
  redirect("/fines");
}
