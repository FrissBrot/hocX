import type { MetadataRoute } from "next";
import { getCurrentBaseUrl, isMarketingVariant } from "@/lib/site-config";

export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  const baseUrl = getCurrentBaseUrl();

  if (!isMarketingVariant()) {
    return {
      rules: {
        userAgent: "*",
        disallow: "/",
      },
    };
  }

  return {
    rules: {
      userAgent: "*",
      allow: "/",
    },
    sitemap: baseUrl ? `${baseUrl}/sitemap.xml` : undefined,
    host: baseUrl ?? undefined,
  };
}
