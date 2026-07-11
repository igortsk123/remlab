"""Общий слой ads-watchdog: env, state, клиенты Direct/Reports/Metrika/Gemini/Telegram.
Только stdlib. Все деньги — в рублях (returnMoneyInMicros=false)."""
import json, pathlib, time, urllib.request, urllib.error, urllib.parse

BASE = pathlib.Path("/opt/remlab/ads-watchdog")
CAMPAIGN_ID = 712721026
COUNTER_ID = 110599064
GOALS = {"01_project_started": 581463533, "02_photo_uploaded": 581463534,
         "03_preview_opened": 581463535, "04_preview_ready": 581463538,
         "05_paywall_viewed": 581463539, "06_pack_unlocked": 581463540}


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
