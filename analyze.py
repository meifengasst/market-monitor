import yfinance as yf
import json
import pandas as pd
import os
from datetime import datetime

# 產業與市場分類
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

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss)))

def analyze():
    history_file = 'chip_history.csv'
    stock_data = []
    
    if os.path.exists(history_file):
        history_df = pd.read_csv(history_file)
    else:
        history_df = pd.DataFrame(columns=['date', 'symbol', 'price', 'volume'])

    today_str = datetime.now().strftime("%Y-%m-%d")

    for symbol, name in STOCKS.items():
        try:
            # 抓取 80 天以計算 MA60 與 RSI
            df = yf.Ticker(symbol).history(period="80d")
            if df.empty: continue
            
            close = df['Close']
            price = round(close.iloc[-1], 2)
            
            # 技術指標 (舊技能)
            ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
            rsi = round(calculate_rsi(close).iloc[-1], 1)
            cat = [k for k, v in CATEGORIES.items() if symbol in v]

            # 籌碼指標 (新技能)
            vol = df['Volume'].iloc[-1]
            avg_vol = df['Volume'].rolling(5).mean().iloc[-1] # 精準計算5日均量
            vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 1

            new_row = {'date': today_str, 'symbol': symbol, 'price': price, 'volume': vol}
            history_df = pd.concat([history_df, pd.DataFrame([new_row])], ignore_index=True)

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
                "status": "現在超火熱" if rsi > 70 else ("撿便宜時機" if rsi < 30 else "平穩行駛中"),
                "vol_ratio": vol_ratio,
                "chip_signal": "🔥 大戶進場" if vol_ratio > 1.5 else "💤 散戶盤整"
            })
        except Exception as e:
            print(f"跳過 {symbol}: {e}")

    history_df.tail(1500).to_csv(history_file, index=False)
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": today_str, "data": stock_data}, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    analyze()
