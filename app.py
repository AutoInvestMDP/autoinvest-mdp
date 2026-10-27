import os
import time
import hmac
import hashlib
import sqlite3
import threading
import requests
from flask import Flask, request, Response, render_template_string, jsonify

app = Flask(__name__)

BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com")
RECV_WINDOW = "5000"
CACHE_TTL = 30
SNAPSHOT_EVERY = int(os.getenv("SNAPSHOT_MINUTES", "15")) * 60
WATCHLIST = [c.strip().upper() for c in os.getenv("WATCHLIST", "BTC,ETH,SOL").split(",") if c.strip()]
DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = os.getenv("DB_PATH", "/data/history.db" if os.path.isdir("/data") else "history.db")
STABLES = {"USDT", "USDC", "USD"}

_cache = {}


def cached(name, fn, ttl=CACHE_TTL):
    now = time.time()
    hit = _cache.get(name)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[name] = (now, val)
    return val


# ---------- Seguridad ----------
@app.before_request
def require_auth():
    if request.path == "/health":
        return None
    user = os.getenv("PANEL_USER", "admin")
    pwd = os.getenv("PANEL_PASS")
    if not pwd:
        return Response("Configurá PANEL_PASS en las variables de entorno", 503)
    auth = request.authorization
    ok = (
        auth
        and hmac.compare_digest(auth.username or "", user)
        and hmac.compare_digest(auth.password or "", pwd)
    )
    if not ok:
        return Response("Login requerido", 401,
                        {"WWW-Authenticate": 'Basic realm="AutoInvest MDP"'})


# ---------- Bybit ----------
def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fmt_time(ms):
    try:
        return time.strftime("%d/%m %H:%M", time.gmtime(int(ms) / 1000))
    except (TypeError, ValueError):
        return "-"


def bybit_get(path, params, signed=True):
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    headers = {}
    if signed:
        key = os.getenv("BYBIT_KEY")
        secret = os.getenv("BYBIT_SECRET")
        if not key or not secret:
            return {"retCode": -1, "retMsg": "Falta BYBIT_KEY o BYBIT_SECRET en las variables de entorno"}
        ts = str(int(time.time() * 1000))
        payload = f"{ts}{key}{RECV_WINDOW}{query}"
        sign = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {
            "X-BAPI-API-KEY": key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": sign,
        }
    try:
        r = requests.get(f"{BASE_URL}{path}?{query}", headers=headers, timeout=15)
    except requests.RequestException as e:
        return {"retCode": -2, "retMsg": f"Error de red: {e}"}
    try:
        return r.json()
    except ValueError:
        return {"retCode": -3,
                "retMsg": f"Respuesta no válida de Bybit (HTTP {r.status_code}). "
                          "Si es 403, Bybit puede estar bloqueando la región/IP del servidor."}


def err_text(label, data):
    return f"{label}: {data.get('retCode')} - {data.get('retMsg')}"


def fetch_prices():
    data = bybit_get("/v5/market/tickers", {"category": "spot"}, signed=False)
    if data.get("retCode") != 0:
        return {}, err_text("PRECIOS", data)
    prices = {}
    for t in (data.get("result") or {}).get("list", []):
        s = t.get("symbol", "")
        if s.endswith("USDT"):
            prices[s[:-4]] = {
                "price": to_float(t.get("lastPrice")),
                "change": to_float(t.get("price24hPcnt")) * 100,
            }
    return prices, None


def coin_price(coin, prices):
    if coin in STABLES:
        return 1.0
    return prices.get(coin, {}).get("price", 0.0)


def fetch_unified():
    data = bybit_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    if data.get("retCode") != 0:
        return [], 0.0, err_text("UNIFIED", data)
    lst = (data.get("result") or {}).get("list") or []
    if not lst:
        return [], 0.0, None
    acc = lst[0]
    coins = []
    for c in acc.get("coin", []):
        bal = to_float(c.get("walletBalance"))
        if bal > 0:
            coins.append({"coin": c["coin"], "balance": bal,
                          "usd": to_float(c.get("usdValue")), "account": "UNIFIED"})
    return coins, to_float(acc.get("totalEquity")), None


