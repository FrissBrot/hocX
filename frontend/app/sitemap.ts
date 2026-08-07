import type { MetadataRoute } from "next";
import { getCurrentBaseUrl, isMarketingVariant } from "@/lib/site-config";

export const dynamic = "force-dynamic";

export default function sitemap(): MetadataRoute.Sitemap {
  if (!isMarketingVariant()) {
    return [];
  }

  const baseUrl = getCurrentBaseUrl();
  if (!baseUrl) {
    return [];
  }

  return [
    {
      url: baseUrl,
      changeFrequency: "weekly",
      priority: 1,
      lastModified: new Date(),
    },
  ];
}
