const releasesUrl = "https://github.com/FrissBrot/hocX/releases";

export function getReleaseUrl(version: string): string {
  // Entwicklungsstände und moving tags besitzen keinen eigenen Release.
  return /^v?\d+\.\d+\.\d+$/.test(version)
    ? `${releasesUrl}/tag/${encodeURIComponent(version)}`
    : releasesUrl;
}
