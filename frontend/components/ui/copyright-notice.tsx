export function CopyrightNotice({ className = "" }: { className?: string }) {
  const classes = ["copyright-notice", className].filter(Boolean).join(" ");

  return <p className={classes}>Copyright © 2026 hocX Project · All rights reserved.</p>;
}
