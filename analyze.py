import yfinance as yf
import pandas as pd
import json
from datetime import datetime
import numpy as np
import os
import requests
import time
import feedparser
import urllib.parse
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

def calculate_atr_stop_loss(df, period=14, multiplier=1.5):
    """阿土伯的 ATR 動態停損計算機"""
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(window=period).mean()
    return df

def calculate_ev_from_df(df, atr_period=14, atr_multiplier=1.5):
    """阿土伯的 ATR 動態期望值與勝率回測系統"""
    trades, entry_price, in_position, peak_price = [], 0, False, 0 
    for index, row in df.iterrows():
        if pd.isna(row.get('ATR', np.nan)): continue
        if in_position:
            peak_price = max(peak_price, row['High'])
            trailing_stop = peak_price - (row['ATR'] * atr_multiplier)
            if row['Low'] <= trailing_stop:
                actual_exit_price = min(row['Open'], trailing_stop)
                trades.append((actual_exit_price - entry_price) / entry_price)
                in_position = False
            elif row.get('Signal', 0) == -1:
                trades.append((row['Close'] - entry_price) / entry_price)
                in_position = False
        elif not in_position and row.get('Signal', 0) == 1:
            entry_price, in_position, peak_price = row['Close'], True, row['Close']

    if not trades: return {"ev": 0.0, "win_rate": 0.0, "trades_count": 0}
    ts = pd.Series(trades)
    win_ts, loss_ts = ts[ts > 0], ts[ts <= 0]
    p_win = len(win_ts) / len(ts) if len(ts) > 0 else 0
    avg_win = win_ts.mean() if not win_ts.empty else 0
    avg_loss = abs(loss_ts.mean()) if not loss_ts.empty else 0
    ev = (p_win * avg_win) - ((1 - p_win) * avg_loss)
    return {"ev": round(ev * 100, 2), "win_rate": round(p_win * 100, 2), "trades_count": len(ts)}

def check_market_regime():
    regime = {"TW": False, "US": False} 
    alert_msg = "⚠️【阿土伯雙引擎戰報】\n大盤跌破月線防禦區！\n\n"
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
    "0050.TW": {"name": "台灣50", "category": "台股龍頭"}, "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"}, "9910.TW": {"name": "豐泰", "category": "運動鞋"}, 
    "9904.TW": {"name": "寶成", "category": "運動鞋"}
}

def get_us_market_summary():
    symbols = {"SPY": "標普500", "SOXX": "費城半導體", "TSM": "台積電ADR", "^VIX": "恐慌指數"}
    summary = {}
    print("🌍 阿土伯正在收集昨夜美股戰報...")
    for sym, name in symbols.items():
        try:
            data = yf.download(sym, period="5d", progress=False)
            if len(data) >= 2:
                close_prices = data['Close'].iloc[-2:].values.flatten()
                prev_close, last_close = close_prices[0], close_prices[1]
                pct_change = ((last_close - prev_close) / prev_close) * 100
                summary[name] = {"price": round(last_close, 2), "pct": round(pct_change, 2)}
            else: summary[name] = {"price": 0, "pct": 0}
        except: summary[name] = {"price": 0, "pct": 0}
    return summary

def generate_morning_script_via_groq(market_data):
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key: return "⚠️ 未設定 GROQ_API_KEY，請手動依據 20MA 鐵律操作。"
    data_str = ", ".join([f"{k}: 變化 {v['pct']}% (收 {v['price']})" for k, v in market_data.items()])
    system_prompt = "你現在是台灣股市老手「阿土伯」，極度重視風險控制。語氣要果斷、嚴厲。請根據提供的【昨夜美股數據】，給出【今日台股開盤的行動指南】。包含資金曝險上限。字數嚴格限制 80 字內。"
    user_prompt = f"昨夜美股數據：{data_str}。請給指令！"
    try:
        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.1-8b-instant", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.3}
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e: return f"🤖 AI 連線異常: {e}"

def get_robust_news(stock_name, limit=3):
    print(f"🕵️ 正在搜索 {stock_name} 的最新情報...")
    query = urllib.parse.quote(f"{stock_name} stock")
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        feed = feedparser.parse(url)
        news_list = []
        for entry in feed.entries[:limit]:
            news_list.append({"title": entry.title, "link": entry.link})
        return news_list
    except: return []

def get_ai_news_sentiment(symbol, stock_name):
    news_list = get_robust_news(stock_name, limit=3)
    if not news_list: return []
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key: return [{"title": n["title"], "link": n["link"], "sentiment": "中立 ⚪"} for n in news_list]

    titles_text = "\n".join([f"新聞 {i+1}：{n['title']}" for i, n in enumerate(news_list)])
    system_prompt = "你是一位台灣股市操盤手。判斷以下新聞標題對股價是「利多」、「利空」或「中立」。嚴格以純 JSON 陣列格式回傳，不要 markdown。範例：[{\"sentiment\": \"利多 🔴\", \"title\": \"標題\"}]"
    user_prompt = f"股票：{stock_name}\n新聞：\n{titles_text}"

    try:
        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.1-8b-instant", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.1}
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15)
        ai_text = res.json()["choices"][0]["message"]["content"].strip()
        if ai_text.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1

這次直接全選貼上，存檔推到 GitHub，然後按「強制更新」，絕對萬無一失！快去試試看！
