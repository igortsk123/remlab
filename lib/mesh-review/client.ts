// Клиентский слой /lab/mesh-review: сетевые вызовы отдельно от UI (code-standards).

export interface ReviewTask {
  id: number;
  taskKey: string;
  sku: string;
  role: string | null;
  contract: string;
  payload: {
    photo?: string; // data-URL карточки товара
    renders?: Record<string, string>; // "0"|"90"|"180"|"270" → data-URL
    name?: string;
    source?: string; // почему спорный
  };
}

export type LoadResult = { kind: "ok"; tasks: ReviewTask[] } | { kind: "login" } | { kind: "error"; message: string };

export async function loadTasks(): Promise<LoadResult> {
  try {
    const r = await fetch("/api/lab/mesh-review/tasks");
    if (r.status === 401) return { kind: "login" };
    if (!r.ok) return { kind: "error", message: `HTTP ${r.status}` };
    const data = (await r.json()) as { tasks: ReviewTask[] };
    return { kind: "ok", tasks: data.tasks };
  } catch (e) {
    return { kind: "error", message: e instanceof Error ? e.message : "не загрузилось" };
  }
}

export async function loginWithSecret(secret: string): Promise<"ok" | "wrong" | "unavailable"> {
  const r = await fetch("/api/lab/mesh-review/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ secret }),
  });
  if (r.ok) return "ok";
  return r.status === 401 ? "wrong" : "unavailable";
}

export async function sendDecision(task: ReviewTask, choice: string): Promise<boolean> {
  const r = await fetch("/api/lab/mesh-review/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ taskId: task.id, choice, idemKey: `${task.taskKey}:${choice}` }),
  });
  return r.ok;
}
