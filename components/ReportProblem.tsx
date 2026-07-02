"use client";

// Кнопка «Сообщить о проблеме» на превью: шлёт номер генерации (+ короткий комментарий) на сервер.
// По этому номеру потом делаем разбор трейса. Состояния: idle / форма / отправка / успех / ошибка.

import { useState } from "react";

type State = "idle" | "form" | "sending" | "done" | "error";

export function ReportProblem({ seq }: { seq: number }) {
  const [state, setState] = useState<State>("idle");
  const [comment, setComment] = useState("");

  async function send() {
    setState("sending");
    try {
      const res = await fetch("/api/trace/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seq, comment }),
      });
      setState(res.ok ? "done" : "error");
    } catch {
      setState("error");
    }
  }

  if (state === "done") {
    return <p className="muted" style={{ marginTop: 12 }}>Спасибо! Передали проблему по генерации #{seq}.</p>;
  }

  if (state === "idle") {
    return (
      <button className="btn btn-ghost" style={{ marginTop: 12 }} onClick={() => setState("form")}>
        Сообщить о проблеме
      </button>
    );
  }

  return (
    <div className="stack" style={{ marginTop: 12 }}>
      <textarea
        className="input"
        rows={3}
        placeholder="Что не так с результатом? (необязательно)"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      {state === "error" && <p className="note">Не отправилось. Попробуйте ещё раз.</p>}
      <div className="row">
        <button className="btn" onClick={send} disabled={state === "sending"}>
          {state === "sending" ? "Отправляем…" : "Отправить"}
        </button>
        <button className="btn btn-ghost" onClick={() => setState("idle")}>Отмена</button>
      </div>
    </div>
  );
}
