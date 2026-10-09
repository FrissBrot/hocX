"use client";

import { CSSProperties, ReactNode, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { avatarColor, dateParts, initials } from "@/components/mobile/mobile-utils";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";

// Kleine Darstellungsbausteine der Mobile-Oberflaeche. Optik liegt komplett in globals.css
// (Praefix `mobile-`); Inline-Styles nur fuer Laufzeitfarben (Tag-/Avatar-Farbe) ueber
// CSS-Variablen, siehe design/DESIGN.md Grundsatz 5.

export function MobilePageHeader({
  title,
  searchOpen,
  onToggleSearch,
  searchValue,
  onSearchChange,
  searchPlaceholder,
}: {
  title: string;
  searchOpen: boolean;
  onToggleSearch: () => void;
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder: string;
}) {
  const t = useTranslations("mobile");
  return (
    <>
      <div className="mobile-page-header">
        <h1 className="mobile-page-title">{title}</h1>
        <button
          type="button"
          className={`mobile-icon-button${searchOpen ? " mobile-icon-button-active" : ""}`}
          aria-label={t("common.search")}
          aria-pressed={searchOpen}
          onClick={onToggleSearch}
        >
          <MobileIcon name="search" />
        </button>
      </div>
      {searchOpen ? (
        <div className="mobile-page-search">
          <SearchInput value={searchValue} onChange={onSearchChange} placeholder={searchPlaceholder} autoFocus />
        </div>
      ) : null}
    </>
  );
}

export type SegmentOption<T extends string> = { value: T; label: string; count?: number | null };

export function MobileSegmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  return (
    <div className="mobile-segmented" role="group" aria-label={ariaLabel} style={{ "--mobile-segments": options.length } as CSSProperties}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            className={`mobile-segment${active ? " mobile-segment-active" : ""}`}
            onClick={() => onChange(option.value)}
          >
            {option.label}
            {option.count !== undefined && option.count !== null ? <span className="mobile-segment-count">{option.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

export function MobileChipRow({ children }: { children: ReactNode }) {
  return <div className="mobile-chip-row">{children}</div>;
}

export function MobileChip({
  active,
  onClick,
  dotColor,
  leading,
  children,
}: {
  active: boolean;
  onClick: () => void;
  dotColor?: string | null;
  leading?: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={`mobile-chip${active ? " mobile-chip-active" : ""}${leading ? " mobile-chip-leading" : ""}`}
      onClick={onClick}
    >
      {leading}
      {dotColor ? <span className="mobile-chip-dot" style={{ "--mobile-tag-color": dotColor } as CSSProperties} /> : null}
      {children}
    </button>
  );
}

export function MobileChipDivider() {
  return <span className="mobile-chip-divider" aria-hidden="true" />;
}

export function MobileAvatar({ name, size = "md" }: { name: string; size?: "xs" | "sm" | "md" | "lg" }) {
  return (
    <span
      className={`mobile-avatar mobile-avatar-${size}`}
      style={{ "--mobile-avatar-color": avatarColor(name) } as CSSProperties}
      aria-hidden="true"
    >
      {initials(name)}
    </span>
  );
}

export function MobileCheck({
  checked,
  overdue = false,
  square = false,
  disabled = false,
  label,
  onToggle,
}: {
  checked: boolean;
  overdue?: boolean;
  square?: boolean;
  disabled?: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="mobile-check-button"
      aria-label={label}
      aria-pressed={checked}
      disabled={disabled}
      onClick={onToggle}
    >
      <span
        className={`mobile-check${checked ? " mobile-check-on" : ""}${overdue && !checked ? " mobile-check-overdue" : ""}${square ? " mobile-check-square" : ""}`}
      >
        {checked ? <MobileIcon name="check" size={14} strokeWidth={3} /> : null}
      </span>
    </button>
  );
}

export function MobileSwitch({ checked, danger = false }: { checked: boolean; danger?: boolean }) {
  return (
    <span className={`mobile-switch${checked ? " mobile-switch-on" : ""}${danger ? " mobile-switch-danger" : ""}`} aria-hidden="true">
      <span className="mobile-switch-knob" />
    </span>
  );
}

export function MobileCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`mobile-card ${className}`}>{children}</section>;
}

export function MobileCardHeader({ label, badge, action }: { label: string; badge?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mobile-card-header">
      <div className="mobile-card-header-label">
        <span className="mobile-eyebrow">{label}</span>
        {badge}
      </div>
      {action}
    </div>
  );
}

export function MobileEmpty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mobile-empty">
      <div className="mobile-empty-title">{title}</div>
      {hint ? <div className="mobile-empty-hint">{hint}</div> : null}
    </div>
  );
}

/** Datumskachel links in Termin-Zeilen: Monat oder Wochentag oben, Tageszahl unten. */
export function MobileDateTile({ iso, color, muted, top }: { iso: string; color: string; muted: boolean; top: "month" | "weekday" }) {
  const locale = useLocale();
  return (
    <span className={`mobile-date-tile${muted ? " mobile-date-tile-muted" : ""}`} style={{ "--mobile-tag-color": color } as CSSProperties} aria-hidden="true">
      <span className="mobile-date-tile-top">{top === "month" ? dateParts.monthShort(iso, locale) : dateParts.weekdayShort(iso, locale)}</span>
      <span className="mobile-date-tile-day">{dateParts.day(iso)}</span>
    </span>
  );
}

export function MobileTagPill({ label, color, cancelled = false }: { label: string; color: string; cancelled?: boolean }) {
  return (
    <span className={`mobile-tag-pill${cancelled ? " mobile-tag-pill-cancelled" : ""}`} style={{ "--mobile-tag-color": color } as CSSProperties}>
      {label}
    </span>
  );
}

