// Gemeinsame Typen des Visual Designers.

export type { BrandOverrides, BrandTokens, TemplateContent, TemplateNode } from "@/lib/documents/layout";
export type Length = string;

export type DesignerArea = "body" | "title_page" | { master: string; slot: "header" | "footer" | "background" };
