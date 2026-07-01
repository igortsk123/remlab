// Типизированный результат вместо throw для внешних вызовов (architecture.md: Result<T,E>).
// Провайдеры/интеграции возвращают Result — вызывающий обязан обработать ветку ошибки.

export type Ok<T> = { ok: true; value: T };
export type Err<E> = { ok: false; error: E };
export type Result<T, E> = Ok<T> | Err<E>;

export function ok<T>(value: T): Ok<T> {
  return { ok: true, value };
}

export function err<E>(error: E): Err<E> {
  return { ok: false, error };
}
