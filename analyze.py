import yfinance as yf
import feedparser
import pandas as pd
from datetime import datetime
import json
import numpy as np
import os
import requests
import re
import time
import urllib.parse

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

def calculate_ev_from_df(df, stop_loss_pct):
    trades, entry_price, in_position, peak_price = [], 0, False, 0 
    for index, row in df.iterrows():
        if in_position:
            peak_price = max(peak_price, row['High'])
            actual_exit_price = max(entry_price * (1 - stop_loss_pct), peak_price * (1 - stop_loss_pct))
            if row['Low'] <= actual_exit_price:
                trades.append((actual_exit_price - entry_price) / entry_price)
                in_position = False
            elif row['Signal'] == -1:
                trades.append((row['Close'] - entry_price) / entry_price)
                in_position = False
        elif not in_position and row['Signal'] == 1:
            entry_price, in_position, peak_price = row['Close'], True, row['Close']

    if not trades: return None
    ts = pd.Series(trades)
    win_ts, loss_ts = ts[ts > 0], ts[ts <= 0]
    p_win = len(win_ts) / len(ts) if len(ts) > 0 else 0
    ev = (p_win * (win_ts.mean() if not win_ts.empty else 0)) - ((len(loss_ts) / len(ts) if len(ts) > 0 else 0) * (abs(loss_ts.mean()) if not loss_ts.empty else 0))
    return {"ev": round(ev * 100, 2), "win_rate": round(p_win * 100, 2)}

def check_market_regime():
    regime = {"TW": False, "US": False} 
    alert_msg = "⚠️【阿土伯雙引擎戰報】\n"
    triggered = False
    try:
        tw = yf.download("0050.TW", period="2mo", progress=False)
        if tw['Close'].iloc[-1].item() < tw['Close'].rolling(20).mean().iloc[-1].item():
            regime["TW"] = True; triggered = True
            alert_msg += f"🇹🇼 台股(0050)破線，啟動避險！\n"
    except: pass
    try:
        us = yf.download("SPY", period="2mo", progress=False)
        if us['Close'].iloc[-1].item() < us['Close'].rolling(20).mean().iloc[-1].item():
            regime["US"] = True; triggered = True
            alert_msg += f"🇺🇸 美股(SPY)破線，啟動避險！\n"
    except: pass
    if triggered: send_line_alert(alert_msg)
    return regime

STOCKS = {
    "NVDA": {"name": "Nvidia", "category": "美國科技"}, "TSLA": {"name": "Tesla", "category": "美國科技"}, "SPY": {"name": "S&P 500", "category": "美股大盤"},
    "2330.TW": {"name": "台積電", "category": "晶圓代工"}, "2337.TW": {"name": "旺宏", "category": "記憶體"},"3105.TWO": {"name": "穩懋", "category": "半導體"},
    "0050.TW": {"name": "台灣50", "category": "台股龍頭"},"00981A.TW": {"name": "主動統一台股增長", "category": "台股"}, "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"}, "9910.TW": {"name": "豐泰", "category": "運動鞋"}, 
    "9904.TW": {"name": "寶成", "category": "運動鞋"}
}

def get_ai_news_sentiment(stock_name, symbol):
    try:
        search_keyword = f"{stock_name} 股票" if not symbol.endswith(".TW") else stock_name
        query = urllib.parse.quote(f"{search_keyword} when:15d")
        res = requests.get(f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant", headers=HEADERS, timeout=10)
        feed = feedparser.parse(res.text)
        top_news = []
        for entry in feed.entries[:5]:
            pub_time_str = time.strftime("%Y-%m-%d", entry.published_parsed) if hasattr(entry, 'published_parsed') else datetime.now().strftime("%Y-%m-%d")
            top_news.append({"title": entry.title.rsplit(" - ", 1)[0], "link": entry.link, "date": pub_time_str})
            
        if not top_news: return [{"title": "近期無重大新聞", "sentiment": "中立", "link": "#", "date": datetime.now().strftime("%Y-%m-%d")}]

        groq_api_key = os.environ.get("GROQ_API_KEY")
        if not groq_api_key: return [{"title": n['title'], "sentiment": "未連線", "link": n['link'], "date": n['date']} for n in top_news]

        news_text = "\n".join([f"新聞: {n['title']}" for n in top_news])
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "讀取新聞標題，嚴格回傳JSON陣列。每項包含: title(繁中), sentiment(利多/利空/中立)。"}, 
                {"role": "user", "content": news_text}
            ],
            "temperature": 0.3
        }
        res_ai = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}, json=payload, timeout=20)
        ai_text = res_ai.json()["choices"][0]["message"]["content"].strip()
        match = re.search(r'\[.*\]', ai_text, re.DOTALL)
        parsed_data = json.loads(match.group(0)) if match else []
        
        final_result = []
        for i, item in enumerate(parsed_data):
            if i < len(top_news): 
                final_result.append({"title": item.get("title", top_news[i]["title"]), "sentiment": item.get("sentiment", "中立"), "link": top_news[i]["link"], "date": top_news[i]["date"]})
        return final_result
    except:
        return [{"title": "新聞掃雷器故障", "sentiment": "未判定", "link": "#", "date": "未知"}]

