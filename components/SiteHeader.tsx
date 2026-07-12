"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Сквозная шапка на всех страницах. Все разделы на виду; две кнопки-калькулятора выделены
// (залитые пилюли), остальные — лёгкие ссылки. Активный раздел подсвечивается. На узком экране
// полоса навигации прокручивается вбок (без «гамбургера»), страница по горизонтали не едет.

type NavItem = { href: string; label: string; match: string[] };

const NAV: NavItem[] = [
  { href: "/start", label: "Дизайн", match: ["/start", "/p/"] },
  { href: "/styles", label: "Стили", match: ["/styles"] },
  { href: "/sovety", label: "Советы", match: ["/sovety"] },
];

function matches(pathname: string, prefixes: string[]): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(p.endsWith("/") ? p : `${p}/`));
}

export function SiteHeader() {
  const pathname = usePathname();

  const materialsActive = pathname === "/calc" || (pathname.startsWith("/calc/") && pathname !== "/calc/remont");
  const costActive = pathname === "/calc/remont";
  const labActive = matches(pathname, ["/lab", "/estimates", "/rooms"]);

  return (
    <header className="site-header">
      <div className="site-header-inner">
        <div className="site-header-top">
          <Link href="/" className="site-brand">remont-lab</Link>
          <Link href="/lab" className={`nav-link${labActive ? " nav-link--active" : ""}`}>
            Моя лаборатория
          </Link>
        </div>
        <nav className="site-nav" aria-label="Разделы сайта">
          <Link href="/calc" className={`nav-cta${materialsActive ? " nav-cta--active" : ""}`}>
            Посчитать материалы
          </Link>
          <Link href="/calc/remont" className={`nav-cta nav-cta--alt${costActive ? " nav-cta--active" : ""}`}>
            Сколько стоит ремонт
          </Link>
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={`nav-link${matches(pathname, n.match) ? " nav-link--active" : ""}`}
            >
              {n.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
