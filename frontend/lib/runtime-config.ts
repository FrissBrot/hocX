declare global {
  interface Window {
    __HOCX_CONFIG__?: {
      mainAppDomain: string | null;
      version: string;
      siteVariant?: "app" | "marketing";
    };
  }
}

export function getRuntimeConfig() {
  return (
    (typeof window !== "undefined" && window.__HOCX_CONFIG__) || {
      mainAppDomain: null,
      version: "dev",
      siteVariant: "app"
    }
  );
}