def get_us_market_summary():
    symbols = {"SPY": "標普500", "SOXX": "費城半導體", "TSM": "台積電ADR", "^VIX": "恐慌指數"}
    summary = {}
    for sym, name in symbols.items():
        try:
            data = yf.download(sym, period="5d", progress=False)
            if len(data) >= 2:
                close_prices = data['Close'].iloc[-2:].values.flatten()
                summary[name] = {"price": round(close_prices[1], 2), "pct": round(((close_prices[1] - close_prices[0]) / close_prices[0]) * 100, 2)}
            else: summary[name] = {"price": 0, "pct": 0}
        except: summary[name] = {"price": 0, "pct": 0}
    return summary

def get_sector_rotation():
    sectors = {"XLK": {"name": "🇺🇸美股科技", "bm": "SPY"}, "XLF": {"name": "🇺🇸美股金融", "bm": "SPY"}, "00881.TW": {"name": "🇹🇼台股科技", "bm": "0050.TW"}, "00878.TW": {"name": "🇹🇼台股高息", "bm": "0050.TW"}}
    results = []
    for sym, info in sectors.items():
        try:
            stock_df, bm_df = yf.Ticker(sym).history(period="1mo"), yf.Ticker(info["bm"]).history(period="1mo")
            if len(stock_df) >= 20 and len(bm_df) >= 20:
                rs = (((stock_df['Close'].iloc[-1] - stock_df['Close'].iloc[-20]) / stock_df['Close'].iloc[-20]) - ((bm_df['Close'].iloc[-1] - bm_df['Close'].iloc[-20]) / bm_df['Close'].iloc[-20])) * 100
                results.append({"name": info["name"], "rs": round(rs, 2)})
        except: pass
    results.sort(key=lambda x: x['rs'], reverse=True)
    return results

def calculate_poc(df, days=120, bins=20):
    try:
        recent_df = df.tail(days).copy()
        if len(recent_df) < 20: return round(df['Close'].iloc[-1], 2)
        recent_df['Price_Bin'] = pd.cut(recent_df['Close'], bins=bins)
        poc_bin = recent_df.groupby('Price_Bin', observed=False)['Volume'].sum().idxmax()
        return round(float(poc_bin.mid), 2)
    except: return round(df['Close'].iloc[-1], 2)

def get_best_ma_strategy(df):
    best_ma, best_profit = 'ma20', -9999
    try:
        for ma in ['ma5', 'ma10', 'ma20', 'ma60']:
            if ma not in df.columns: continue
            test_df = df.tail(120).copy()
            in_position, entry_price, profit = False, 0, 0
            for i in range(1, len(test_df)):
                if not in_position and test_df['Close'].iloc[i-1] < test_df[ma].iloc[i-1] and test_df['Close'].iloc[i] > test_df[ma].iloc[i]:
                    in_position, entry_price = True, test_df['Close'].iloc[i]
                elif in_position and test_df['Close'].iloc[i-1] > test_df[ma].iloc[i-1] and test_df['Close'].iloc[i] < test_df[ma].iloc[i]:
                    in_position, profit = False, profit + (test_df['Close'].iloc[i] - entry_price) / entry_price
            if in_position and entry_price > 0: profit += (test_df['Close'].iloc[-1] - entry_price) / entry_price
            if profit > best_profit: best_profit, best_ma = profit, ma
        return best_ma.replace('ma', '') + 'MA' 
    except: return "20MA"

