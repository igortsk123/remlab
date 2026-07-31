"use client";

import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { RouterProvider } from "react-aria-components";

// Клиентская навигация для react-aria Link/Button href (Untitled UI): без провайдера
// href-компоненты делали бы полную перезагрузку страницы вместо клиентского перехода.
export function Providers({ children }: { children: ReactNode }) {
  const router = useRouter();
  return <RouterProvider navigate={(href) => router.push(href)}>{children}</RouterProvider>;
}
