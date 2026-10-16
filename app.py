import os, ccxt
from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    try:
        exchange = ccxt.bybit({
            'apiKey': os.getenv("BYBIT_KEY", "9Q3LQW5M3O"),
            'secret': os.getenv("BYBIT_SECRET"),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            },
            'urls': {
                'api': {
                    'public': 'https://api.bybit.com',
                    'private': 'https://api.bybit.com',
                }
            }
        })
        # Fuerza a no usar el endpoint de instruments que te bloquea
        balance = exchange.fetch_balance()
        usdt = balance['USDT']['free'] if 'USDT' in balance else balance['total'].get('USDT', 0)
        return f"<h1>AutoInvest MDP</h1>Balance: {usdt} USDT<br>Comision: 0<br>ESTADO: ONLINE ✅"
    except Exception as e:
        return f"<h1>AutoInvest MDP</h1>Balance: ERROR TEMPORAL<br>Detalle: {e}<br>USDT<br>Comision: 0<br>Intentando reconectar..."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
