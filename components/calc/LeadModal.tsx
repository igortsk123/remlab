"use client";

import { useEffect, useState, useTransition } from "react";
import type { CalcKind } from "@/contracts/calc";
import { captureLead } from "@/app/lead-actions";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const inp = {
  padding: "10px 12px", borderRadius: 8, border: "1px solid var(--base)",
  background: "var(--surface)", color: "var(--text)", fontSize: 15, width: "100%",
} as const;

// Модалка «Сообщить по почте»: e-mail (проверка маски) + согласие → лид. Закрытие: backdrop, «×», Esc.
export function LeadModal({ kind, url, onClose }: { kind: CalcKind; url?: string; onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState(false);
  const [pending, startTransition] = useTransition();
  const valid = EMAIL_RE.test(email.trim());

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  function submit() {
    if (!valid || !consent) return;
    setError(false);
    startTransition(async () => {
      const res = await captureLead({ email: email.trim(), urls: url ? [url] : undefined, kind, consent });
      if (res.ok) { setDone(true); setTimeout(onClose, 1300); }
      else setError(true);
    });
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Сообщить по почте">
        <button type="button" className="modal-close" aria-label="Закрыть" onClick={onClose}>×</button>
        {done ? (
          <p style={{ margin: 0 }}>Спасибо! Поищем выгоднее и пришлём варианты на почту.</p>
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            <p className="eyebrow" style={{ margin: 0 }}>Сообщить по почте</p>
            <p className="muted" style={{ margin: 0, fontSize: 14 }}>Оставьте e-mail — найдём, где дешевле, и пришлём варианты.</p>
            <input style={inp} type="email" inputMode="email" placeholder="E-mail" value={email} onChange={(e) => setEmail(e.target.value)} />
            <label className="row" style={{ gap: 8, alignItems: "flex-start" }}>
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span className="muted" style={{ fontSize: 13 }}>
                Я согласен с <a href="#" onClick={(e) => e.preventDefault()}>политикой обработки персональных данных</a>.
              </span>
            </label>
            <button type="button" className="btn" disabled={pending || !valid || !consent} onClick={submit}>
              {pending ? "Отправляем…" : "Отправить"}
            </button>
            {email.length > 0 && !valid && <span className="muted" style={{ fontSize: 13 }}>Проверьте формат e-mail.</span>}
            {error && <span className="muted" style={{ fontSize: 13 }}>Не удалось отправить, попробуйте ещё раз.</span>}
          </div>
        )}
      </div>
    </div>
  );
}
