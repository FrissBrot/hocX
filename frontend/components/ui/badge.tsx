import { ReactNode } from "react";

export type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral";

type Props = {
  variant?: BadgeVariant;
  dot?: boolean;
  className?: string;
  children: ReactNode;
};

export function Badge({ variant = "neutral", dot, className, children }: Props) {
  return (
    <span className={`badge badge-${variant}${className ? ` ${className}` : ""}`}>
      {dot ? <span className="badge-dot" /> : null}
      {children}
    </span>
  );
}
