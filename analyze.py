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
