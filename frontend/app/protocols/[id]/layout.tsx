import "@/app/styles/protocol.css";

// Editor-CSS nur auf der Protokollseite, nicht in der Liste (S7, CSS-Grenze 400 KB je Seite).
export default function ProtocolLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children;
}
