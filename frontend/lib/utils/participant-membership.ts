/** Ein- und Austrittsdatum gehören beide noch zur Mitgliedschaft. */
export function participantEligibleOn(
  participant: { joined_at?: string | null; left_at?: string | null },
  asOf: string,
): boolean {
  return (!participant.joined_at || participant.joined_at <= asOf)
    && (!participant.left_at || participant.left_at >= asOf);
}

export function localDateToday(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