def get_smart_money_flow(symbol):
    fmp_key = os.environ.get("FMP_API_KEY")
    if symbol.endswith(".TW") or not fmp_key: return "無明顯大戶異常動向"
    try:
        res = requests.get(f"https://financialmodelingprep.com/api/v4/insider-trading?symbol={symbol}&limit=10&apikey={fmp_key}", timeout=5)
        if res.status_code != 200 or not res.json(): return "無明顯大戶異常動向"
        buy_amount, sell_amount = 0, 0
        for trade in res.json():
            val = trade.get('securitiesTransacted', 0) * trade.get('price', 0)
            if trade.get('acquistionOrDisposition') == 'A': buy_amount += val
            elif trade.get('acquistionOrDisposition') == 'D': sell_amount += val
        net_flow = buy_amount - sell_amount
        if net_flow > 1000000: return f"🔥【大戶狂買】高管淨買入 ${round(buy_amount/1000000, 2)}M 美金！"
        elif net_flow < -1000000: return f"🚨【高管倒貨】高管淨賣出 ${round(sell_amount/1000000, 2)}M 美金！"
        return "內部人近期無明顯大動作。"
    except: return "大戶動向偵測失敗"

# 🧠 尊貴核心：深度推理交給你課金的 o3-mini (還原文字詳解版)
def get_unified_brain_o3(stock_name, current_price, ma20, rsi, poc_price, rs_score, smart_money):
    print(f"🧠 [o3-mini 深度推理] 啟動戰情分析：{stock_name}...")
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key: return None

    system_prompt = """你是一位華爾街量化風控長。你需要綜合數據給出唯一裁決，用「白話文」撰寫。
    必須嚴格回傳 JSON 格式：
    {
        "pattern": "目前的狀態 (限10字)",
        "bull": "多方好消息 (白話文，限25字)",
        "bear": "空方壞消息 (白話文，限25字)",
        "trap": "騙線警告 (包含POC籌碼判斷，限30字)",
        "stop_price": 數字 (合理防守價, 精確到小數點後兩位),
        "sizing": "資金建議 (限20字)",
        "action": "最終指令 (限選一個：抱牢續賺 / 縮注試單 / 嚴格觀望 / 破線快逃)"
    }"""
    
    user_prompt = f"股票:{stock_name}, 現價:{current_price}, 20MA:{ma20}, RSI:{rsi}, POC成本:{poc_price}, 大戶動向:{smart_money}"
    
    try:
        res = requests.post(
            "https://api.openai.com/v1/chat/completions", 
            headers={"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"}, 
            json={"model": "o3-mini", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "response_format": {"type": "json_object"}}, 
            timeout=25
        )
        return json.loads(res.json()["choices"][0]["message"]["content"].strip())
    except Exception as e:
        print(f"o3-mini 錯誤: {e}")
        return {"pattern": "連線異常", "bull": "API中斷", "bear": "API中斷", "trap": "API中斷", "stop_price": round(current_price * 0.95, 2), "sizing": "防禦狀態", "action": "觀望"}

def generate_morning_script_groq(market_data, sector_data):
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key: return "⚠️ 未設定 GROQ_API_KEY。"
    data_str = ", ".join([f"{k}: 變化 {v['pct']}%" for k, v in market_data.items()])
    sector_str = ", ".join([f"{s['name']}(動能 {s['rs']}%)" for s in sector_data]) if sector_data else "無資料"
    
    try:
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions", 
            headers={"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}, 
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": "你是阿土伯。根據美股與資金流向給出80字內今日台股操作鐵律，必須包含資金曝險上限建議(如20%)。"}, {"role": "user", "content": f"美股:{data_str}。流向:{sector_str}。"}]}, 
            timeout=15
        )
        return res.json()["choices"][0]["message"]["content"].strip()
    except: return "🤖 戰情室連線異常，請縮小部位觀望。"

