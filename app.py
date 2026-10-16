import os, ccxt
from flask import Flask, render_template_string, jsonify
API_KEY = "q5UQ797DWB7yrjwd3E"
API_SECRET = os.getenv("BYBIT_SECRET")
app = Flask(__name__)
bot_activo = True
def get_bybit():
    return ccxt.bybit({'apiKey': API_KEY, 'secret': API_SECRET, 'enableRateLimit': True})
HTML = """<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>MDP</title></head><body style="background:#111;color:#fff;font-family:sans-serif;padding:20px"><h2>AutoInvest MDP</h2><div id="b">Cargando...</div><script>async function l(){let r=await fetch('/api/balance');let j=await r.json();document.getElementById('b').innerHTML='Balance: '+j.usdt+' USDT<br>Comision: '+j.comision}setInterval(l,3000);l()</script></body></html>"""
@app.route('/')
def home(): return render_template_string(HTML)
@app.route('/api/balance')
def balance():
    try:
        ex=get_bybit();b=ex.fetch_balance();u=float(b.get('USDT',{}).get('free',0));return {"usdt":u,"comision":round(u*0.15,2),"activo":bot_activo}
    except Exception as e: return {"usdt":str(e),"comision":0,"activo":bot_activo}
@app.route('/api/toggle', methods=['POST'])
def toggle():
    global bot_activo;bot_activo=not bot_activo;return {"ok":True}
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv("PORT",8080)))
