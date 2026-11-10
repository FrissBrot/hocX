// Avatare von Personen (Klassen .participant-avatar und -tone-0 … -4 in globals.css): Initialen
// und ein stabiler Farbton aus der ID, damit ein Avatar beim Umbenennen seine Farbe behält.

type Named = { display_name: string; first_name?: string | null; last_name?: string | null };

/** Initialen bevorzugt aus Vor-/Nachname (Übernamen wie "Kiwi" sagen wenig), sonst aus dem Anzeigenamen. */
export function participantInitials(participant: Named): string {
  if (participant.first_name && participant.last_name) {
    return (participant.first_name[0] + participant.last_name[0]).toUpperCase();
  }
  const parts = participant.display_name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Stabiler Farbton (0-4) aus der ID. */
export function avatarTone(key: string): number {
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  return Math.abs(hash) % 5;
}
