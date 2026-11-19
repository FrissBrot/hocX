/** Anzeigename aus Vor- und Nachname («Test Timo»), ohne doppelte Leerzeichen. */
export function autoDisplayName(firstName: string, lastName: string): string {
  return `${firstName.trim()} ${lastName.trim()}`.trim();
}

/**
 * Übernimmt eine Änderung an Vor- oder Nachname. Der Anzeigename läuft mit, solange er noch dem
 * automatisch gebildeten Namen entspricht (auch leer); wurde er von Hand geändert, bleibt er stehen.
 */
export function withNameUpdate<T extends { first_name: string; last_name: string; display_name: string }>(
  member: T,
  change: Partial<Pick<T, "first_name" | "last_name">>,
): T {
  const next = { ...member, ...change };
  const followsNames = member.display_name.trim() === autoDisplayName(member.first_name, member.last_name);
  return followsNames ? { ...next, display_name: autoDisplayName(next.first_name, next.last_name) } : next;
}
