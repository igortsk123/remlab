/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone", // тонкий runtime для контейнера (migration-ready)
  reactStrictMode: true,
  // Линт гоняем отдельно (pnpm lint / CI S4), не блокируем контейнерную сборку.
  eslint: { ignoreDuringBuilds: true },
  env: {
    APP_VERSION: process.env.APP_VERSION ?? "dev",
  },
};

export default nextConfig;
