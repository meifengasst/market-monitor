import yfinance as yf
import json
import pandas as pd
import os
import requests
import time
from datetime import datetime

# 1. 鑰匙與配置 (從 GitHub 保險箱讀取)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")
LINE_TARGET_ID = os.environ.get("LINE_TARGET_ID")

CATEGORIES = {
    "美國科技": ["NVDA", "TSLA"],
    "美股大盤": ["SPY"],
    "台股龍頭": ["0050.TW", "2330.TW"],
    "晶圓代工": ["2330.TW",],
    "運動鞋": ["9802.TW", "9910.TW",]
}

STOCKS = {
    "NVDA": "Nvidia (AI之王)", "TSLA": "Tesla (電動車)", "SPY": "S&P 500 ETF",
    "0050.TW": "元大台灣50", "2330.TW": "台積電", 
    "9802.TW": "鈺齊-KY", "9910.TW": "豐泰", 
}

# 2. 🤖 AI 讀報大腦 (直球 REST API 版 + 風險評估)
def get_ai_summary(stock_name, price, bias, news_list):
    if not GEMINI_API_KEY: 
        return "🤖 找不到鑰匙：請檢查 GEMINI_API_KEY 設定！"
    if not news_list: 
        return "目前市場靜悄悄，無最新新聞。"
    
    headlines = [n.get('title', '') for n in news_list[:5]]
    
    # 🎯 讓 AI 根據乖離率給出「操作建議」
    prompt = f"你是台股資深股神阿土伯。標的【{stock_name}】，現價{price}，乖離率{bias}%。請根據這些數據與以下新聞，用繁體中文寫25字內的一句話『操作建議』（如：分批獲利、等待拉回或撿便宜）：\n" + "\n".join(headlines)
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    try:
        res = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10)
        return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except: 
        return "🤖 阿土伯正在盯盤，暫無評論。"

# 3. 數學運算工具
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss + 1e-9)))

# 4. LINE 推播秘書
def send_line_message(msg):
    if not LINE_ACCESS_TOKEN or not LINE_TARGET_ID: 
        print("未設定 LINE Token，跳過推播")
        return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    data = {"to": LINE_TARGET_ID, "messages": [{"type": "text", "text": msg}]}
    try: 
        requests.post(url, headers=headers, json=data)
    except Exception as e: 
        print(f"❌ LINE 推播失敗: {e}")

# 5. 核心引擎 (已修復縮排)
def analyze():
    history_file = 'chip_history.csv'
    stock_data = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 讀取或初始化歷史檔案
    if os.path.exists(history_file):
        hist_df = pd.read_csv(history_file)
    else:
        hist_df = pd.DataFrame(columns=['date','symbol','price','volume'])

    for symbol, name in STOCKS.items():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="80d")
            if df.empty: continue
            
            close = df['Close']
            price = round(close.iloc[-1], 2)
            
            # 計算均線
            ma5 = close.rolling(5).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1]
            
            # 🛡️ 計算乖離率 (Bias) 與風險等級
            bias = round(((price - ma20) / ma20) * 100, 2)
            risk_level = "😱 極高" if bias > 10 else ("📉 超跌" if bias < -10 else "🧐 正常")

            # 計算 RSI 與量能比例
            rsi = round(calculate_rsi(close).iloc[-1], 1)
            vol_ratio = round(df['Volume'].iloc[-1] / df['Volume'].rolling(5).mean().iloc[-1], 2)
            
            # 判斷產業分類
            cat_name = [k for k, v in CATEGORIES.items() if symbol in v][0] if any(symbol in v for v in CATEGORIES.values()) else "其他"
            
            # 存入每日歷史庫
            new_row = {'date': today_str, 'symbol': symbol, 'price': price, 'volume': df['Volume'].iloc[-1]}
            hist_df = pd.concat([hist_df, pd.DataFrame([new_row])], ignore_index=True)
            
            # 呼叫 AI 大腦
            ai_text = get_ai_summary(name, price, bias, ticker.news)
            
            # 統整單檔股票數據
            stock_data.append({
                "symbol": symbol, "name": name, "category": cat_name, "price": price, "rsi": rsi,
                "bias": bias, "risk_level": risk_level, "vol_ratio": vol_ratio, "ai_summary": ai_text,
                "lights": {"short": "🔴" if price > ma5 else "⚪", "mid": "🟡" if price > ma20 else "⚪", "long": "🟢" if price > ma60 else "⚪"},
                "history": hist_df[hist_df['symbol'] == symbol].tail(30).to_dict('records')
            })
            time.sleep(1) # 溫柔一點，避開 Google API 的限制
            print(f"✅ 完成 {name} 分析")
        except Exception as e: 
            print(f"❌ 錯誤 {symbol}: {e}")

    # 📊 計算產業統計數據 (給網頁上方的雷達圖用)
    cat_stats = []
    for cat, members in CATEGORIES.items():
        relevant = [s for s in stock_data if s['symbol'] in members]
        if relevant:
            avg_rsi = sum(s['rsi'] for s in relevant) / len(relevant)
            cat_stats.append({"category": cat, "avg_rsi": round(avg_rsi, 1)})

    # 將資料寫入 JSON 與 CSV
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": today_str, "data": stock_data, "cat_stats": cat_stats}, f, ensure_ascii=False, indent=4)
    hist_df.tail(2000).to_csv(history_file, index=False)
    
    # 📱 準備與發送 LINE 晨報
    bull_stocks = [s['name'] for s in stock_data if s['lights']['short'] != '⚪']
    hot_chips = [s['name'] for s in stock_data if s['vol_ratio'] > 1.5]
    
    msg = f"\n老闆早！阿土伯戰情室 {today_str} 報告：\n"
    msg += "----------------------\n"
    msg += f"🚀 準備起飛 ({len(bull_stocks)}檔)：\n"
    msg += f"{', '.join(bull_stocks) if bull_stocks else '無'}\n\n"
    msg += f"🕵️ 大戶偷偷進貨 ({len(hot_chips)}檔)：\n"
    msg += f"{', '.join(hot_chips) if hot_chips else '無'}\n"
    msg += "----------------------\n"
    msg += "戰情雷達與 AI 風險分析已更新，請至網頁查看！"
    
    send_line_message(msg)
    print("🎉 系統更新完成！")

if __name__ == "__main__":
    analyze()

