/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone", // тонкий runtime для контейнера (migration-ready)
  reactStrictMode: true,
  // Линт гоняем отдельно (pnpm lint / CI S4), не блокируем контейнерную сборку.
  eslint: { ignoreDuringBuilds: true },
  // Фото комнаты приходит через Server Action — дефолтный лимит 1 МБ мал для фото с телефона.
  experimental: { serverActions: { bodySizeLimit: "12mb" } },
  env: {
    APP_VERSION: process.env.APP_VERSION ?? "dev",
  },
};

export default nextConfig;
