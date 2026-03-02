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

# 定義產業鏈對照表
CATEGORIES = {
    "運動鞋": ["9802.TW", "9910.TW", "9904.TW"], # 鈺齊, 豐泰, 寶成
    "晶圓代工": ["2330.TW", "2303.TW"],        # 台積電, 聯電
    "超商通路": ["2912.TW", "5903.TW"]         # 統一超, 全家
}

# 需要抓取的清單 (從分類中整合)
STOCKS = {
    "9802.TW": "鈺齊-KY", "9910.TW": "豐泰", "9904.TW": "寶成",
    "2330.TW": "台積電", "2303.TW": "聯電",
    "2912.TW": "統一超", "5903.TW": "全家"
}

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def analyze():
    stock_data = []
    for symbol, name in STOCKS.items():
        try:
            ticker = yf.Ticker(symbol)
            # 抓取 80 天數據確保夠算 MA60
            df = ticker.history(period="80d")
            if df.empty: continue

            price = round(df['Close'].iloc[-1], 2)
            ma5 = df['Close'].rolling(5).mean().iloc[-1]
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            ma60 = df['Close'].rolling(60).mean().iloc[-1]
            rsi = round(calculate_rsi(df['Close']).iloc[-1], 1)

            # 找出屬於哪個產業
            category = [k for k, v in CATEGORIES.items() if symbol in v]
            
            stock_data.append({
                "symbol": symbol,
                "name": name,
                "category": category[0] if category else "其他",
                "price": price,
                "rsi": rsi,
                "lights": {
                    "short": "🔴" if price > ma5 else "⚪",   # 起步加速
                    "mid": "🟡" if price > ma20 else "⚪",    # 路況順暢
                    "long": "🟢" if price > ma60 else "⚪"    # 地基穩固
                },
                "status": "現在很火熱" if rsi > 70 else ("撿便宜時機" if rsi < 30 else "平穩行駛中")
            })
        except Exception as e:
            print(f"錯誤 {symbol}: {e}")

    output = {"last_update": datetime.now().strftime("%Y-%m-%d %H:%M"), "data": stock_data}
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    analyze()
