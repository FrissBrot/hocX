"use client";

import type { CollaboratorInfo } from "@/lib/hooks/use-protocol-collaboration";

const AVATAR_COLORS = ["#e07a5f", "#3d8bfd", "#588157", "#9c6ade", "#e8a33d", "#2a9d8f", "#d1495b"];

function colorForUser(userId: string): string {
  // userId is now a UUID string rather than a small integer, so derive a stable numeric
  // hash from its characters instead of relying on it already being a number.
  let hash = 0;
  for (let i = 0; i < userId.length; i += 1) {
    hash = (hash * 31 + userId.charCodeAt(i)) | 0;
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function CollaboratorAvatar({ user }: { user: CollaboratorInfo }) {
  return (
    <span
      className="collab-avatar"
      style={{ backgroundColor: colorForUser(user.user_id) }}
      title={user.display_name}
    >
      {initials(user.display_name)}
    </span>
  );
}

export function CollaborationPresenceBar({ users, connected }: { users: CollaboratorInfo[]; connected: boolean }) {
  return (
    <div className="collab-presence-bar" title={connected ? undefined : "Live-Kollaboration nicht verfügbar"}>
      {users.map((user) => (
        <CollaboratorAvatar key={user.user_id} user={user} />
      ))}
      {!connected && <span className="collab-presence-offline">Offline</span>}
    </div>
  );
}

export function LockBadge({ holder }: { holder: CollaboratorInfo }) {
  return (
    <span className="collab-lock-badge" style={{ borderColor: colorForUser(holder.user_id) }}>
      🔒 wird bearbeitet von {holder.display_name}
    </span>
  );
}
