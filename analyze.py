import yfinance as yf
import json
from datetime import datetime

# 1. 這裡加入你想搜尋的股票，記得 9802 要加 .TW
STOCKS = {
    "2912.TW": "統一超",
    "2891.TW": "中信金",
    "9802.TW": "鈺齊-KY",
    "2330.TW": "台積電"
}

def analyze():
    stock_data = []
    # 抓取真實數據
    for symbol, name in STOCKS.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            current_price = round(hist['Close'].iloc[-1], 2)
            ma5 = hist['Close'].mean()
            
            stock_data.append({
                "symbol": symbol,
                "name": name,
                "price": current_price,
                "trend": "多頭" if current_price >= ma5 else "空頭",
                "signal": "趨勢穩定" if current_price >= ma5 else "建議觀望"
            })
        except:
            print(f"無法抓取 {symbol}")

    # 2. 這是網頁需要的正確 JSON 格式
    output = {
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data": stock_data  # 注意這裡是一個清單
    }

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    analyze()
import yfinance as yf
import json
import pandas as pd
from datetime import datetime

# 產業與市場分類
CATEGORIES = {
    "美國科技": ["NVDA", "TSLA"],
    "美股大盤": ["SPY"],
    "台股龍頭": ["0050.TW", "2330.TW"],
    "晶圓代工": ["2330.TW", "2303.TW"],
    "運動鞋": ["9802.TW", "9910.TW", "9904.TW"]
}

# 監控總清單 (你可以隨時增加代號)
STOCKS = {
    "NVDA": "Nvidia (AI之王)",
    "TSLA": "Tesla (電動車)",
    "SPY": "S&P 500 ETF",
    "0050.TW": "元大台灣50",
    "2330.TW": "台積電",
    "2303.TW": "聯電",
    "9802.TW": "鈺齊-KY",
    "9910.TW": "豐泰",
    "9904.TW": "寶成"
}

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss)))

def analyze():
    stock_data = []
    for symbol, name in STOCKS.items():
        try:
            df = yf.Ticker(symbol).history(period="80d")
            if df.empty: continue
            
            close = df['Close']
            price = round(close.iloc[-1], 2)
            ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
            rsi = round(calculate_rsi(close).iloc[-1], 1)
            cat = [k for k, v in CATEGORIES.items() if symbol in v]

            stock_data.append({
                "symbol": symbol,
                "name": name,
                "category": cat[0] if cat else "其他",
                "price": price,
                "rsi": rsi,
                "lights": {
                    "short": "🔴" if price > ma5 else "⚪", 
                    "mid": "🟡" if price > ma20 else "⚪",  
                    "long": "🟢" if price > ma60 else "⚪"  
                },
                "status": "現在超火熱" if rsi > 70 else ("撿便宜時機" if rsi < 30 else "平穩行駛中")
            })
        except: print(f"跳過 {symbol}")

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": datetime.now().strftime("%Y-%m-%d %H:%M"), "data": stock_data}, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    analyze()
