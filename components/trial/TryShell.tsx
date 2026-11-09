// Оболочка страниц пробы `/try*` (план agent-trial-01, T-C; два языка — agent-trial-08, П): шапка и подвал лендинга
// (макет v3-en-final, TG 420) вместо сквозных русских (`components/SiteHeader.tsx`, подвал `app/layout.tsx`) — их скрываем
// стилем страницы, как `app/flat/page.tsx`. Ссылки шапки ведут на блоки `/try` и со страницы задания `/try/<id>`; язык
// держится в `?lang=`. Переключатель «Русский · English» — в подвале, как у `/demo` (владелец 16.10: внизу, мелко).

import Link from "next/link";
import type { ReactNode } from "react";
import { LangSwitch } from "@/components/trial/LangSwitch";
import l from "@/components/trial/landing.module.css";
import { LANG_KEY, textOf, withLang, type TrialLang } from "@/lib/trial/i18n";

const HIDE_SITE_CHROME = ".site-header{display:none}:root{--site-header-h:0px}body footer.container{display:none}";

// Язык не задан в адресе — сервер выбрал по браузеру; сохранённый выбор человека (как в `/demo`) главнее: до показа
// страницы перезагружаем её с `?lang=`. Адрес с `?lang=` скрипта не получает.
const savedLangJs = (current: TrialLang) =>
  `(function(){try{var s=localStorage.getItem(${JSON.stringify(LANG_KEY)});if((s==="ru"||s==="en")&&s!==${JSON.stringify(current)}){` +
  `var u=new URL(location.href);u.searchParams.set("lang",s);location.replace(u.toString());}}catch(e){}})();`;

type Props = { lang: TrialLang; explicit: boolean; path: string; children: ReactNode };

export function TryShell({ lang, explicit, path, children }: Props) {
  const t = textOf(lang).shell;
  const home = withLang("/try", lang);
  return (
    <div lang={textOf(lang).htmlLang} className={l.root}>
      {explicit ? null : <script dangerouslySetInnerHTML={{ __html: savedLangJs(lang) }} />}
      <style>{HIDE_SITE_CHROME}</style>
      <header className={l.header}>
        <div className={l.wrap}>
          <Link className={l.logo} href={home}><i>R</i>RemLab</Link>
          <nav className={l.nav}>
            <Link className={l.navLink} href={`${home}#how`}>{t.how}</Link>
            <Link className={l.navLink} href={`${home}#faq`}>{t.faq}</Link>
            <Link className={`${l.btn} ${l.btnSecondary}`} href={`${home}#example`}>{t.example}</Link>
          </nav>
        </div>
      </header>
      <main>{children}</main>
      <footer className={l.footer}>
        <div className={l.wrap}>
          <span>{t.beta}</span>
          {/* Контактного адреса в проекте нет (`lib/legal/texts.ts` — {{privacy e-mail}}): «Contact» ведёт на «Who we are». */}
          <span><Link href={`/privacy?lang=${lang}`}>{t.privacy}</Link> · <Link href={`/privacy?lang=${lang}`}>{t.contact}</Link></span>
          <LangSwitch lang={lang} path={path} label={t.langLabel} />
        </div>
      </footer>
    </div>
  );
}
