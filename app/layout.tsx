import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "remont-lab — AI-помощник по ремонту",
  description:
    "Обновите комнату с помощью AI: визуальная идея, товары, материалы, бюджет и план по фото.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
