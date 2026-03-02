import yfinance as yf
import json
from datetime import datetime

# 定義你想監控的股票 (台股請加 .TW)
# 2330.TW (台積電), 2912.TW (統一超), 2891.TW (中信金)
STOCKS = {
    "2912.TW": "統一超 (WBC消費帶動)",
    "2891.TW": "中信金 (WBC主要贊助)",
    "TSLA": "Tesla (國際情緒參考)"
}

def analyze_market():
    results = []
    print(f"--- 啟動數據分析: {datetime.now()} ---")

    for symbol, description in STOCKS.items():
        try:
            # 抓取過去 20 天的歷史數據計算均線
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="20d")
            
            if df.empty:
                continue

            current_price = df['Close'].iloc[-1]
            ma5 = df['Close'].rolling(window=5).mean().iloc[-1] # 5日線 (短線趨勢)
            
            # 判斷多空：股價在均線上則偏多，反之偏空
            trend = "多頭" if current_price > ma5 else "空頭"
            
            results.append({
                "symbol": symbol,
                "name": description,
                "price": round(current_price, 2),
                "trend": trend,
                "signal": "建議觀望" if trend == "空頭" else "趨勢穩定"
            })
            print(f"成功抓取 {symbol}: {current_price}")
            
        except Exception as e:
            print(f"抓取 {symbol} 失敗: {e}")

    # 存檔
    output = {
        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data": results
    }
    
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    analyze_market()
