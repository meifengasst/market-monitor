import yfinance as yf
import json
import pandas as pd
import os
from datetime import datetime

STOCKS = {
    "2330.TW": "台積電", "2891.TW": "中信金", "9802.TW": "鈺齊-KY",
    "NVDA": "輝達", "TSLA": "特斯拉", "0050.TW": "元大台灣50"
}

def analyze():
    history_file = 'chip_history.csv'
    stock_data = []
    
    # 讀取現有的歷史資料庫，如果沒有就建立新的
    if os.path.exists(history_file):
        history_df = pd.read_csv(history_file)
    else:
        history_df = pd.DataFrame(columns=['date', 'symbol', 'price', 'volume'])

    today_str = datetime.now().strftime("%Y-%m-%d")

    for symbol, name in STOCKS.items():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="5d")
            if df.empty: continue
            
            price = round(df['Close'].iloc[-1], 2)
            vol = df['Volume'].iloc[-1]
            
            # 【自研邏輯】：計算量能激增比 (今日成交量 / 5日平均量)
            avg_vol = df['Volume'].mean()
            vol_ratio = round(vol / avg_vol, 2)
            
            # 建立今日數據列
            new_row = {'date': today_str, 'symbol': symbol, 'price': price, 'volume': vol}
            stock_data.append({
                "symbol": symbol,
                "name": name,
                "price": price,
                "vol_ratio": vol_ratio,
                "chip_signal": "🔥 大戶進場" if vol_ratio > 1.5 else "💤 散戶盤整",
                "status": f"量能倍數: {vol_ratio}x"
            })
            
            # 追加到歷史 CSV (這就是你的私有資料庫)
            history_df = pd.concat([history_df, pd.DataFrame([new_row])], ignore_index=True)
            
        except Exception as e:
            print(f"抓取 {symbol} 失敗: {e}")

    # 只保留最近 1000 筆紀錄，避免檔案太大
    history_df.tail(1000).to_csv(history_file, index=False)

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": today_str, "data": stock_data}, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    analyze()
