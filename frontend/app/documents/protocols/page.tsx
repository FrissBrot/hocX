import { redirect } from "next/navigation";

// Früher eigene Seite für die Gestaltung der Sitzungsdokumente; seit «Gestaltung auf Abruf»
// stehen Sitzungs- und weitere Dokumente gemeinsam unter «Dokumentvorlagen».
export default function Page() {
  redirect("/documents");
}
