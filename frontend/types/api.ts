export type SaveState = "saving" | "saved" | "error";

export type TemplateSummary = {
  id: number;
  name: string;
  version: number;
  status: string;
};

export type ProtocolSummary = {
  id: number;
  protocol_number: string;
  title: string | null;
  status: string;
};

