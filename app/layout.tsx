import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { VersionWatcher } from "@/components/VersionWatcher";

export const metadata: Metadata = {
  title: "remont-lab — AI-помощник по ремонту",
  description:
    "Обновите комнату с помощью AI: визуальная идея, товары, материалы, бюджет и план по фото.",
};

// Версия сборки, которой отдана страница (runtime env контейнера). Клиент сравнит её с /api/health
// и предложит обновиться после передеплоя (иначе серверные экшены форм молча ломаются).
const APP_VERSION = process.env.APP_VERSION ?? "dev";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        {children}
        <VersionWatcher current={APP_VERSION} />
      </body>
    </html>
  );
}
