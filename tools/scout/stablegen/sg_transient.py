"""Краткие сбои связи с нодой покраски — одно место для моста и драйвера (T-20261120-153/1). Признаки — данные `rules/stablegen-transient.json`.
403 со страницей «Salad Connection Error» шлюз отдаёт, когда запрос НЕ дошёл до ComfyUI (перенос/перезапуск ноды), поэтому повторять можно и POST; 502–504 и обрывы связи — повторяем только безопасные (GET/HEAD)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, '..', 'rules', 'stablegen-transient.json')
SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def pause_s(rules: dict, attempt: int, key: str | None = None) -> float:
    ps = (rules.get(key) if key else rules)['pauses_s']
    return float(ps[min(attempt, len(ps) - 1)])


def response_reason(rules: dict, method: str, status: int, body: bytes) -> str | None:
    """Причина краткого сбоя ответа шлюза или None (ответ настоящий). Для POST — только то, что точно не дошло до ComfyUI."""
    r = rules['relay']
    text = body[:4000].decode('utf-8', 'replace')
    if status == 403:
        marks = r['forbidden_body_markers'] if method.upper() in SAFE_METHODS else r['post_safe_forbidden_markers']
        hit = next((m for m in marks if m in text), None)
        return f'403 {hit}' if hit else None
    if status in r['status_codes'] and method.upper() in SAFE_METHODS:
        return f'HTTP {status}'
    if status in r['post_safe_status_codes']:
        return f'HTTP {status}'
    return None


def error_reason(method: str, exc: Exception, connect_failed: bool) -> str | None:
    """Обрыв связи: повторяем безопасные методы всегда, остальные — только если соединение не было установлено (запрос не ушёл)."""
    if method.upper() in SAFE_METHODS or connect_failed:
        return f'{type(exc).__name__}'
    return None


def text_has_server_marker(rules: dict, text: str) -> bool:
    return any(m in str(text) for m in rules['drive']['server_markers'])


def relay_stats(port: int | None, timeout: float = 3.0) -> dict | None:
    """Счётчики повторов моста (/_relay/stats); моста нет/не отвечает — None."""
    if not port:
        return None
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/_relay/stats', timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None
