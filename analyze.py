import yfinance as yf
import json
import pandas as pd
import os
import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime

# 1. 鑰匙與配置
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")
LINE_TARGET_ID = os.environ.get("LINE_TARGET_ID")

CATEGORIES = {
    "美國科技": ["NVDA", "TSLA"],
    "美股大盤": ["SPY"],
    "台股龍頭": ["0050.TW", "2330.TW"],
    "晶圓代工": ["2330.TW", "2303.TW"],
    "運動鞋": ["9802.TW", "9910.TW", "9904.TW"]
}

STOCKS = {
    "NVDA": "Nvidia (AI之王)", "TSLA": "Tesla (電動車)", "SPY": "S&P 500 ETF",
    "0050.TW": "元大台灣50", "2330.TW": "台積電", "2303.TW": "聯電",
    "9802.TW": "鈺齊-KY", "9910.TW": "豐泰", "9904.TW": "寶成"
}

# 2. 📡 攔截 Google 全球財經新聞
def get_google_news(is_taiwan=True):
    url = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-Hant" if is_taiwan else "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en"
    try:
        res = requests.get(url, timeout=10)
        root = ET.fromstring(res.text)
        return [item.find('title').text for item in root.findall('.//item')[:5]]
    except: return ["暫無新聞"]

# 3. 🤖 AI 總經大腦
def get_macro_ai_prediction(news_list, region):
    API_KEY = os.environ.get('GEMINI_API_KEY') 
    if not API_KEY: return "🤖 找不到鑰匙"
    prompt = f"你是華爾街頂級總經分析師阿土伯。請根據以下{region}最新財經新聞標題，用繁體中文寫「50字以內」的『盤前總經與趨勢速報』：\n" + "\n".join(news_list)
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.4}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=15)
        if res.status_code == 200: return res.json()['choices'][0]['message']['content'].strip()
        else: return "🤖 總經訊號微弱，無法解讀。"
    except: return "🤖 網路連線逾時..."

# 4. 🤖 AI 個股大腦
def get_ai_prediction(stock_name, price, bias, pe_ratio, eps, news_list):
    API_KEY = os.environ.get('GEMINI_API_KEY') 
    if not API_KEY: return "🤖 找不到鑰匙"
    headlines = [n.get('title', '') for n in news_list[:5]] if news_list else ["無最新重大新聞"]
    prompt = f"你是資深股市觀察家阿土伯。標的【{stock_name}】，現價{price}，乖離率{bias}%，本益比{pe_ratio}，EPS為{eps}。請綜合基本面、技術面與新聞，寫「40字以內」的客觀趨勢點評：\n" + "\n".join(headlines)
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    data = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.5}
    try:
        res = requests.post(url, headers=headers, json=data, timeout=10)
        if res.status_code == 200: return res.json()['choices'][0]['message']['content'].strip()
        else: return "🤖 API 錯誤"
    except: return "🤖 網路逾時"

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss + 1e-9)))

def send_line_message(msg):
    if not LINE_ACCESS_TOKEN or not LINE_TARGET_ID: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    data = {"to": LINE_TARGET_ID, "messages": [{"type": "text", "text": msg}]}
    try: requests.post(url, headers=headers, json=data)
    except Exception as e: print(f"❌ LINE 推播失敗: {e}")

