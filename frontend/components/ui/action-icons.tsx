import { SVGProps } from "react";

export type ActionIconKey = "edit" | "delete" | "close" | "add" | "copy" | "upload" | "download" | "link" | "hide";

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
      width={16}
      height={16}
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

const ICONS: Record<ActionIconKey, (props: IconProps) => React.ReactElement> = {
  edit: (props) => (
    <Icon {...props}>
      <path d="M4 20h4.2L18.4 9.8a2 2 0 0 0 0-2.8l-1.4-1.4a2 2 0 0 0-2.8 0L4 15.8V20z" />
      <path d="M13.5 6.5l4 4" />
    </Icon>
  ),
  delete: (props) => (
    <Icon {...props}>
      <path d="M5 7h14" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
      <path d="M7 7l1 13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-13" />
      <path d="M10 11v6M14 11v6" />
    </Icon>
  ),
  close: (props) => (
    <Icon {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Icon>
  ),
  add: (props) => (
    <Icon {...props}>
      <path d="M12 5v14M5 12h14" />
    </Icon>
  ),
  upload: (props) => (
    <Icon {...props}>
      <path d="M12 15V4M7.5 8.5L12 4l4.5 4.5" />
      <path d="M5 19h14" />
    </Icon>
  ),
  download: (props) => (
    <Icon {...props}>
      <path d="M12 4v11M7.5 10.5L12 15l4.5-4.5" />
      <path d="M5 19h14" />
    </Icon>
  ),
  link: (props) => (
    <Icon {...props}>
      <path d="M9.5 14.5l5-5" />
      <path d="M8 11l-2 2a3.5 3.5 0 0 0 5 5l2-2M16 13l2-2a3.5 3.5 0 0 0-5-5l-2 2" />
    </Icon>
  ),
  hide: (props) => (
    <Icon {...props}>
      <path d="M3 3l18 18" />
      <path d="M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 8.5 4.2 9.5 6-.4.8-1.3 2-2.5 3.2M6.6 6.6C4.6 7.9 3.2 9.8 2.5 12c1 1.8 4.5 6 9.5 6 1.6 0 3-.4 4.3-1.1" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </Icon>
  ),
  copy: (props) => (
    <Icon {...props}>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" />
    </Icon>
  ),
};

export function ActionIcon({ name, ...rest }: { name: ActionIconKey } & IconProps) {
  const Component = ICONS[name];
  return <Component {...rest} />;
}
