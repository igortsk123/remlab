"use client";

// Переключатель языка страниц пробы «Русский · English» (план agent-trial-08, П) — как строка `#langSw` живого `/demo`:
// текущий язык жирным, другой — ссылка на ту же страницу с `?lang=`; выбор запоминается (`localStorage['remlab-lang']`,
// общий с `/demo`), чтобы следующий вход без `?lang=` открылся на нём же. Хранилища может не быть — тогда только адрес.

import l from "@/components/trial/landing.module.css";
import { LANG_KEY, TRIAL_LANGS, type TrialLang } from "@/lib/trial/i18n";

export function LangSwitch({ lang, path, label }: { lang: TrialLang; path: string; label: string }) {
  const remember = (next: TrialLang) => { try { localStorage.setItem(LANG_KEY, next); } catch { /* нет хранилища */ } };
  return (
    <nav className={l.lang} aria-label={label} data-testid="trial-lang">
      {TRIAL_LANGS.map(([code, name], i) => (
        <span key={code}>
          {i > 0 ? <i aria-hidden="true">·</i> : null}
          {code === lang ? <b lang={code}>{name}</b> : (
            <a href={`${path}?lang=${code}`} lang={code} hrefLang={code} onClick={() => remember(code)}>{name}</a>
          )}
        </span>
      ))}
    </nav>
  );
}
