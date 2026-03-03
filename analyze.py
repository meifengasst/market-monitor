import yfinance as yf
import json
import pandas as pd
import os
import requests  # <--- 新增這行，用來發送網路請求
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

POSITIVE_WORDS = ["漲", "看好", "利多", "營收增", "突破", "創新高", "買進", "升評", "成長", "優於", "強勁", "暴增", "上漲"]
NEGATIVE_WORDS = ["跌", "看壞", "利空", "衰退", "跌破", "創新低", "賣出", "降評", "下修", "不如", "放緩", "砍單", "下跌"]

def analyze_sentiment(news_list):
    if not news_list: return 0, "無最新消息"
    score = 0
    headlines = [n.get('title', '') for n in news_list[:5]]
    for title in headlines:
        for w in POSITIVE_WORDS:
            if w in title: score += 1
        for w in NEGATIVE_WORDS:
            if w in title: score -= 1
    if score > 0: return score, "🌞 媒體偏多"
    elif score < 0: return score, "⛈️ 媒體偏空"
    else: return score, "⛅ 消息中性"

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss)))

def send_line_notify(message):
    token = os.environ.get("LINE_NOTIFY_TOKEN")
    if not token:
        print("沒有設定 LINE_NOTIFY_TOKEN，跳過推播。")
        return
    
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"message": message}
    try:
        requests.post(url, headers=headers, data=data)
        print("✅ LINE 推播發送成功！")
    except Exception as e:
        print(f"❌ LINE 推播失敗：{e}")

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
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="80d")
            if df.empty: continue
            
            close = df['Close']
            price = round(close.iloc[-1], 2)
            ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
            rsi = round(calculate_rsi(close).iloc[-1], 1)
            cat = [k for k, v in CATEGORIES.items() if symbol in v]

            vol = df['Volume'].iloc[-1]
            avg_vol = df['Volume'].rolling(5).mean().iloc[-1] 
            vol_ratio = round(vol / avg_vol, 2) if avg_vol > 0 else 1

            news_data = ticker.news
            sent_score, sent_label = analyze_sentiment(news_data)

            # 將今日數據存入大資料庫
            new_row = {'date': today_str, 'symbol': symbol, 'price': price, 'volume': vol}
            history_df = pd.concat([history_df, pd.DataFrame([new_row])], ignore_index=True)

            # 【新技能】：抓取過去30天的私有歷史紀錄，轉成網頁看得懂的格式
            symbol_history = history_df[history_df['symbol'] == symbol].tail(30)
            history_list = symbol_history[['date', 'price', 'volume']].to_dict('records')

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
                "chip_signal": "🔥 大戶進場" if vol_ratio > 1.5 else "💤 散戶盤整",
                "sentiment_label": sent_label,
                "sentiment_score": sent_score,
                "history": history_list  # <--- 將私有歷史資料傳給前端
            })
        except Exception as e:
            print(f"跳過 {symbol}: {e}")

# === 原本的寫檔邏輯 ===
    history_df.tail(1500).to_csv(history_file, index=False)
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": today_str, "data": stock_data}, f, ensure_ascii=False, indent=4)

    # === 【新技能：生成戰情摘要並推播】 ===
    # 統計今天有幾檔「🔴 起步加速」(短線轉強)
    bull_stocks = [s['name'] for s in stock_data if s['lights']['short'] != '⚪']
    # 統計今天有幾檔「大戶偷偷進場」(量能大於1.5倍)
    hot_chips = [s['name'] for s in stock_data if s['vol_ratio'] > 1.5]
    
    msg = f"\n老闆早！阿土伯戰情室 {today_str} 報告：\n"
    msg += "----------------------\n"
    msg += f"🚀 準備起飛 ({len(bull_stocks)}檔)：\n"
    msg += f"{', '.join(bull_stocks) if bull_stocks else '無'}\n\n"
    
    msg += f"🕵️ 大戶偷偷進貨 ({len(hot_chips)}檔)：\n"
    msg += f"{', '.join(hot_chips) if hot_chips else '無'}\n"
    msg += "----------------------\n"
    msg += "詳細大數據圖表與新聞情緒，請至戰情室網頁查看！"

    # 發送推播
    send_line_notify(msg)

if __name__ == "__main__":
    analyze()
if __name__ == "__main__":
    analyze()


