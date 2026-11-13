// Куда уводит ссылка-вход /api/lab/mesh-review/session после того, как кука поставлена.
// Только относительный путь из короткого списка: за прокси req.url — внутренний адрес (https://0.0.0.0:3000),
// абсолютный редирект из него браузер не открывает (T-20261112-118/3); чужой адрес в to= — не открытый редирект.

export const LOGIN_TARGETS = ["/lab/mesh-review", "/lab/mesh-check"] as const;
export const DEFAULT_LOGIN_TARGET = LOGIN_TARGETS[0];

/** Путь из to=, если он в списке; иначе путь по умолчанию. */
export function loginTarget(to: string | null | undefined): string {
  return LOGIN_TARGETS.find((t) => t === to) ?? DEFAULT_LOGIN_TARGET;
}
