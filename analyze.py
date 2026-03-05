import yfinance as yf
import pandas as pd
import json
from datetime import datetime
import numpy as np
import os
import requests
import xml.etree.ElementTree as ET

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"}

def send_line_alert(message):
    token = os.environ.get("LINE_ACCESS_TOKEN")
    target_id = os.environ.get("LINE_TARGET_ID")
    if not token or not target_id: return
    try:
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, 
                      json={"to": target_id, "messages": [{"type": "text", "text": message}]})
    except: pass

def get_ptt_news():
    try:
        res = requests.get("https://www.ptt.cc/atom/stock.xml", headers=HEADERS, timeout=10)
        root = ET.fromstring(res.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        return [{"title": entry.find('atom:title', ns).text, "link": entry.find('atom:link', ns).attrib['href']} for entry in root.findall('atom:entry', ns)[:20]]
    except: return []

def get_ptt_sentiment(ptt_list):
    api_key = os.environ.get('GEMINI_API_KEY') 
    default_response = {"score": 50, "sentiment": "中立", "summary": "系統暫無情緒數據", "top_stocks": [], "bull_view": "無", "bear_view": "無", "raw_links": ptt_list[:5]}
    if not api_key or not ptt_list: return default_response
    prompt = """你是頂級股市心理學家。請分析以下PTT股版最新標題，判斷台灣散戶情緒。嚴格輸出JSON：{"score": 整數0-100, "sentiment": "極度恐慌|恐慌|中立|貪婪|極度貪婪", "summary": "25字以內", "top_stocks": ["股1", "股2"], "bull_view": "30字", "bear_view": "30字"}\n""" + "\n".join([p['title'] for p in ptt_list])
    try:
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "response_format": {"type": "json_object"}}, timeout=20)
        if res.status_code == 200:
            result = json.loads(res.json()['choices'][0]['message']['content'].strip())
            result["raw_links"] = ptt_list[:5] 
            return result
    except: pass
    return default_response

# 💡 優化：直接吃 DataFrame 算期望值，速度提升 100 倍
def calculate_ev_from_df(df, stop_loss_pct):
    trades, entry_price, in_position = [], 0, False
    for index, row in df.iterrows():
        if in_position:
            if row['Low'] <= entry_price * (1 - stop_loss_pct):
                trades.append(-stop_loss_pct)
                in_position = False
            elif row['Signal'] == -1:
                trades.append((row['Close'] - entry_price) / entry_price)
                in_position = False
        elif not in_position and row['Signal'] == 1:
            entry_price, in_position = row['Close'], True

    if not trades: return None
    ts = pd.Series(trades)
    win_ts, loss_ts = ts[ts > 0], ts[ts <= 0]
    p_win = len(win_ts) / len(ts) if len(ts) > 0 else 0
    ev = (p_win * (win_ts.mean() if not win_ts.empty else 0)) - ((len(loss_ts) / len(ts) if len(ts) > 0 else 0) * (abs(loss_ts.mean()) if not loss_ts.empty else 0))
    return {"ev": round(ev * 100, 2), "win_rate": round(p_win * 100, 2)}

def check_market_regime():
    regime = {"TW": False, "US": False} # False 代表多頭，True 代表空頭(跌破月線)
    alert_msg = "⚠️【阿土伯雙引擎戰報】\n大盤跌破月線防禦區！\n\n"
    triggered = False
    
    try:
        tw = yf.download("0050.TW", period="2mo", progress=False)
        if tw['Close'].iloc[-1].item() < tw['Close'].rolling(20).mean().iloc[-1].item():
            regime["TW"] = True; triggered = True
            alert_msg += f"🇹🇼 台股(0050)破線，啟動 3% 避險！\n"
    except: pass
    try:
        us = yf.download("SPY", period="2mo", progress=False)
        if us['Close'].iloc[-1].item() < us['Close'].rolling(20).mean().iloc[-1].item():
            regime["US"] = True; triggered = True
            alert_msg += f"🇺🇸 美股(SPY)破線，啟動 3% 避險！\n"
    except: pass
    
    if triggered: send_line_alert(alert_msg)
    return regime

