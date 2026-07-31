"use client";

// Кнопка «Сообщить о проблеме» на превью: шлёт номер генерации (+ короткий комментарий) на сервер.
// По этому номеру потом делаем разбор трейса. Состояния: idle / форма / отправка / успех / ошибка.

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { TextArea } from "@/components/base/textarea/textarea";

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
      <Button color="tertiary" size="md" className="mt-3" onClick={() => setState("form")}>
        Сообщить о проблеме
      </Button>
    );
  }

  return (
    <div className="stack" style={{ marginTop: 12 }}>
      <TextArea
        rows={3}
        placeholder="Что не так с результатом? (необязательно)"
        value={comment}
        onChange={setComment}
        aria-label="Что не так с результатом?"
      />
      {state === "error" && <p className="note">Не отправилось. Попробуйте ещё раз.</p>}
      <div className="row">
        <Button size="md" onClick={send} isLoading={state === "sending"} isDisabled={state === "sending"}>
          {state === "sending" ? "Отправляем…" : "Отправить"}
        </Button>
        <Button color="tertiary" size="md" onClick={() => setState("idle")}>Отмена</Button>
      </div>
    </div>
  );
}