def analyze():
    stock_data = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    print("🌍 正在分析全球與國內總經新聞...")
    macro_info = {
        "tw_insight": get_macro_ai_prediction(get_google_news(is_taiwan=True), "台灣"),
        "us_insight": get_macro_ai_prediction(get_google_news(is_taiwan=False), "美國及全球")
    }

    for symbol, name in STOCKS.items():
        try:
            ticker = yf.Ticker(symbol)
            # 增加抓取天數到 100 天，確保 MACD 計算精準
            df = ticker.history(period="100d")
            if df.empty: continue
            
            close = df['Close']
            price = round(close.iloc[-1], 2)
            
            info = ticker.info
            pe_ratio = round(info.get('trailingPE', 0), 1) if isinstance(info.get('trailingPE'), (int, float)) else 'N/A'
            eps = info.get('trailingEps', 'N/A')
            
            # 📈 基礎技術指標
            df['MA5'] = close.rolling(5).mean()
            df['MA20'] = close.rolling(20).mean()
            df['MA60'] = close.rolling(60).mean()
            df['RSI'] = calculate_rsi(close)
            
            # 🛡️ 布林通道 (Bollinger Bands)
            df['STD20'] = close.rolling(20).std()
            df['BB_UPPER'] = df['MA20'] + (df['STD20'] * 2)
            df['BB_LOWER'] = df['MA20'] - (df['STD20'] * 2)
            
            # ⚔️ MACD 動能指標
            exp1 = close.ewm(span=12, adjust=False).mean()
            exp2 = close.ewm(span=26, adjust=False).mean()
            df['MACD'] = exp1 - exp2
            df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
            df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']
            
            ma5, ma20, ma60 = df['MA5'].iloc[-1], df['MA20'].iloc[-1], df['MA60'].iloc[-1]
            bias = round(((price - ma20) / ma20) * 100, 2)
            risk_level = "😱 極高" if bias > 10 else ("📉 超跌" if bias < -10 else "🧐 正常")
            rsi = round(df['RSI'].iloc[-1], 1)
            vol_ratio = round(df['Volume'].iloc[-1] / df['Volume'].rolling(5).mean().iloc[-1], 2)
            cat_name = [k for k, v in CATEGORIES.items() if symbol in v][0] if any(symbol in v for v in CATEGORIES.values()) else "其他"
            
            ai_text = get_ai_prediction(name, price, bias, pe_ratio, eps, ticker.news)
            
            # 🎨 將最新的 30 天包含布林通道與 MACD 的資料包裝給前端
            chart_history = []
            for date, row in df.tail(30).iterrows():
                chart_history.append({
                    "date": date.strftime("%m-%d"), "price": round(row['Close'], 2), "volume": int(row['Volume']),
                    "ma5": round(row['MA5'], 2) if pd.notna(row['MA5']) else None,
                    "ma20": round(row['MA20'], 2) if pd.notna(row['MA20']) else None,
                    "ma60": round(row['MA60'], 2) if pd.notna(row['MA60']) else None,
                    "rsi": round(row['RSI'], 1) if pd.notna(row['RSI']) else None,
                    "bb_upper": round(row['BB_UPPER'], 2) if pd.notna(row['BB_UPPER']) else None,
                    "bb_lower": round(row['BB_LOWER'], 2) if pd.notna(row['BB_LOWER']) else None,
                    "macd": round(row['MACD'], 2) if pd.notna(row['MACD']) else None,
                    "macd_signal": round(row['MACD_SIGNAL'], 2) if pd.notna(row['MACD_SIGNAL']) else None,
                    "macd_hist": round(row['MACD_HIST'], 2) if pd.notna(row['MACD_HIST']) else None
                })
            
            stock_data.append({
                "symbol": symbol, "name": name, "category": cat_name, "price": price, "rsi": rsi,
                "bias": bias, "risk_level": risk_level, "vol_ratio": vol_ratio, 
                "pe_ratio": pe_ratio, "eps": eps, "ai_summary": ai_text,
                "lights": {"short": "🔴" if price > ma5 else "⚪", "mid": "🟡" if price > ma20 else "⚪", "long": "🟢" if price > ma60 else "⚪"},
                "history": chart_history
            })
            time.sleep(1)
            print(f"✅ 完成 {name} 分析 (加入 BB & MACD)")
        except Exception as e: print(f"❌ 錯誤 {symbol}: {e}")

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": today_str, "macro": macro_info, "data": stock_data}, f, ensure_ascii=False, indent=4)
    
    bull_stocks = [s['name'] for s in stock_data if s['lights']['short'] != '⚪']
    msg = f"\n老闆早！阿土伯戰情室 {today_str} 報告：\n----------------------\n🌍 【國際大盤】\n{macro_info['us_insight']}\n\n🇹🇼 【國內台股】\n{macro_info['tw_insight']}\n----------------------\n🚀 準備起飛：{', '.join(bull_stocks) if bull_stocks else '無'}\n🔗 點擊看詳細戰情：\nhttps://meifengstore.com/market-monitor/\n"
    send_line_message(msg)

if __name__ == "__main__":
    analyze()
