import { SVGProps } from "react";

export type ActionIconKey = "edit" | "delete" | "close" | "add" | "copy";

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
