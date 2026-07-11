"""Общий слой ads-watchdog: env, state, клиенты Direct/Reports/Metrika/Gemini/Telegram.
Только stdlib. Все деньги — в рублях (returnMoneyInMicros=false)."""
import json, pathlib, time, urllib.request, urllib.error, urllib.parse

BASE = pathlib.Path("/opt/remlab/ads-watchdog")
COUNTER_ID = 110599064

# Все наши кампании: id → (роль, описание сервиса для Gemini-минусовки — «мусор» у каждой свой).
CAMPAIGNS = {
    712722345: ("Этап 1 — Калькуляторы",
                "калькулятор материалов: сколько нужно обоев/плитки/краски/ламината и смета-список покупок"),
    712722343: ("Этап 2 — Сколько стоит ремонт",
                "расчёт стоимости ремонта комнаты: вилка бюджета (эконом/средний/дороже), работы и материалы, смета"),
    712721026: ("AI-дизайн (ступень М5)",
                "нейросеть делает дизайн интерьера жилой комнаты по фото"),
    712722344: ("Ванная (пауза)",
                "дизайн ванной комнаты и раскладка плитки"),
}
OUR_CAMPAIGN_IDS = list(CAMPAIGNS)

# Воронка сметы (главная в v0.4). AI-воронка (01–06) — legacy, в отчёте не показываем.
GOALS = {"calc_started": 581529922, "estimate_opened": 581529923,
         "estimate_saved": 581529924, "ref_click": 581530035}


def load_env():
    env = {}
    for line in (BASE / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env()
DRY = ENV.get("DRY_RUN", "1") != "0"


def disabled() -> bool:
    return (BASE / "DISABLED").exists()


def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def state_load() -> dict:
    p = BASE / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def state_save(st: dict):
    (BASE / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=1))


def _http(url: str, data: bytes | None, headers: dict, timeout: int = 60):
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


def direct(resource: str, method: str, params: dict) -> dict:
    body = json.dumps({"method": method, "params": params}).encode()
    code, _, text = _http("https://api.direct.yandex.com/json/v5/" + resource, body, {
        "Authorization": f"Bearer {ENV['YANDEX_DIRECT_TOKEN']}", "Accept-Language": "ru",
        "Content-Type": "application/json; charset=utf-8"})
    out = json.loads(text)
    if "error" in out:
        raise RuntimeError(f"Direct {resource}.{method}: {out['error']}")
    return out["result"]


def direct_report(name: str, report_type: str, fields: list[str], date_range: str = "TODAY",
                  filters: list | None = None) -> list[list[str]]:
    """TSV-отчёт без заголовков; офлайн-очередь с polling (до ~4 мин)."""
    sel = {"Filter": filters} if filters else {}
    body = json.dumps({"params": {
        "SelectionCriteria": sel, "FieldNames": fields, "ReportName": name,
        "ReportType": report_type, "DateRangeType": date_range, "Format": "TSV",
        "IncludeVAT": "YES", "IncludeDiscount": "NO"}}).encode()
    headers = {"Authorization": f"Bearer {ENV['YANDEX_DIRECT_TOKEN']}", "Accept-Language": "ru",
               "Content-Type": "application/json; charset=utf-8", "processingMode": "auto",
               "returnMoneyInMicros": "false", "skipReportHeader": "true",
               "skipColumnHeader": "true", "skipReportSummary": "true"}
    for _ in range(16):
        code, hdrs, text = _http("https://api.direct.yandex.com/json/v5/reports", body, headers, 120)
        if code == 200:
            return [row.split("\t") for row in text.splitlines() if row.strip()]
        if code in (201, 202):
            time.sleep(int(hdrs.get("retryIn", 15)))
            continue
        raise RuntimeError(f"reports HTTP {code}: {text[:300]}")
    raise RuntimeError("reports: очередь не отдала отчёт за отведённое время")


def metrika_today() -> dict:
    metrics = ["ym:s:visits"] + [f"ym:s:goal{g}reaches" for g in GOALS.values()]
    url = ("https://api-metrika.yandex.net/stat/v1/data?ids=" + str(COUNTER_ID) +
           "&metrics=" + ",".join(metrics) + "&date1=today&date2=today&accuracy=full")
    code, _, text = _http(url, None, {"Authorization": f"OAuth {ENV['YANDEX_DIRECT_TOKEN']}"})
    if code != 200:
        raise RuntimeError(f"metrika HTTP {code}: {text[:200]}")
    data = json.loads(text)
    totals = data.get("totals") or [0] * len(metrics)
    if totals and isinstance(totals[0], list):  # с dimensions Метрика вкладывает список
        totals = totals[0]
    out = {"visits": int(totals[0])}
    for (name, _), val in zip(GOALS.items(), totals[1:]):
        out[name] = int(val)
    return out


def gemini(prompt: str) -> str:
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.2}}).encode()
    code, _, text = _http(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
        body, {"X-goog-api-key": ENV["GEMINI_API_KEY"], "Content-Type": "application/json"}, 90)
    if code != 200:
        raise RuntimeError(f"gemini HTTP {code}: {text[:200]}")
    data = json.loads(text)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def openai_chat(prompt: str) -> str:
    """GPT для генерации текстов объявлений (бенч 2026-07-11: русский естественнее Gemini)."""
    body = json.dumps({"model": ENV.get("OPENAI_AD_MODEL", "gpt-5.1-chat-latest"),
                       "messages": [{"role": "user", "content": prompt}],
                       "max_completion_tokens": 2000}).encode()
    code, _, text = _http("https://api.openai.com/v1/chat/completions", body, {
        "Authorization": f"Bearer {ENV['OPENAI_API_KEY']}",
        "Content-Type": "application/json"}, 120)
    if code != 200:
        raise RuntimeError(f"openai HTTP {code}: {text[:200]}")
    return json.loads(text)["choices"][0]["message"]["content"]


def llm_for_ads(prompt: str) -> str:
    """Тексты объявлений: GPT-5.1, при недоступности — фолбэк на Gemini."""
    if ENV.get("OPENAI_API_KEY"):
        try:
            return openai_chat(prompt)
        except Exception as e:
            log(f"openai fail → gemini fallback: {e}")
    return gemini(prompt)


def tg(text: str):
    prefix = "🧪 [РЕПЕТИЦИЯ] " if DRY else ""
    data = urllib.parse.urlencode({"chat_id": ENV["TG_CHAT_ID"], "text": prefix + text}).encode()
    code, _, resp = _http(f"https://api.telegram.org/bot{ENV['TG_BOT_TOKEN']}/sendMessage",
                          data, {"Content-Type": "application/x-www-form-urlencoded"})
    if code != 200:
        log(f"TG FAIL {code}: {resp[:200]}")


def remember_action(st: dict, what: str):
    st.setdefault("actions", []).append({"ts": time.strftime("%Y-%m-%d %H:%M"), "what": what})
    st["actions"] = st["actions"][-50:]