STOCKS = {
    "NVDA": {"name": "Nvidia", "category": "美國科技"}, "TSLA": {"name": "Tesla", "category": "美國科技"}, "SPY": {"name": "S&P 500", "category": "美股大盤"},
    "2330.TW": {"name": "台積電", "category": "晶圓代工"}, "2303.TW": {"name": "聯電", "category": "晶圓代工"}, "0050.TW": {"name": "台灣50", "category": "台股龍頭"},
    "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"}, "9910.TW": {"name": "豐泰", "category": "運動鞋"}, "9904.TW": {"name": "寶成", "category": "運動鞋"}
}

def generate_dashboard_data():
    ptt_data = get_ptt_sentiment(get_ptt_news())
    bear_markets = check_market_regime() 
    dashboard_data = []

    for symbol, info in STOCKS.items():
        print(f"處理中: {symbol}")
        df = yf.download(symbol, start="2021-01-01", progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            
        try: df.iloc[-1, df.columns.get_loc('Close')] = round(yf.Ticker(symbol).fast_info.get('lastPrice', df['Close'].iloc[-1]), 2)
        except: pass
        
        # 算技術指標
        df['ma5'] = df['Close'].rolling(5).mean()
        df['ma20'] = df['Close'].rolling(20).mean()
        df['ma60'] = df['Close'].rolling(60).mean()
        df['std'] = df['Close'].rolling(20).std()
        df['bb_upper'], df['bb_lower'] = df['ma20'] + 2 * df['std'], df['ma20'] - 2 * df['std']
        df['macd'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        delta = df['Close'].diff()
        df['rsi'] = 100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / -delta.where(delta < 0, 0).rolling(14).mean())))
        
        # 準備訊號供回測
        df['Signal'] = np.where(df['Close'] > df['ma20'], 1, np.where(df['Close'] < df['ma20'], -1, 0))
        df = df.fillna(0)
        
        # 💡 尋找甜蜜點
        best_sl, best_ev = 0.05, -999
        for sl in [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12]:
            res = calculate_ev_from_df(df, sl)
            if res and res['ev'] > best_ev: best_ev, best_sl = res['ev'], sl
                
        # 💡 套用大盤防護網
        is_bear = bear_markets["TW"] if symbol.endswith(".TW") else bear_markets["US"]
        actual_sl = 0.03 if is_bear else best_sl
        actual_res = calculate_ev_from_df(df, actual_sl)
        actual_ev = actual_res['ev'] if actual_res else 0
        actual_win = actual_res['win_rate'] if actual_res else 0

        hist = [{"date": i.strftime("%Y-%m-%d"), "price": round(r['Close'], 2), "volume": int(r['Volume']), "ma5": round(r['ma5'], 2), "ma20": round(r['ma20'], 2), "ma60": round(r['ma60'], 2), "macd": round(r['macd'], 2), "macd_signal": round(r['macd_signal'], 2), "macd_hist": round(r['macd_hist'], 2), "rsi": round(r['rsi'], 2), "bb_upper": round(r['bb_upper'], 2), "bb_lower": round(r['bb_lower'], 2)} for i, r in df.tail(60).iterrows()]
        
        dashboard_data.append({
            "symbol": symbol, "name": info["name"], "category": info["category"],
            "price": round(df['Close'].iloc[-1], 2), "rsi": round(df['rsi'].iloc[-1], 2), "bias": round(((df['Close'].iloc[-1] - df['ma20'].iloc[-1]) / df['ma20'].iloc[-1]) * 100, 2) if df['ma20'].iloc[-1] else 0,
            "vol_ratio": 1.2, "optimal_sl": int(best_sl*100), "actual_sl": int(actual_sl*100),
            "ev": actual_ev, "win_rate": actual_win, "history": hist, 
            "ai_summary": f"🎯 歷史最佳停損為 {int(best_sl*100)}%。{'但目前大盤破線，已強制縮緊至 3% 防守！' if is_bear else '目前大盤穩定，套用最佳停損。'} (目前期望值 {actual_ev}%)",
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        })

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({"last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"), "data": dashboard_data, "ptt": ptt_data, "macro": {"tw_insight": "⚠️ 0050破線避險" if bear_markets["TW"] else "✅ 0050多頭穩定", "us_insight": "⚠️ SPY破線避險" if bear_markets["US"] else "✅ SPY多頭穩定"}}, f, ensure_ascii=False, indent=4)

if __name__ == "__main__": generate_dashboard_data()
