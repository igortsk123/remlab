"use client";

import { useState, useTransition } from "react";
import type { CalcKind } from "@/contracts/calc";
import { CALC_META } from "@/lib/estimate/companions";
import { captureLead } from "@/app/lead-actions";

const TG_BOT = process.env.NEXT_PUBLIC_TELEGRAM_BOT;
const MAX_BOT = process.env.NEXT_PUBLIC_MAX_BOT;

const inp = {
  padding: "8px 10px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

// «Найти дешевле» (К6): ссылка (если есть) + e-mail за результат (лид). Поиск — асинхронно (owner/позже).
export function FindCheaper({ kind, url }: { kind: CalcKind; url: string | undefined }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [links, setLinks] = useState<string[]>([url ?? ""]);
  const [city, setCity] = useState("");
  const [consent, setConsent] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState(false);
  const [pending, startTransition] = useTransition();

  function submit() {
    setError(false);
    startTransition(async () => {
      const urls = links.map((l) => l.trim()).filter(Boolean);
      const res = await captureLead({ email, urls, city: city.trim() || undefined, kind, consent });
      if (res.ok) setDone(true);
      else setError(true);
    });
  }

  if (done) {
    return (
      <div className="card stack">
        <p className="eyebrow">Найдём выгоднее</p>
        <p style={{ margin: 0 }}>Спасибо! Поищем те же материалы выгоднее и пришлём варианты на почту.</p>
      </div>
    );
  }

  return (
    <div className="card stack">
      <p className="eyebrow">Найдём выгоднее</p>
      {!open ? (
        <>
          <p className="muted" style={{ margin: 0, fontSize: 15 }}>Мы найдём {CALC_META[kind].accYours} и все необходимые материалы для {CALC_META[kind].work} по более выгодной цене в магазинах вашего города или онлайн.</p>
          <button type="button" className="btn btn-secondary" onClick={() => setOpen(true)}>Найти выгоднее</button>
        </>
      ) : (
        <>
          {links.map((l, i) => (
            <input
              key={i}
              style={inp}
              placeholder="Ссылка на товар (если есть)"
              value={l}
              onChange={(e) => setLinks((ls) => ls.map((x, j) => (j === i ? e.target.value : x)))}
            />
          ))}
          <button type="button" className="quiz-link" onClick={() => setLinks((ls) => [...ls, ""])}>+ добавить товар</button>
          <input style={inp} placeholder="Ваш город" value={city} onChange={(e) => setCity(e.target.value)} />
          <input style={inp} type="email" placeholder="E-mail для результата" value={email} onChange={(e) => setEmail(e.target.value)} />
          <label className="row" style={{ gap: 8, alignItems: "flex-start" }}>
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span className="muted" style={{ fontSize: 13 }}>Согласен на обработку e-mail для отправки результата.</span>
          </label>
          <button type="button" className="btn" disabled={pending || !email || !consent} onClick={submit}>
            {pending ? "Отправляем…" : "Прислать варианты"}
          </button>
          {error && <span className="muted" style={{ fontSize: 13 }}>Проверьте e-mail и согласие.</span>}
          {(TG_BOT || MAX_BOT) && (
            <p className="muted" style={{ fontSize: 13, margin: 0 }}>
              Или подпишитесь на бота:{" "}
              {TG_BOT && <a href={`https://t.me/${TG_BOT}`} target="_blank" rel="noopener noreferrer">Telegram</a>}
              {TG_BOT && MAX_BOT ? " · " : ""}
              {MAX_BOT && <a href={`https://max.ru/${MAX_BOT}`} target="_blank" rel="noopener noreferrer">MAX</a>}
            </p>
          )}
        </>
      )}
    </div>
  );
}
