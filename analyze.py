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

# 2. 🤖 AI 預判大腦 (🚀 光速黑馬 Groq API 版)
def get_ai_prediction(stock_name, price, bias, pe_ratio, eps, news_list):
    # 這裡我們借用原本的變數名稱，但裡面放的是你新申請的 Groq 金鑰
    API_KEY = os.environ.get('GEMINI_API_KEY') 
    
    if not API_KEY: 
        return "🤖 找不到鑰匙：請檢查 GitHub 金鑰設定！"
    
    headlines = [n.get('title', '') for n in news_list[:5]] if news_list else ["無最新重大新聞"]
    prompt = f"你是資深股市觀察家阿土伯。標的【{stock_name}】，現價{price}，乖離率{bias}%，本益比{pe_ratio}，EPS為{eps}。請綜合基本面、技術面與以下新聞，用繁體中文寫「40字以內」的客觀趨勢點評：\n" + "\n".join(headlines)
    
    # 🎯 關鍵修改：把網址換成 Groq 的主機，並指定使用 Meta 最強大的 Llama 3 70B 模型
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "llama3-70b-8192", 
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5 # 讓它的回答客觀冷靜一點
    }
    
    try:
        res = requests.post(url, headers=headers, json=data, timeout=10)
        result = res.json()
        
        if res.status_code == 200:
            return result['choices'][0]['message']['content'].strip()
        else:
            err_msg = result.get('error', {}).get('message', '未知錯誤')
            print(f"【API 錯誤】{stock_name}: {err_msg}")
            return f"🤖 API 錯誤：{err_msg}"
            
    except Exception as e:
        print(f"【系統錯誤】{stock_name}: {e}")
        return "🤖 網路連線或系統逾時..."

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    return 100 - (100 / (1 + (gain / loss + 1e-9)))

def send_line_message(msg):
    if not LINE_ACCESS_TOKEN or not LINE_TARGET_ID: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    data = {"to": LINE_TARGET_ID, "messages": [{"type": "text", "text": msg}]}
    try: requests.post(url, headers=headers, json=data)
    except Exception as e: print(f"❌ LINE 推播失敗: {e}")

def analyze():
    history_file = 'chip_history.csv'
    stock_data = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
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
            
            # 📊 抓取基本面財報數據 (PE & EPS)
            info = ticker.info
            pe_ratio = info.get('trailingPE', 'N/A')
            pe_ratio = round(pe_ratio, 1) if isinstance(pe_ratio, (int, float)) else pe_ratio
            eps = info.get('trailingEps', 'N/A')
            
            # 技術面指標
            ma5, ma20, ma60 = close.rolling(5).mean().iloc[-1], close.rolling(20).mean().iloc[-1], close.rolling(60).mean().iloc[-1]
            bias = round(((price - ma20) / ma20) * 100, 2)
            risk_level = "😱 極高" if bias > 10 else ("📉 超跌" if bias < -10 else "🧐 正常")
            rsi = round(calculate_rsi(close).iloc[-1], 1)
            vol_ratio = round(df['Volume'].iloc[-1] / df['Volume'].rolling(5).mean().iloc[-1], 2)
            cat_name = [k for k, v in CATEGORIES.items() if symbol in v][0] if any(symbol in v for v in CATEGORIES.values()) else "其他"
            
            # 存歷史
            new_row = {'date': today_str, 'symbol': symbol, 'price': price, 'volume': df['Volume'].iloc[-1]}
            hist_df = pd.concat([hist_df, pd.DataFrame([new_row])], ignore_index=True)
            
            # 🧠 呼叫 AI 進行大數據預判
            ai_text = get_ai_prediction(name, price, bias, pe_ratio, eps, ticker.news)
            
            stock_data.append({
                "symbol": symbol, "name": name, "category": cat_name, "price": price, "rsi": rsi,
                "bias": bias, "risk_level": risk_level, "vol_ratio": vol_ratio, 
                "pe_ratio": pe_ratio, "eps": eps, "ai_summary": ai_text,
                "lights": {"short": "🔴" if price > ma5 else "⚪", "mid": "🟡" if price > ma20 else "⚪", "long": "🟢" if price > ma60 else "⚪"},
                "history": hist_df[hist_df['symbol'] == symbol].tail(30).to_dict('records')
            })
            time.sleep(1)
            print(f"✅ 完成 {name} 分析 (PE: {pe_ratio}, EPS: {eps})")
        except Exception as e: 
            print(f"❌ 錯誤 {symbol}: {e}")

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump({"last_update": today_str, "data": stock_data}, f, ensure_ascii=False, indent=4)
    hist_df.tail(2000).to_csv(history_file, index=False)
    
    # LINE 推播
    bull_stocks = [s['name'] for s in stock_data if s['lights']['short'] != '⚪']
    hot_chips = [s['name'] for s in stock_data if s['vol_ratio'] > 1.5]
    msg = f"\n老闆早！阿土伯戰情室 {today_str} 報告：\n----------------------\n🚀 準備起飛 ({len(bull_stocks)}檔)：\n{', '.join(bull_stocks) if bull_stocks else '無'}\n\n🕵️ 大戶進貨 ({len(hot_chips)}檔)：\n{', '.join(hot_chips) if hot_chips else '無'}\n----------------------\n財報預判大腦已上線，請至網頁查看！"
    send_line_message(msg)

if __name__ == "__main__":
    analyze()


