// Оболочка английских страниц пробы `/try*` (план agent-trial-01, T-C): шапка и подвал лендинга (макет v3-en-final, TG 420)
// вместо сквозных русских (`components/SiteHeader.tsx`, подвал `app/layout.tsx`) — их скрываем стилем страницы,
// как `app/flat/page.tsx`. Ссылки шапки ведут на блоки `/try` и со страницы задания `/try/<id>`.

import Link from "next/link";
import type { ReactNode } from "react";
import l from "@/components/trial/landing.module.css";

const HIDE_SITE_CHROME = ".site-header{display:none}:root{--site-header-h:0px}body footer.container{display:none}";

export function TryShell({ children }: { children: ReactNode }) {
  return (
    <div lang="en-GB" className={l.root}>
      <style>{HIDE_SITE_CHROME}</style>
      <header className={l.header}>
        <div className={l.wrap}>
          <Link className={l.logo} href="/try"><i>R</i>RemLab</Link>
          <nav className={l.nav}>
            <Link className={l.navLink} href="/try#how">How it works</Link>
            <Link className={l.navLink} href="/try#faq">FAQ</Link>
            <Link className={`${l.btn} ${l.btnSecondary}`} href="/try#example">Example</Link>
          </nav>
        </div>
      </header>
      <main>{children}</main>
      <footer className={l.footer}>
        <div className={l.wrap}>
          <span>© 2026 RemLab · Beta</span>
          {/* Контактного адреса в проекте нет (`lib/legal/texts.ts` — {{privacy e-mail}}): «Contact» ведёт на «Who we are». */}
          <span><Link href="/privacy?lang=en">Privacy</Link> · <Link href="/privacy?lang=en">Contact</Link></span>
        </div>
      </footer>
    </div>
  );
}
