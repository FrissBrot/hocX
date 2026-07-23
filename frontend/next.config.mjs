/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  experimental: {
    typedRoutes: true,
    staleTimes: {
      dynamic: 0,
    },
  },
};

export default nextConfig;

