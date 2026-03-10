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

def get_robust_news(stock_name, limit=3):
    """
    阿土伯的精準情報網：Google News RSS 爬蟲
    """
    print(f"🕵️ 正在啟動深度爬蟲，搜索 {stock_name} 的最新情報...")
    
    # 將股票名稱編碼，加入 "stock" 關鍵字過濾雜訊
    query = urllib.parse.quote(f"{stock_name} stock")
    # 使用 Google News RSS 接口 (這裡設定抓取台灣繁體中文新聞，也可改為純英文)
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    
    try:
        feed = feedparser.parse(url)
        news_list = []
        
        for entry in feed.entries[:limit]:
            news_list.append({
                "title": entry.title,
                "link": entry.link,
                "published": entry.published # 可以順便抓取發布時間
            })
            
        if not news_list:
            print(f"⚠️ 找不到 {stock_name} 的近期新聞，可能是關鍵字太偏門。")
            
        return news_list
        
    except Exception as e:
        print(f"💥 爬蟲連線異常: {e}")
        return []

def calculate_atr_stop_loss(df, period=14, multiplier=1.5):
    """
    阿土伯的 ATR 動態停損計算機
    :param df: 包含 High, Low, Close 的 yfinance DataFrame
    :param period: ATR 計算週期 (通常用 14 天)
    :param multiplier: 停損寬容度 (通常設 1.5 到 2 倍 ATR)
    """
    # 計算 True Range (TR)
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    
    # 計算 ATR (簡單移動平均)
    atr = true_range.rolling(window=period).mean()
    df['ATR'] = atr
    
    # 計算動態停損點 (以收盤價往下扣除 N 倍 ATR)
    df['Dynamic_Stop_Loss'] = df['Close'] - (atr * multiplier)
    
    return df

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
    trades, entry_price, in_position = [], 0, False
    peak_price = 0 
    
    for index, row in df.iterrows():
        if in_position:
            peak_price = max(peak_price, row['High'])
            fixed_stop = entry_price * (1 - stop_loss_pct)
            trailing_stop = peak_price * (1 - stop_loss_pct)
            actual_exit_price = max(fixed_stop, trailing_stop)

            if row['Low'] <= actual_exit_price:
                trades.append((actual_exit_price - entry_price) / entry_price)
                in_position = False
            elif row['Signal'] == -1:
                trades.append((row['Close'] - entry_price) / entry_price)
                in_position = False
        elif not in_position and row['Signal'] == 1:
            entry_price, in_position = row['Close'], True
            peak_price = row['Close']

    if not trades: return None
    ts = pd.Series(trades)
    win_ts, loss_ts = ts[ts > 0], ts[ts <= 0]
    p_win = len(win_ts) / len(ts) if len(ts) > 0 else 0
    ev = (p_win * (win_ts.mean() if not win_ts.empty else 0)) - ((len(loss_ts) / len(ts) if len(ts) > 0 else 0) * (abs(loss_ts.mean()) if not loss_ts.empty else 0))
    return {"ev": round(ev * 100, 2), "win_rate": round(p_win * 100, 2)}

def check_market_regime():
    regime = {"TW": False, "US": False} 
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
    "2330.TW": {"name": "台積電", "category": "晶圓代工"}, "2337.TW": {"name": "旺宏", "category": "記憶體"},"3105.TWO": {"name": "穩懋", "category": "半導體"},
    "0050.TW": {"name": "台灣50", "category": "台股龍頭"}, "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"}
}

def get_us_market_summary():
    symbols = {"SPY": "標普500", "SOXX": "費城半導體", "TSM": "台積電ADR", "^VIX": "恐慌指數"}
    summary = {}
    print("🌍 阿土伯正在收集昨夜美股戰報...")
    for sym, name in symbols.items():
        try:
            data = yf.download(sym, period="5d", progress=False)
            if data.empty: continue
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.droplevel(1)
            close_prices = data['Close'].values.flatten()
            if len(close_prices) >= 2:
                prev_close, last_close = close_prices[-2], close_prices[-1]
                pct_change = ((last_close - prev_close) / prev_close) * 100
                summary[name] = {"price": round(last_close, 2), "pct": round(pct_change, 2)}
        except Exception as e:
            print(f"⚠️ 抓取 {name} 失敗: {e}")
    return summary

def generate_morning_script_via_groq(market_data):
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key: return "⚠️ 未設定 GROQ_API_KEY，無法產生晨間劇本。"
    data_str = ", ".join([f"{k}: 變化 {v['pct']}% (收 {v['price']})" for k, v in market_data.items()])
    system_prompt = "你現在是台灣股市老手「阿土伯」，極度重視風險控制。請根據提供的【昨夜美股數據】，給出【今日台股開盤的行動指南】。字數嚴格限制在 80 字以內，語氣要嚴厲。"
    user_prompt = f"昨夜美股數據：{data_str}。請阿土伯下達今日台股操作鐵律！"
    try:
        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.1-8b-instant", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.3}
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"].strip()
    except: return "🤖 AI 戰情室連線異常，請手動依據 20MA 鐵律操作。"

# 💡 AI 功能 1：新聞掃雷
# 💡 AI 功能 1：新聞掃雷 (阿土伯升級版)
def get_ai_news_sentiment(symbol, stock_name):
    print(f"📰 正在掃描 {stock_name} 的新聞籌碼...")
    
    # 👉 這裡才是重點！呼叫我們自己寫的 Google News 爬蟲，拋棄 yfinance
    news_list = get_robust_news(stock_name, limit=3)
    
    # 如果真的沒抓到新聞，直接回傳空陣列
    if not news_list: 
        return []

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key: 
        return [{"title": n["title"], "link": n["link"], "sentiment": "中立 ⚪"} for n in news_list]

    titles_text = "\n".join([f"新聞 {i+1}：{n['title']}" for i, n in enumerate(news_list)])
    system_prompt = """你是一位台灣股市操盤手。請判斷以下新聞標題對該公司股價是「利多」、「利空」還是「中立」。
    請嚴格以純 JSON 陣列格式回傳，不要 Markdown 標記！範例：[{"sentiment": "利多 🔴", "title": "標題1"}]"""
    user_prompt = f"股票：{stock_name}\n新聞列表：\n{titles_text}"

    try:
        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.1-8b-instant", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "temperature": 0.1}
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=15)
        
        ai_text = res.json()["choices"][0]["message"]["content"].strip()
        
        # 👉 幫你把剛剛斷掉的尾巴補上：防呆機制，清除 Groq 可能生成的 ```json 標籤
        if ai_text.startswith("```json"):
            ai_text = ai_text[7:-3].strip()
        elif ai_text.startswith("```"):
            ai_text = ai_text[3:-3].strip()
            
        return json.loads(ai_text)
        
    except Exception as e:
        print(f"⚠️ AI 解讀失敗: {e}")
        # AI 壞掉時的保底機制
        return [{"title": n["title"], "link": n["link"], "sentiment": "中立 ⚪"} for n in news_list]