def fetch_fund(prices):
    data = bybit_get("/v5/asset/transfer/query-account-coins-balance", {"accountType": "FUND"})
    if data.get("retCode") != 0:
        return [], err_text("FUND", data)
    coins = []
    for c in (data.get("result") or {}).get("balance", []):
        bal = to_float(c.get("walletBalance"))
        if bal > 0:
            coins.append({"coin": c["coin"], "balance": bal,
                          "usd": bal * coin_price(c["coin"], prices), "account": "FUND"})
    return coins, None


def fetch_positions():
    data = bybit_get("/v5/position/list", {"category": "linear", "settleCoin": "USDT", "limit": 50})
    if data.get("retCode") != 0:
        return [], err_text("POSICIONES", data)
    rows = []
    for p in (data.get("result") or {}).get("list", []):
        if to_float(p.get("size")) > 0:
            rows.append({
                "symbol": p.get("symbol"), "side": p.get("side"),
                "size": to_float(p.get("size")), "entry": to_float(p.get("avgPrice")),
                "mark": to_float(p.get("markPrice")), "pnl": to_float(p.get("unrealisedPnl")),
                "lev": p.get("leverage"),
            })
    return rows, None


def fetch_closed_pnl():
    data = bybit_get("/v5/position/closed-pnl", {"category": "linear", "limit": 20})
    if data.get("retCode") != 0:
        return [], err_text("HISTORIAL", data)
    rows = []
    for p in (data.get("result") or {}).get("list", []):
        rows.append({
            "symbol": p.get("symbol"), "side": p.get("side"),
            "entry": to_float(p.get("avgEntryPrice")), "exit": to_float(p.get("avgExitPrice")),
            "pnl": to_float(p.get("closedPnl")),
            "time": fmt_time(p.get("updatedTime") or p.get("createdTime")),
        })
    return rows, None


def build_dashboard():
    errors = []
    prices, e = fetch_prices()
    if e: errors.append(e)
    uni, uni_equity, e = fetch_unified()
    if e: errors.append(e)
    fund, e = fetch_fund(prices)
    if e: errors.append(e)
    positions, e = fetch_positions()
    if e: errors.append(e)
    closed, e = fetch_closed_pnl()
    if e: errors.append(e)

    fund_usd = sum(c["usd"] for c in fund)
    watch = [{"coin": c, **prices[c]} for c in WATCHLIST if c in prices]
    return {
        "balances": uni + fund,
        "total_usd": uni_equity + fund_usd,
        "watch": watch,
        "positions": positions,
        "unrealized": sum(p["pnl"] for p in positions),
        "closed": closed,
        "errors": errors,
        "updated": time.strftime("%H:%M:%S UTC", time.gmtime()),
    }


def get_dashboard(force=False):
    if force:
        _cache.pop("dash", None)
    return cached("dash", build_dashboard)


# ---------- Historial del balance (Postgres externo o SQLite) ----------
def db():
    if DATABASE_URL:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        with conn, conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS snapshots (ts BIGINT PRIMARY KEY, equity DOUBLE PRECISION)")
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS snapshots (ts INTEGER PRIMARY KEY, equity REAL)")
    return conn


def save_snapshot(equity):
    ts = int(time.time())
    if DATABASE_URL:
        conn = db()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("INSERT INTO snapshots VALUES (%s, %s) ON CONFLICT (ts) DO NOTHING", (ts, equity))
        finally:
            conn.close()
    else:
        with db() as conn:
            conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?)", (ts, equity))


def load_history(limit=500):
    q = "SELECT ts, equity FROM (SELECT ts, equity FROM snapshots ORDER BY ts DESC LIMIT {p}) t ORDER BY ts"
    if DATABASE_URL:
        conn = db()
        try:
            with conn.cursor() as cur:
                cur.execute(q.format(p="%s"), (limit,))
                rows = cur.fetchall()
        finally:
            conn.close()
    else:
        with db() as conn:
            rows = conn.execute(q.format(p="?"), (limit,)).fetchall()
    return [{"t": time.strftime("%d/%m %H:%M", time.gmtime(ts)), "v": round(eq, 2)} for ts, eq in rows]


def snapshot_loop():
    while True:
        try:
            d = get_dashboard(force=True)
            if d["total_usd"] > 0:
                save_snapshot(d["total_usd"])
        except Exception as e:
            print("snapshot error:", e, flush=True)
        time.sleep(SNAPSHOT_EVERY)


