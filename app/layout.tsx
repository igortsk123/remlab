import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "remont-lab — AI-помощник по ремонту",
  description:
    "Обновите комнату с помощью AI: визуальная идея, товары, бюджет и план по фото.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body
        style={{
          margin: 0,
          fontFamily:
            "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
          background: "#0f1115",
          color: "#e8eaed",
        }}
      >
        {children}
      </body>
    </html>
  );
}