def generate_dashboard_data():
    bear_markets = check_market_regime() 
    try:
        with open("portfolio.json", "r", encoding="utf-8") as f: cloud_portfolio = json.load(f)
    except: cloud_portfolio = {}
    
    tw_idx, us_idx = yf.download("0050.TW", period="6mo", progress=False), yf.download("SPY", period="6mo", progress=False)
    if isinstance(tw_idx.columns, pd.MultiIndex): tw_idx.columns = tw_idx.columns.droplevel(1)
    if isinstance(us_idx.columns, pd.MultiIndex): us_idx.columns = us_idx.columns.droplevel(1)
    
    dashboard_data = []

    for symbol, info in STOCKS.items():
        print(f"處理中: {symbol}")
        try:
            df = yf.download(symbol, start="2021-01-01", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
                
            current_price = round(df['Close'].iloc[-1], 2)
            df['ma5'] = df['Close'].rolling(5).mean(); df['ma10'] = df['Close'].rolling(10).mean(); df['ma20'] = df['Close'].rolling(20).mean(); df['ma60'] = df['Close'].rolling(60).mean()
            best_ma_name = get_best_ma_strategy(df)
            best_ma_price = round(df['ma' + best_ma_name.replace('MA', '')].iloc[-1], 2) if not pd.isna(df['ma' + best_ma_name.replace('MA', '')].iloc[-1]) else round(df['ma20'].iloc[-1], 2)
            
            df['std'] = df['Close'].rolling(20).std()
            df['bb_upper'], df['bb_lower'] = df['ma20'] + 2 * df['std'], df['ma20'] - 2 * df['std']
            df['macd'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']
            delta = df['Close'].diff()
            df['rsi'] = 100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / -delta.where(delta < 0, 0).rolling(14).mean())))
            df['tr'] = df[['High', 'Low']].max(axis=1) - df[['High', 'Low']].min(axis=1)
            df['atr'] = df['tr'].rolling(14).mean()
            df['Signal'] = np.where(df['Close'] > df['ma20'], 1, np.where(df['Close'] < df['ma20'], -1, 0))
            df = df.fillna(0)
            
            try: rs_score = round((((df['Close'].iloc[-1] - df['Close'].iloc[-20]) / df['Close'].iloc[-20]) - ((tw_idx['Close'].iloc[-1] - tw_idx['Close'].iloc[-20]) / tw_idx['Close'].iloc[-20] if symbol.endswith(".TW") else (us_idx['Close'].iloc[-1] - us_idx['Close'].iloc[-20]) / us_idx['Close'].iloc[-20])) * 100, 2)
            except: rs_score = 0
            
            best_sl = 0.05
            for sl in [0.03, 0.05, 0.08, 0.10]:
                res = calculate_ev_from_df(df, sl)
                if res and res['ev'] > -999: best_sl = sl
                    
            actual_sl = 0.03 if (bear_markets["TW"] if symbol.endswith(".TW") else bear_markets["US"]) else best_sl
            
            smart_money = get_smart_money_flow(symbol)
            poc_price = calculate_poc(df, days=120, bins=20)
            
            unified_brain = get_unified_brain_o3(info["name"], current_price, round(df['ma20'].iloc[-1], 2), round(df['rsi'].iloc[-1], 2), poc_price, rs_score, smart_money)

            avg_vol_20 = df['Volume'].rolling(20).mean().iloc[-1]
            real_vol_ratio = round(float(df['Volume'].iloc[-1] / avg_vol_20), 2) if avg_vol_20 > 0 else 1.0
            
            hist = [{"date": i.strftime("%Y-%m-%d"), "price": round(r['Close'], 2), "volume": int(r['Volume']), "ma5": round(r['ma5'], 2), "ma20": round(r['ma20'], 2), "ma60": round(r['ma60'], 2), "macd": round(r['macd'], 2), "macd_signal": round(r['macd_signal'], 2), "macd_hist": round(r['macd_hist'], 2), "rsi": round(r['rsi'], 2), "bb_upper": round(r['bb_upper'], 2), "bb_lower": round(r['bb_lower'], 2)} for i, r in df.tail(60).iterrows()]

            dashboard_data.append({
                "symbol": symbol, "name": info["name"], "category": info["category"],
                "price": current_price, "rsi": round(df['rsi'].iloc[-1], 2), 
                "poc_price": poc_price, "vol_ratio": real_vol_ratio, "actual_sl": int(actual_sl*100),
                "history": hist, "rs_score": rs_score,
                "unified_brain": unified_brain, 
                "smart_money": smart_money,
                "best_ma_name": best_ma_name, "best_ma_price": best_ma_price
            })

        except Exception as e:
            print(f"⚠️ 處理 {symbol} 失敗: {e}")
        
        # 🚨 阿土伯的「保命符」：強制休息 15 秒，保證你的 Tier 1 帳號絕對不會被鎖！
        print("⏳ 運算完畢，為了保護你的 o3-mini 額度，系統強制冷卻 15 秒...")
        time.sleep(15)

    us_market_data = get_us_market_summary()
    sector_data = get_sector_rotation()
    morning_script = generate_morning_script_groq(us_market_data, sector_data)
    health_pct = int((sum(1 for d in dashboard_data if d['price'] > d['history'][-1]['ma20']) / len(dashboard_data)) * 100) if dashboard_data else 50

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({"last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"), "data": dashboard_data, "market_health": {"vix": us_market_data.get("恐慌指數", {}).get("price", 0) if isinstance(us_market_data, dict) else 0, "health_pct": health_pct, "us_summary": us_market_data, "sector_data": sector_data, "ai_script": morning_script}}, f, ensure_ascii=False, indent=4)

if __name__ == "__main__": 
    generate_dashboard_data()
