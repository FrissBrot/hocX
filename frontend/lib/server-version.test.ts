import { afterEach, describe, expect, it, vi } from "vitest";
import { execFileSync } from "node:child_process";
import { getServerVersion } from "./server-version";

vi.mock("node:child_process", () => {
  const execFileSync = vi.fn();
  return { execFileSync, default: { execFileSync } };
});

afterEach(() => { vi.unstubAllEnvs(); vi.resetAllMocks(); });

function setup(environment: string, version: string) {
  vi.stubEnv("HOCX_ENVIRONMENT", environment);
  vi.stubEnv("HOCX_VERSION", version);
  vi.stubEnv("HOCX_FRONTEND_IMAGE", "");
  vi.stubEnv("HOCX_GIT_BRANCH", "");
  vi.stubEnv("HOCX_GIT_COMMIT", "");
}

describe("getServerVersion", () => {
  it("liest den promovierten Release-Tag zur Laufzeit ohne Git", () => {
    setup("production", "v1.2.0");
    expect(getServerVersion()).toMatchObject({ version: "v1.2.0", environment: "production" });
    expect(execFileSync).not.toHaveBeenCalled();
  });
  it("behandelt den Alias prod bestehender Hosts als production", () => {
    setup("prod", "v1.2.0");
    expect(getServerVersion()).toMatchObject({ version: "v1.2.0", environment: "production" });
  });
  it("zeigt in Test den Tag des tatsaechlich ausgewaehlten Images", () => {
    setup("test", "test-old");
    vi.stubEnv("HOCX_FRONTEND_IMAGE", "registry:5000/hocx-frontend:test-20261011-abc1234-r42");
    expect(getServerVersion().version).toBe("test-20261011-abc1234-r42");
  });
  it("verwendet ohne Image-Override den gemeinsamen Test-Tag", () => {
    setup("test", "test-20261011-abc1234-r42");
    expect(getServerVersion().version).toBe("test-20261011-abc1234-r42");
  });
  it("liest Branch und Commit auch wenn Next.js in Dev im Produktionsmodus laeuft", () => {
    setup("development", "dev-local");
    vi.stubEnv("NODE_ENV", "production");
    vi.mocked(execFileSync).mockReturnValueOnce("abc1234\n").mockReturnValueOnce("feature/version\n");
    expect(getServerVersion()).toMatchObject({ environment: "development", branch: "feature/version", commit: "abc1234" });
  });
  it("bleibt ohne verfuegbares Git darstellbar", () => {
    setup("development", "dev");
    vi.mocked(execFileSync).mockImplementation(() => { throw new Error("missing git"); });
    expect(getServerVersion()).toMatchObject({ branch: null, commit: null });
  });
});
