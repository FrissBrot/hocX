import { ReactNode } from "react";

export type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral";

type Props = {
  variant?: BadgeVariant;
  dot?: boolean;
  children: ReactNode;
};

export function Badge({ variant = "neutral", dot, children }: Props) {
  return (
    <span className={`badge badge-${variant}`}>
      {dot ? <span className="badge-dot" /> : null}
      {children}
    </span>
  );
}
