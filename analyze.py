import yfinance as yf
import json
import pandas as pd
import os
import requests
import time
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

# 2. AI 讀報：直球 REST API 版 (解決 404 問題)
def get_ai_summary(stock_name, news_list):
    if not GEMINI_API_KEY or not news_list: return "目前市場靜悄悄，無最新新聞。"
    headlines = [n.get('title', '') for n in news_list[:5]]
    prompt = f"你是台股資深股神阿土伯。標的【{stock_name}】，現價{price}，乖離率{bias}%。請根據這些數據與以下新聞，給出一句25字內的『操作建議』（如：分批獲利、等待拉回或空手觀望）：\n" + "\n".join(headlines)
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10)
        return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except: return "🤖 阿土伯讀報中，暫無評論。"

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss + 1e-9)))

def analyze():
    # 計算 20MA 乖離率 (Bias)
            ma20_val = close.rolling(20).mean().iloc[-1]
            bias = round(((price - ma20_val) / ma20_val) * 100, 2)
            
            # 定義風險等級
            risk_level = "😱 極高 (過熱)" if bias > 10 else ("🧐 正常" if bias > -5 else "📉 超跌 (撿便宜)")
    
    history_file = 'chip_history.csv'
    stock_data = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 讀取/初始化歷史庫
    hist_df = pd.read_csv(history_file) if os.path.exists(history_file) else pd.DataFrame(columns=['date','symbol','price','volume'])

    for symbol, name in STOCKS.items():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="80d")
            if df.empty: continue
            
            close = df['Close']
            price = round(close.iloc[-1], 2)
            ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
            rsi = round(calculate_rsi(close).iloc[-1], 1)
            vol_ratio = round(df['Volume'].iloc[-1] / df['Volume'].rolling(5).mean().iloc[-1], 2)
            
            cat_name = [k for k, v in CATEGORIES.items() if symbol in v][0] if any(symbol in v for v in CATEGORIES.values()) else "其他"
            
            # 存入歷史並取得 AI 評論
            hist_df = pd.concat([hist_df, pd.DataFrame([{'date': today_str, 'symbol': symbol, 'price': price, 'volume': df['Volume'].iloc[-1]}])], ignore_index=True)
            ai_text = get_ai_summary(name, ticker.news)
            
            stock_data.append({
                "symbol": symbol, "name": name, "category": cat_name, "price": price, "rsi": rsi,
                "vol_ratio": vol_ratio, "ai_summary": ai_text,
                "lights": {"short": "🔴" if price > ma5 else "⚪", "mid": "🟡" if price > ma20 else "⚪", "long": "🟢" if price > ma60 else "⚪"},
                "history": hist_df[hist_df['symbol'] == symbol].tail(30).to_dict('records')
            })
            time.sleep(1) # 避開頻率限制
        except Exception as e: print(f"Error {symbol}: {e}")

    # 3. 核心升級：計算產業統計數據
    cat_stats = []
    for cat, members in CATEGORIES.items():
        relevant = [s for s in stock_data if s['symbol'] in members]
        if relevant:
            avg_rsi = sum(s['rsi'] for s in relevant) / len(relevant)
            avg_vol = sum(s['vol_ratio'] for s in relevant) / len(relevant)
            cat_stats.append({"category": cat, "avg_rsi": round(avg_rsi, 1), "avg_vol": round(avg_vol, 2)})

    # 儲存與 LINE 推播 (略，保持你原本的邏輯即可)
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": today_str, "data": stock_data, "cat_stats": cat_stats}, f, ensure_ascii=False, indent=4)
    hist_df.tail(2000).to_csv(history_file, index=False)
    
    # LINE 推播訊息構造... (呼叫 send_line_message)

if __name__ == "__main__":
    analyze()