threading.Thread(target=snapshot_loop, daemon=True).start()


# ---------- Web ----------
TEMPLATE = """
<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoInvest MDP</title>
<style>
  body{background:#0e0e10;color:#fff;font-family:Inter,system-ui,sans-serif;padding:12px;margin:0}
  .card{background:#1a1a1d;border:1px solid #2a2a2e;border-radius:16px;padding:20px;max-width:560px;margin:16px auto}
  h1{font-size:22px;margin:0 0 6px} h2{font-size:15px;margin:0 0 10px;color:#aaa;font-weight:600}
  .status{color:#00ff88;font-weight:bold;margin:0}
  .total{font-size:30px;font-weight:700;margin:10px 0}
  .row{display:flex;justify-content:space-between;gap:8px;font-size:15px;padding:8px 0;border-bottom:1px solid #222}
  .row:last-child{border-bottom:0}
  .pos{color:#00ff88} .neg{color:#ff6b6b}
  .error{background:#2a1111;color:#ff6b6b;padding:10px;border-radius:10px;margin:8px 0;word-break:break-word;font-size:13px}
  small{color:#888} .right{text-align:right}
  button{background:#2a2a2e;color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer}
</style></head><body>

<div class="card">
  <h1>AutoInvest MDP</h1>
  <p class="status">● ONLINE</p>
  <div class="total">${{ "%.2f"|format(d.total_usd) }}</div>
  <small>Balance total estimado (Unified + Fund)</small>
  {% for e in d.errors %}<div class="error">{{ e }}</div>{% endfor %}
</div>

<div class="card">
  <h2>Evolución del balance</h2>
  <canvas id="chart" height="160"></canvas>
  <small id="nohist" style="display:none">Todavía no hay datos. Se guarda un punto cada {{ mins }} min.</small>
</div>

{% if d.watch %}
<div class="card">
  <h2>Precios</h2>
  {% for w in d.watch %}
  <div class="row">
    <span>{{ w.coin }}</span>
    <span>${{ "{:,.2f}".format(w.price) }}
      <small class="{{ 'pos' if w.change >= 0 else 'neg' }}">{{ "%+.2f"|format(w.change) }}%</small></span>
  </div>
  {% endfor %}
</div>
{% endif %}

<div class="card">
  <h2>Balances</h2>
  {% for b in d.balances %}
  <div class="row">
    <span>{{ b.coin }} <small>({{ b.account }})</small></span>
    <span class="right">{{ "%.8g"|format(b.balance) }}
      {% if b.usd %}<small>≈ ${{ "%.2f"|format(b.usd) }}</small>{% endif %}</span>
  </div>
  {% else %}
  <p>Sin balances.</p>
  {% endfor %}
</div>

<div class="card">
  <h2>Posiciones abiertas
    {% if d.positions %}<small class="{{ 'pos' if d.unrealized >= 0 else 'neg' }}">
      PnL no realizado: {{ "%+.2f"|format(d.unrealized) }} USDT</small>{% endif %}</h2>
  {% for p in d.positions %}
  <div class="row">
    <span>{{ p.symbol }} <small>{{ p.side }} x{{ p.lev }}</small><br>
      <small>entrada {{ p.entry }} · mark {{ p.mark }}</small></span>
    <span class="right {{ 'pos' if p.pnl >= 0 else 'neg' }}">{{ "%+.2f"|format(p.pnl) }}</span>
  </div>
  {% else %}
  <p><small>No hay posiciones abiertas.</small></p>
  {% endfor %}
</div>

<div class="card">
  <h2>Últimas operaciones cerradas</h2>
  {% for c in d.closed %}
  <div class="row">
    <span>{{ c.symbol }} <small>{{ c.side }} · {{ c.time }}</small><br>
      <small>{{ c.entry }} → {{ c.exit }}</small></span>
    <span class="right {{ 'pos' if c.pnl >= 0 else 'neg' }}">{{ "%+.2f"|format(c.pnl) }}</span>
  </div>
  {% else %}
  <p><small>Sin operaciones cerradas.</small></p>
  {% endfor %}
</div>

<div class="card" style="text-align:center">
  <small>Actualizado: {{ d.updated }} · caché {{ ttl }}s</small><br><br>
