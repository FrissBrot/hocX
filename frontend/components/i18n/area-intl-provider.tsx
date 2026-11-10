import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

import { extraAreaNamespaces, pickNamespaces, type MessageArea } from "@/lib/i18n/message-scopes";

// Server Component fuer die layout.tsx eines Bereichs: liefert dem Client die globalen plus die
// Bereichs-Namespaces aus (siehe lib/i18n/message-scopes.ts). Der verschachtelte Provider
// ersetzt die Messages des Root-Layouts vollstaendig, deshalb immer inkl. GLOBAL_NAMESPACES.
// Liefert das Root-Layout schon alles Noetige aus, entfaellt der zusaetzliche Provider.
export async function AreaIntlProvider({
  area,
  children,
}: Readonly<{ area: MessageArea; children: React.ReactNode }>) {
  const namespaces = extraAreaNamespaces(area);
  if (!namespaces) {
    return <>{children}</>;
  }
  const messages = pickNamespaces(await getMessages(), namespaces);
  return <NextIntlClientProvider messages={messages}>{children}</NextIntlClientProvider>;
}
