"use client";

// Форма первого экрана лендинга `/try` (план agent-trial-01, T-C; вид — макет v3-en-final, TG 420): файл плана (PDF или фото,
// ≤ 15 МБ) и необязательный текст с размерами → `POST /api/trial` (multipart, потоком на сервере) → `/try/<id>`.
// Почты нет до T9 (минимизация ПДн). XHR, а не fetch: на медленной связи 15 МБ грузятся долго — показываем проценты.
// Язык (план agent-trial-08, П) — тексты формы и ошибок, и он же уходит дальше: `/try/<id>?lang=…` → тур.

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import l from "@/components/trial/landing.module.css";
import { rememberFileName } from "@/components/trial/useTrialJob";
import { textOf, withLang, type TrialLang } from "@/lib/trial/i18n";
import { uploadErrorText } from "@/lib/trial/steps";

const MAX_BYTES = 15 * 1024 * 1024; // = lib/trial/config.ts:TRIAL_FILE_MAX_BYTES (серверный модуль сюда не тянем)
const TYPES = /\.(pdf|jpe?g|png|webp)$/i;
const size = (b: number, t: { mb: string; kb: string }, lang: TrialLang) => {
  const n = b >= 1024 * 1024 ? (b / 1024 / 1024).toFixed(1) : String(Math.max(1, Math.round(b / 1024)));
  return `${lang === "ru" ? n.replace(".", ",") : n} ${b >= 1024 * 1024 ? t.mb : t.kb}`;
};
type Reply = { status: number; body: { id?: string; url?: string; error?: string }; retryAfterSec: number | null };

function send(data: FormData, onProgress: (p: number) => void): Promise<Reply> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", "/api/trial");
    x.responseType = "json";
    x.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    x.onload = () => {
      const ra = Number(x.getResponseHeader("Retry-After"));
      resolve({ status: x.status, body: (x.response ?? {}) as Reply["body"], retryAfterSec: Number.isFinite(ra) && ra > 0 ? ra : null });
    };
    x.onerror = () => reject(new Error("network"));
    x.send(data);
  });
}

const UploadIcon = () => (
  <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
  </svg>
);

export function UploadForm({ lang }: { lang: TrialLang }) {
  const t = textOf(lang).form;
  const router = useRouter();
  const box = useRef<HTMLDetailsElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [over, setOver] = useState(false);
  // как в макете: на широком экране поле размеров раскрыто сразу
  useEffect(() => { if (box.current && window.innerWidth >= 768) box.current.open = true; }, []);

  const choose = (f: File | undefined) => {
    setError(null);
    if (!f) return;
    if (!TYPES.test(f.name)) { setFile(null); setError(uploadErrorText("unsupported_type", lang)); return; }
    if (f.size > MAX_BYTES) { setFile(null); setError(uploadErrorText("too_large", lang)); return; }
    setFile(f);
  };
  const drop = (e: DragEvent<HTMLLabelElement>) => { e.preventDefault(); setOver(false); choose(e.dataTransfer.files[0]); };

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!file) { setError(uploadErrorText("no_file", lang)); return; }
    const data = new FormData();
    data.set("listing", String(new FormData(e.currentTarget).get("listing") ?? "").trim());
    // TODO(legal): строка согласия — решение владельца
    data.set("consent", "yes");
    data.set("file", file);
    setError(null);
    setProgress(0);
    try {
      const r = await send(data, setProgress);
      if (r.status === 201 && r.body.url) {
        if (r.body.id) rememberFileName(r.body.id, file.name);
        router.push(withLang(r.body.url, lang));
        return;
      }
      setError(uploadErrorText(r.body.error, lang, r.retryAfterSec));
    } catch {
      setError(uploadErrorText(undefined, lang));
    }
    setProgress(null);
  };

  const busy = progress !== null;
  return (
    <form className={`${l.card} ${l.upload}`} onSubmit={submit} noValidate>
      <label className={l.drop} data-over={over ? "1" : "0"} onDrop={drop}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}>
        <UploadIcon />
        {file ? (
          <div><b>{file.name}</b><span>{size(file.size, t, lang)} · <u>{t.chooseOther}</u></span></div>
        ) : (
          <div><b>{t.drop}</b><span>{t.kinds} · <u>{t.choose}</u></span></div>
        )}
        <input type="file" name="file" accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"
          className="sr-only" onChange={(e) => choose(e.target.files?.[0])} disabled={busy} />
      </label>
      <details className={l.field} ref={box}>
        <summary><span>{t.sizesSummary} <em>· {t.optional}</em></span></summary>
        <textarea name="listing" aria-label={t.sizesLabel} placeholder={t.sizesPlaceholder} maxLength={5000} disabled={busy} />
      </details>
      {error ? <p className={l.err} role="alert">{error}</p> : null}
      <div className={l.actions}>
        <button className={`${l.btn} ${l.btnPrimary}`} type="submit" disabled={busy}>
          {busy ? `${t.uploading} ${Math.round((progress ?? 0) * 100)}%` : t.upload}
        </button>
        <a className={`${l.btn} ${l.btnSecondary}`} href="#example">{t.example}</a>
      </div>
    </form>
  );
}