export function MobileFab({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="mobile-fab" onClick={onClick}>
      <MobileIcon name="plus" strokeWidth={2.4} />
      {label}
    </button>
  );
}

/** Zeile in einer gruppierten Liste (Sheets, "Mehr"): Beschriftung links, Wert + Pfeil rechts. */
export function MobileListRow({
  label,
  value,
  onClick,
  chevron = true,
  leading,
  trailing,
}: {
  label: ReactNode;
  value?: ReactNode;
  onClick?: () => void;
  chevron?: boolean;
  leading?: ReactNode;
  trailing?: ReactNode;
}) {
  const content = (
    <>
      {leading}
      <span className="mobile-list-row-label">{label}</span>
      {value !== undefined ? <span className="mobile-list-row-value">{value}</span> : null}
      {trailing}
      {onClick && chevron ? <MobileIcon name="chevronRight" size={16} strokeWidth={2.2} className="mobile-list-row-chevron" /> : null}
    </>
  );
  return onClick ? (
    <button type="button" className="mobile-list-row" onClick={onClick}>
      {content}
    </button>
  ) : (
    <div className="mobile-list-row">{content}</div>
  );
}

/** Kopf einer Bereichsseite unter "Mehr": "‹ Mehr" (oder eigenes Ziel), Titel, Untertitel, Aktionen. */
export function MobileSubHeader({
  title,
  subtitle,
  backLabel,
  onBack,
  actions,
}: {
  title: string;
  subtitle?: string;
  backLabel: string;
  onBack: () => void;
  actions?: ReactNode;
}) {
  return (
    <div className="mobile-subheader">
      <button type="button" className="mobile-sheet-back" onClick={onBack}>
        <MobileIcon name="chevronLeft" size={22} strokeWidth={2.2} />
        {backLabel}
      </button>
      <div className="mobile-page-header mobile-subheader-row">
        <div className="mobile-subheader-text">
          <h1 className="mobile-page-title">{title}</h1>
          {subtitle ? <div className="mobile-muted-sm">{subtitle}</div> : null}
        </div>
        {actions ? <div className="mobile-subheader-actions">{actions}</div> : null}
      </div>
    </div>
  );
}

export type MobileAction = { label: string; onClick: () => void; danger?: boolean; disabled?: boolean };

/** Aktionen zu einem Objekt als Bottom-Sheet - mobiles Gegenstueck zu ActionMenu. */
export function MobileActionSheet({ title, actions, onClose }: { title: string; actions: MobileAction[]; onClose: () => void }) {
  return (
    <Modal open size="sheet" title={title} onClose={onClose} className="mobile-sheet">
      <div className="mobile-action-list">
        {actions.map((action) => (
          <button
            key={action.label}
            type="button"
            className={`mobile-action${action.danger ? " mobile-action-danger" : ""}`}
            disabled={action.disabled}
            onClick={() => {
              onClose();
              action.onClick();
            }}
          >
            {action.label}
          </button>
        ))}
      </div>
    </Modal>
  );
}

/** Hinweis fuer Funktionen, die bewusst am Computer bleiben - mit Link an die eigene E-Mail. */
export function MobileDesktopHint({ text, email }: { text: string; email?: string | null }) {
  const t = useTranslations("mobile");
  // Erst nach dem Mount: die aktuelle URL gibt es nur im Browser (sonst Hydration-Abweichung).
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => {
    setHref(email ? `mailto:${email}?subject=${encodeURIComponent("hocX")}&body=${encodeURIComponent(window.location.href)}` : null);
  }, [email]);
  return (
    <div className="mobile-desktop-hint">
      <p className="mobile-desktop-hint-text">{text}</p>
      {href ? (
        <a className="mobile-list-row mobile-desktop-hint-link" href={href}>
          <span className="mobile-list-row-label">
            {t("common.sendLinkToMe")}
            <small className="mobile-muted-sm">{email}</small>
          </span>
          <MobileIcon name="chevronRight" size={16} strokeWidth={2.2} className="mobile-list-row-chevron" />
        </a>
      ) : null}
    </div>
  );
}

/** Schwebende Leiste fuer eine Mehrfachauswahl (Teilnehmer, Fotos). */
export function MobileSelectionBar({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mobile-selection-bar" role="toolbar" aria-label={label}>
      <span className="mobile-selection-bar-label">{label}</span>
      <div className="mobile-selection-bar-actions">{children}</div>
    </div>
  );
}

/** Kompakte Kennzahl-Kachel (Statistik, Bussen, Abo). */
export function MobileStat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mobile-card mobile-stat">
      <div className="mobile-eyebrow">{label}</div>
      <div className="mobile-stat-value">{value}</div>
      {sub ? <div className="mobile-muted-sm">{sub}</div> : null}
    </div>
  );
}

/** Zeile mit Fortschrittsbalken (Abgaben, Speicher, Nutzer). */
export function MobileProgress({ value, max, label }: { value: number; max: number; label?: ReactNode }) {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="mobile-progress">
      <div className="mobile-progress-track">
        <span style={{ width: `${percent}%` }} />
      </div>
      {label ? <span className="mobile-muted-sm">{label}</span> : null}
    </div>
  );
}

/** Beschriftete Gruppe von Zeilen in einer Karte (Einstellungen, "Mehr"). */
export function MobileGroupCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mobile-group">
      <div className="mobile-group-label">{label}</div>
      <div className="mobile-card mobile-group-card">{children}</div>
    </div>
  );
}
