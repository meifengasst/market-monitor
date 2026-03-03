import yfinance as yf
import json
import pandas as pd
import os
import requests
import time
import random
import google.generativeai as genai  # <--- 導入 AI 模組
from datetime import datetime

# 設定 Gemini API
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

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

# 【新技能】：AI 新聞總結 (含重試機制)
def get_ai_news_summary(stock_name, news_list):
    if not GEMINI_API_KEY or not news_list:
        return "🤖 AI 休息中，或無最新新聞。"
    
    headlines = [n.get('title', '') for n in news_list[:5]]
    news_text = "\n".join(headlines)
    prompt = f"你是股市老司機阿土伯。請根據以下【{stock_name}】的新聞標題，用繁體中文寫「30字以內」的一句話幽默短評（指出利多、利空或無聊即可）：\n{news_text}"
    
    model_candidates = ['gemini-1.5-flash', 'gemini-pro']
    for attempt in range(3):
        for model_name in model_candidates:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                return response.text.strip()
            except Exception as e:
                if "429" in str(e) or "Too Many Requests" in str(e):
                    time.sleep(2 ** attempt + random.random())
                    continue
                else:
                    continue
    return "🤖 新聞太多，阿土伯消化不良中..."

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss)))

def send_line_message(msg):
    token = os.environ.get("LINE_ACCESS_TOKEN")
    target_id = os.environ.get("LINE_TARGET_ID")
    if not token or not target_id: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"to": target_id, "messages": [{"type": "text", "text": msg}]}
    try:
        requests.post(url, headers=headers, data=json.dumps(data))
    except Exception as e:
        print(f"❌ 網路請求錯誤：{e}")

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
            
            # 呼叫 AI 幫你讀新聞 (會稍微花一點點時間)
            ai_summary = get_ai_news_summary(name, news_data)

            new_row = {'date': today_str, 'symbol': symbol, 'price': price, 'volume': vol}
            history_df = pd.concat([history_df, pd.DataFrame([new_row])], ignore_index=True)

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
                "ai_summary": ai_summary,  # <--- 把 AI 結論存起來給網頁用
                "history": history_list  
            })
            print(f"✅ 完成 {name} 分析")
            # 為了避免被 Google API 阻擋，每次分析完稍微休息 2 秒
            time.sleep(2)
            
        except Exception as e:
            print(f"跳過 {symbol}: {e}")

    history_df.tail(1500).to_csv(history_file, index=False)
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": today_str, "data": stock_data}, f, ensure_ascii=False, indent=4)

    bull_stocks = [s['name'] for s in stock_data if s['lights']['short'] != '⚪']
    hot_chips = [s['name'] for s in stock_data if s['vol_ratio'] > 1.5]
    
    msg = f"\n老闆早！阿土伯戰情室 {today_str} 報告：\n"
    msg += "----------------------\n"
    msg += f"🚀 準備起飛 ({len(bull_stocks)}檔)：\n"
    msg += f"{', '.join(bull_stocks) if bull_stocks else '無'}\n\n"
    msg += f"🕵️ 大戶偷偷進貨 ({len(hot_chips)}檔)：\n"
    msg += f"{', '.join(hot_chips) if hot_chips else '無'}\n"
    msg += "----------------------\n"
    msg += "詳細 AI 大數據圖表與新聞情緒，請至戰情室網頁查看！"

    send_line_message(msg)

if __name__ == "__main__":
    analyze()
