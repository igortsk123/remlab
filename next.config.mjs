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
  // Проба для агентов (agent-trial-01): ключ ссылки /try/<id> не уходит в Referer и в поиск. На проде то же (и
  // Cache-Control: private, no-store) ставит Caddy `@trialpage`; здесь — для запуска без Caddy (dev, e2e).
  async headers() {
    const h = [
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "X-Robots-Tag", value: "noindex, nofollow" },
    ];
    return [
      { source: "/try", headers: h },
      { source: "/try/:path*", headers: h },
    ];
  },
};

export default nextConfig;
