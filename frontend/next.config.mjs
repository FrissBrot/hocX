/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    typedRoutes: true,
    staleTimes: {
      dynamic: 0,
    },
  },
};

export default nextConfig;

