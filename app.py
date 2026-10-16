import os, time, hmac, hashlib, requests
from flask import Flask
app = Flask(__name__)

def bybit_request(secret, key, account_type):
    url = f"https://api.bybit.com/v5/account/wallet-balance?accountType={account_type}"
    ts = str(int(time.time()*1000))
    rw = "5000"
    param = f"{ts}{key}{rw}accountType={account_type}"
    sign = hmac.new(secret.encode(), param.encode(), hashlib.sha256).hexdigest()
    headers = {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": rw, "X-BAPI-SIGN": sign}
    return requests.get(url, headers=headers, timeout=15).json()

@app.route("/")
def index():
    key = os.getenv("BYBIT_KEY", "q5UQ797DWB7yrjwd3E")
    secret = os.getenv("BYBIT_SECRET")
    if not secret:
        return "Falta BYBIT_SECRET en Variables"

    results = []
    for acc in ["UNIFIED", "FUND", "SPOT"]:
        data = bybit_request(secret, key, acc)
        if data.get("result") and data["result"]["list"]:
            for coin in data["result"]["list"][0]["coin"]:
                bal = float(coin["walletBalance"])
                if bal > 0:
                    results.append(f"{coin['coin']}: {bal} ({acc})")

    if not results:
        return f"<body style='background:#111;color:#fff;padding:20px'><h1>AutoInvest MDP</h1><p>Balance 0 en todas las cuentas. Respuesta Bybit: {bybit_request(secret, key, 'UNIFIED')}</p></body>"

    html = "<br>".join(results)
    return f"<body style='background:#111;color:#fff;font-family:sans-serif;padding:30px'><h1>AutoInvest MDP</h1><h2>{html}</h2><p style='color:#0f0'>ONLINE - EU ✅</p><p>Comision: 0</p></body>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
