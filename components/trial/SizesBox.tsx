"use client";

// «Размеры своими словами» на странице ожидания (план agent-trial-08, Р2-текст): размеров нет (`job.askSizes`) — агент со своей ссылкой
// (`?k=`) пишет, что знает, одним полем; мы сами ставим размеры и обставляем. Текст уходит в `POST /api/trial/<id>/listing` (уже на v1 —
// «принято, применим после сборки»); повтор отправки того же текста — тот же `request_id` (без второй работы), новый текст — новый id
// (сервер заменит ещё не взятый). Состояние — из опроса задания (`job.listing`), самого текста сервер не возвращает.

import { useRef, useState, type FormEvent } from "react";
import l from "@/components/trial/landing.module.css";
import s from "@/components/trial/trial.module.css";
import { TRIAL_SIZES_TEXT_MAX, type TrialJobView } from "@/contracts/trial";
import { textOf, type TrialLang, type TrialText } from "@/lib/trial/i18n";

type Words = TrialText["sizes"];

export function newRequestId(): string {
  try { return crypto.randomUUID().replace(/-/g, ""); } catch { return `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`; }
}

/** Код отказа ручки → строка для агента. */
export function sendErrorText(code: unknown, t: Words): string {
  if (code === "source_gone") return t.sourceGone;
  if (code === "busy") return t.busy;
  if (code === "rebuild_limit") return t.limit;
  if (code === "forbidden") return t.forbidden;
  return t.error;
}

/** Что сейчас с текстом агента (по опросу задания); `sent` — только что отправили, а опрос ещё не догнал. */
export function listingNote(job: Pick<TrialJobView, "listing" | "listingError">, sent: boolean, t: Words): { text: string; bad: boolean } | null {
  if (job.listing === "accepted") return { text: t.accepted, bad: false };
  if (job.listing === "applying") return { text: t.applying, bad: false };
  if (job.listing === "done") return { text: t.done, bad: false };
  if (job.listing === "failed") return { text: job.listingError === "source_gone" ? t.sourceGone : t.failed, bad: true };
  return sent ? { text: t.accepted, bad: false } : null;
}

type Props = { id: string; k: string; lang: TrialLang; job: TrialJobView; onSent?: () => void };

export function SizesBox({ id, k, lang, job, onSent }: Props) {
  const t = textOf(lang).sizes;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const rid = useRef<string | null>(null);
  const note = listingNote(job, sent, t);
  const applying = job.listing === "applying";

  async function send(e: FormEvent) {
    e.preventDefault();
    const body = text.trim();
    if (!body || busy) return;
    rid.current ??= newRequestId();
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/trial/${encodeURIComponent(id)}/listing`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ k, request_id: rid.current, text: body }),
      });
      const j = (await res.json().catch(() => ({}))) as { error?: unknown };
      if (res.ok) { setSent(true); onSent?.(); } else setErr(sendErrorText(j.error, t));
    } catch {
      setErr(t.error); // сеть: тот же request_id при повторе — сервер не сделает работу дважды
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={s.sizes} onSubmit={(e) => void send(e)} data-testid="trial-sizes">
      <b>{t.title}</b>
      <p>{t.text}</p>
      <textarea aria-label={t.label} placeholder={t.placeholder} maxLength={TRIAL_SIZES_TEXT_MAX} value={text} disabled={busy}
        onChange={(e) => { setText(e.target.value); rid.current = null; setErr(null); }} />
      {err ? <p className={s.sizesErr} role="alert">{err}</p> : null}
      {!err && note ? <p className={note.bad ? s.sizesErr : s.sizesOk} role="status" data-testid="trial-sizes-state">{note.text}</p> : null}
      <button className={`${l.btn} ${l.btnSecondary}`} type="submit" disabled={busy || applying || !text.trim()}>
        {busy ? t.sending : t.send}
      </button>
    </form>
  );
}
