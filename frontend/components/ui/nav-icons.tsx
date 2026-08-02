import { SVGProps } from "react";

export type NavIconKey =
  | "dashboard"
  | "protocols"
  | "todos"
  | "fines"
  | "finances"
  | "statistics"
  | "lists"
  | "participants"
  | "events"
  | "submissions"
  | "templates"
  | "elements"
  | "cycles"
  | "users"
  | "documents"
  | "tenant"
  | "activity";

type IconProps = Omit<SVGProps<SVGSVGElement>, "viewBox" | "fill">;

function Icon({ children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      width={18}
      height={18}
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

const ICONS: Record<NavIconKey, (props: IconProps) => React.ReactElement> = {
  dashboard: (props) => (
    <Icon {...props}>
      <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.5" />
      <rect x="13" y="3.5" width="7.5" height="7.5" rx="1.5" />
      <rect x="3.5" y="13" width="7.5" height="7.5" rx="1.5" />
      <rect x="13" y="13" width="7.5" height="7.5" rx="1.5" />
    </Icon>
  ),
  protocols: (props) => (
    <Icon {...props}>
      <rect x="5" y="4" width="14" height="17" rx="2" />
      <path d="M9 3.2h6v2.6a1 1 0 01-1 1h-4a1 1 0 01-1-1V3.2z" />
      <path d="M8.5 11h7M8.5 14.5h7M8.5 18h4.5" />
    </Icon>
  ),
  todos: (props) => (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.2 12.3l2.6 2.6 5-5.2" />
    </Icon>
  ),
  fines: (props) => (
    <Icon {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5v5.2" />
      <circle cx="12" cy="16.2" r="0.9" fill="currentColor" stroke="none" />
    </Icon>
  ),
  finances: (props) => (
    <Icon {...props}>
      <rect x="3" y="6.5" width="18" height="12.5" rx="2" />
      <path d="M3 10.2h18" />
      <circle cx="16.5" cy="14.3" r="1.15" fill="currentColor" stroke="none" />
    </Icon>
  ),
  statistics: (props) => (
    <Icon {...props}>
      <rect x="4" y="12.5" width="3.2" height="7.5" rx="0.8" />
      <rect x="10.4" y="7.5" width="3.2" height="12.5" rx="0.8" />
      <rect x="16.8" y="4" width="3.2" height="16" rx="0.8" />
    </Icon>
  ),
  lists: (props) => (
    <Icon {...props}>
      <path d="M9 6.5h11M9 12h11M9 17.5h11" />
      <circle cx="4.3" cy="6.5" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="4.3" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="4.3" cy="17.5" r="1.1" fill="currentColor" stroke="none" />
    </Icon>
  ),
  participants: (props) => (
    <Icon {...props}>
      <circle cx="9" cy="8.2" r="3.2" />
      <path d="M3.3 19.8c0-3.4 2.6-6.1 5.7-6.1s5.7 2.7 5.7 6.1" />
      <path d="M15.8 9a2.9 2.9 0 010 5.7" />
      <path d="M14.8 14.1c2.6 0.5 4.6 2.7 4.6 5.7" />
    </Icon>
  ),
  events: (props) => (
    <Icon {...props}>
      <rect x="3.5" y="5" width="17" height="16" rx="2" />
      <path d="M3.5 10h17M8 3v4M16 3v4" />
    </Icon>
  ),
  submissions: (props) => (
    <Icon {...props}>
      <path d="M12 3.2v10.2" />
      <path d="M8.4 9.8L12 13.4l3.6-3.6" />
      <path d="M4 15.2v3a2 2 0 002 2h12a2 2 0 002-2v-3" />
    </Icon>
  ),
  templates: (props) => (
    <Icon {...props}>
      <rect x="3.5" y="3.5" width="17" height="17" rx="2" />
      <path d="M3.5 9h17M9 9v11.5" />
    </Icon>
  ),
  elements: (props) => (
    <Icon {...props}>
      <path d="M5.5 4.5h4.6v1.9a1.4 1.4 0 002.8 0V4.5h4.6a1 1 0 011 1v4.6h-1.9a1.4 1.4 0 000 2.8h1.9v4.6a1 1 0 01-1 1h-4.6v-1.9a1.4 1.4 0 00-2.8 0v1.9H5.5a1 1 0 01-1-1v-4.6h1.9a1.4 1.4 0 000-2.8H4.5V5.5a1 1 0 011-1z" />
    </Icon>
  ),
  cycles: (props) => (
    <Icon {...props}>
      <path d="M4.3 12a7.7 7.7 0 0113.6-4.9l1.8 1.9" />
      <path d="M19.7 5.6v3.8h-3.8" />
      <path d="M19.7 12a7.7 7.7 0 01-13.6 4.9l-1.8-1.9" />
      <path d="M4.3 18.4v-3.8h3.8" />
    </Icon>
  ),
  users: (props) => (
    <Icon {...props}>
      <circle cx="12" cy="8" r="3.6" />
      <path d="M5 20.5c0-3.9 3.1-7 7-7s7 3.1 7 7" />
    </Icon>
  ),
  documents: (props) => (
    <Icon {...props}>
      <path d="M7 3h6.5L18 7.5V20a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1z" />
      <path d="M13.5 3v4.2a0.8 0.8 0 00.8.8H18" />
      <path d="M9 13.2h6M9 16.6h6" />
    </Icon>
  ),
  tenant: (props) => (
    <Icon {...props}>
      <circle cx="12" cy="12" r="2.9" />
      <path d="M12 3.3v2.3M12 18.4v2.3M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M3.3 12h2.3M18.4 12h2.3M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" />
    </Icon>
  ),
  activity: (props) => (
    <Icon {...props}>
      <path d="M3 12.5h3.4l2-5.4 3.2 10.8 2.4-8.4 1.6 3h5.4" />
    </Icon>
  ),
};

export function NavIcon({ name, ...rest }: { name: NavIconKey } & IconProps) {
  const Component = ICONS[name];
  return <Component {...rest} />;
}
