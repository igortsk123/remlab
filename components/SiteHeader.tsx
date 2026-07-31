"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { LabBadge } from "@/components/LabBadge";
import { ZoomControl } from "@/components/ZoomControl";

// Сквозная шапка на всех страницах: ОДИН ряд кнопок (шапка шире контента — globals.css,
// .site-header-inner), активный раздел подсвечивается. На мобильном при прокрутке вниз ряд
// сворачивается (класс site-header--collapsed + media query) — остаются бренд/зум/лаборатория
// и липкий итог. Разделы с soon закрыты заглушками до запуска (launch-p1-vitrina).

type NavItem = { href: string; label: string; match: string[]; soon?: boolean };

const NAV: NavItem[] = [
  { href: "/start", label: "Дизайн", match: ["/start", "/p/"], soon: true },
  { href: "/styles", label: "Стили", match: ["/styles"], soon: true },
  { href: "/sovety", label: "Советы", match: ["/sovety"], soon: true },
];

function matches(pathname: string, prefixes: string[]): boolean {
  return prefixes.some((p) => pathname === p || pathname.startsWith(p.endsWith("/") ? p : `${p}/`));
}

export function SiteHeader() {
  const pathname = usePathname();
  const ref = useRef<HTMLElement>(null);

  // Публикуем высоту шапки в CSS-переменную — под ней липнут вторичные шапки (напр. итоги калькулятора).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const setVar = () => document.documentElement.style.setProperty("--site-header-h", `${el.offsetHeight}px`);
    setVar();
    const ro = new ResizeObserver(setVar);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Прокрутка вниз → класс collapsed (ряд кнопок скрывает media query — только узкие окна).
  // Пороги 160/40: зазор БОЛЬШЕ высоты сворачиваемого ряда (~46px), иначе изменение высоты
  // шапки перебрасывает y через оба порога и шапка мерцает (+ overflow-anchor: none в CSS).
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const y = window.scrollY;
        if (y > 160) el.classList.add("site-header--collapsed");
        else if (y < 40) el.classList.remove("site-header--collapsed");
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  const materialsActive = pathname === "/calc" || (pathname.startsWith("/calc/") && pathname !== "/calc/remont");
  const costActive = pathname === "/calc/remont";
  const labActive = matches(pathname, ["/lab", "/rooms"]);

  return (
    <header ref={ref} className="site-header">
      <div className="site-header-inner">
        {/* Бренд + полоса кнопок — ОДИН блок (site-header-group): на десктопе он шириной по
            содержимому и центрируется целиком, поэтому бренд стоит ровно на левом крае первой
            кнопки. Зум и «Моя лаборатория» на десктопе уводятся к правому краю (absolute). */}
        <div className="site-header-group">
          <div className="site-header-top">
            <Link href="/" className="site-brand">remont-lab</Link>
            <span className="row header-controls" style={{ gap: 10, alignItems: "center", flexWrap: "nowrap" }}>
              <ZoomControl />
              <Link href="/lab" className={`nav-link${labActive ? " nav-link--active" : ""}`} style={{ padding: "8px 0" }}>
                Моя лаборатория<LabBadge />
              </Link>
            </span>
          </div>
          <nav className="site-nav" aria-label="Разделы сайта">
            <Link href="/calc" className={`nav-cta${materialsActive ? " nav-cta--active" : ""}`}>
              Посчитать материалы
            </Link>
            <Link href="/calc/remont" className={`nav-cta nav-cta--alt${costActive ? " nav-cta--active" : ""}`}>
              Сколько стоит ремонт
              <span className="ml-2 rounded-full bg-brand-800/15 px-2 py-0.5 text-[11px] font-semibold text-brand-800">скоро</span>
            </Link>
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={`nav-link${matches(pathname, n.match) ? " nav-link--active" : ""}`}
              >
                {n.label}
                {n.soon && (
                  <span className="ml-2 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold text-quaternary ring-1 ring-border-primary ring-inset">скоро</span>
                )}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}
