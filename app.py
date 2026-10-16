import os, time, hmac, hashlib, requests
from flask import Flask
app = Flask(__name__)

@app.route("/")
def index():
    try:
        key = os.getenv("BYBIT_KEY", "q5UQ797DWB7yrjwd3E")
        secret = os.getenv("BYBIT_SECRET")
        if not secret:
            return "<h1>AutoInvest MDP</h1>ERROR: Falta BYBIT_SECRET en Railway Variables"

        url = "https://api.bybit.com/v5/account/wallet-balance?accountType=UNIFIED"
        ts = str(int(time.time()*1000))
        rw = "5000"
        sign = hmac.new(secret.encode(), f"{ts}{key}{rw}accountType=UNIFIED".encode(), hashlib.sha256).hexdigest()
        headers = {"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": rw, "X-BAPI-SIGN": sign}
        data = requests.get(url, headers=headers, timeout=15).json()

        usdt = "0"
        if data.get("result"):
            for c in data["result"]["list"][0]["coin"]:
                if c["coin"] == "USDT":
                    usdt = c["walletBalance"]

        return f"<body style='background:#111;color:#fff;font-family:sans-serif;padding:30px'><h1>AutoInvest MDP</h1><h2>Balance: {usdt} USDT</h2><p style='color:#0f0'>ONLINE - EU ✅</p><p>Comision: 0</p></body>"
    except Exception as e:
        return f"<h1>AutoInvest MDP</h1>Error: {e}"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
