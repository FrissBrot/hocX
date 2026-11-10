import { execFileSync } from "node:child_process";

function gitValue(args: string[]): string | null {
  try {
    return execFileSync("git", args, { encoding: "utf8", timeout: 1000, stdio: ["ignore", "pipe", "ignore"] }).trim() || null;
  } catch {
    return null;
  }
}

// Laufzeitwerte: dasselbe getestete Image wird ohne Neubau nach Prod promoviert.
export function getServerVersion() {
  const version = process.env.HOCX_VERSION || "dev";
  const rawEnvironment = (process.env.HOCX_ENVIRONMENT || "").trim().toLowerCase() ||
    (version.startsWith("dev") ? "development" : version.startsWith("test-") ? "test" : "production");
  // 'prod' ist ein Alias fuer 'production': deploy.sh schrieb bis zum Audit MAIN-OPS-001 den
  // Host-Namen in die .env (siehe backend/app/core/config.py::is_production).
  const environment = rawEnvironment === "prod" ? "production" : rawEnvironment;
  if (environment === "development" || environment === "dev") {
    const commit = process.env.HOCX_GIT_COMMIT || gitValue(["rev-parse", "--short", "HEAD"]);
    const branch = process.env.HOCX_GIT_BRANCH || gitValue(["branch", "--show-current"]);
    return { version, environment: "development", commit, branch };
  }
  // Ein explizit abweichendes Frontend-Image hat Vorrang vor dem gemeinsamen Tag.
  const image = process.env.HOCX_FRONTEND_IMAGE;
  const imageTag = image && !image.includes("@") && image.lastIndexOf(":") > image.lastIndexOf("/")
    ? image.slice(image.lastIndexOf(":") + 1) : image;
  return { version: environment === "test" ? imageTag || version : version, environment, commit: null, branch: null };
}
