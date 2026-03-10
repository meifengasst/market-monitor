import yfinance as yf
import pandas as pd
import json
from datetime import datetime
import numpy as np
import os
import requests
import xml.etree.ElementTree as ET

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"}

def send_line_alert(message):
    token = os.environ.get("LINE_ACCESS_TOKEN")
    target_id = os.environ.get("LINE_TARGET_ID")
    if not token or not target_id: return
    try:
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, 
                      json={"to": target_id, "messages": [{"type": "text", "text": message}]})
    except: pass





def calculate_ev_from_df(df, atr_period=14, atr_multiplier=1.5):
    """
    阿土伯的 ATR 動態期望值與勝率回測系統
    """
    # 先呼叫 ATR 函數算出每天的波動
    df = calculate_atr_stop_loss(df, period=atr_period, multiplier=atr_multiplier)

    trades, entry_price, in_position, peak_price = [], 0, False, 0 
    
    for index, row in df.iterrows():
        if pd.isna(row['ATR']): continue

        if in_position:
            peak_price = max(peak_price, row['High'])
            trailing_stop = peak_price - (row['ATR'] * atr_multiplier) # 動態防守線
            
            if row['Low'] <= trailing_stop:
                actual_exit_price = min(row['Open'], trailing_stop)
                trades.append((actual_exit_price - entry_price) / entry_price)
                in_position = False
            elif row.get('Signal', 0) == -1:
                trades.append((row['Close'] - entry_price) / entry_price)
                in_position = False
        elif not in_position and row.get('Signal', 0) == 1:
            entry_price, in_position, peak_price = row['Close'], True, row['Close']

    if not trades: return {"ev": 0.0, "win_rate": 0.0, "trades_count": 0}
    ts = pd.Series(trades)
    win_ts, loss_ts = ts[ts > 0], ts[ts <= 0]
    p_win = len(win_ts) / len(ts) if len(ts) > 0 else 0
    ev = (p_win * (win_ts.mean() if not win_ts.empty else 0)) - ((1 - p_win) * (abs(loss_ts.mean()) if not loss_ts.empty else 0))
    return {"ev": round(ev * 100, 2), "win_rate": round(p_win * 100, 2), "trades_count": len(ts)}

def check_market_regime():
    regime = {"TW": False, "US": False} 
    alert_msg = "⚠️【阿土伯雙引擎戰報】\n大盤跌破月線防禦區！\n\n"
    triggered = False
    try:
        tw = yf.download("0050.TW", period="2mo", progress=False)
        if tw['Close'].iloc[-1].item() < tw['Close'].rolling(20).mean().iloc[-1].item():
            regime["TW"] = True; triggered = True
            alert_msg += f"🇹🇼 台股(0050)破線，啟動 3% 避險！\n"
    except: pass
    try:
        us = yf.download("SPY", period="2mo", progress=False)
        if us['Close'].iloc[-1].item() < us['Close'].rolling(20).mean().iloc[-1].item():
            regime["US"] = True; triggered = True
            alert_msg += f"🇺🇸 美股(SPY)破線，啟動 3% 避險！\n"
    except: pass
    if triggered: send_line_alert(alert_msg)
    return regime

STOCKS = {
    "NVDA": {"name": "Nvidia", "category": "美國科技"}, "TSLA": {"name": "Tesla", "category": "美國科技"}, "SPY": {"name": "S&P 500", "category": "美股大盤"},
    "2330.TW": {"name": "台積電", "category": "晶圓代工"}, "2337.TW": {"name": "旺宏", "category": "記憶體"},"3105.TWO": {"name": "穩懋", "category": "半導體"},
    "0050.TW": {"name": "台灣50", "category": "台股龍頭"}, "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"}, "9910.TW": {"name": "豐泰", "category": "運動鞋"}, 
    "9904.TW": {"name": "寶成", "category": "運動鞋"}
}

def get_ai_news_sentiment(symbol, stock_name):
    """抓取 Yahoo 財經新聞，並交給 Groq AI 判定多空情緒"""
    print(f"📰 正在掃描 {stock_name} 的新聞籌碼...")
    try:
        # 1. 抓取近期 3 條新聞 (避免塞爆 API)
        news_data = yf.Ticker(symbol).news[:3]
        if not news_data: 
            return []
        news_list = [{"title": n.get("title", ""), "link": n.get("link", "")} for n in news_data]
    except Exception as e:
        print(f"⚠️ 抓取 {symbol} 新聞失敗: {e}")
        return []

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return [{"title": n["title"], "link": n["link"], "sentiment": "中立 ⚪"} for n in news_list]

    # 2. 組合給 AI 看的 Prompt
    titles_text = "\n".join([f"新聞 {i+1}：{n['title']}" for i, n in enumerate(news_list)])
    system_prompt = """
    你是一位台灣股市資深操盤手。請判斷以下新聞標題對該公司股價是「利多」、「利空」還是「中立」。
    請務必嚴格以純 JSON 陣列格式回傳，不要加上任何 markdown 標記 (如 ```json) 或廢話！
    格式範例：
    [
        {"sentiment": "利多 🔴", "title": "新聞標題1"},
        {"sentiment": "利空 🟢", "title": "新聞標題2"}
    ]
    """
    user_prompt = f"股票：{stock_name}\n新聞列表：\n{titles_text}"

    # 3. 呼叫 Groq AI
    try:
        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.1
        }
        res = requests.post("[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)", headers=headers, json=payload, timeout=15)
        res.raise_for_status()
        
        # 處理 AI 回傳的字串，確保能被轉換為 JSON
        ai_text = res.json()["choices"][0]["message"]["content"].strip()
        if ai_text.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1
http://googleusercontent.com/immersive_entry_chip/2

---

### 🚀 驗收成果

1.  把這兩邊改完之後，推送到 GitHub。
2.  點擊你網頁上的 **「🔄 點我強制更新」**，讓 Python 重新跑一遍（這次會稍微久一點點，因為 AI 正在讀新聞）。
3.  更新完成後，每一張股票卡片的左上角都會多出一個藍色的 **「📰 AI 掃雷」** 按鈕。
4.  點擊它！你就會看到阿土伯 AI 幫你整理的最新新聞，並且貼上了清晰的「🔴 利多」或「🟢 利空」標籤。

快去改看看！如果 Python 在看新聞的時候出錯了，隨時把 Log 貼給阿土伯！

def get_us_market_summary():
    """抓取昨夜美股四大關鍵指標的漲跌幅"""
    symbols = {"SPY": "標普500", "SOXX": "費城半導體", "TSM": "台積電ADR", "^VIX": "恐慌指數"}
    summary = {}
    
    print("🌍 阿土伯正在收集昨夜美股戰報...")
    for sym, name in symbols.items():
        try:
            # 抓近兩天收盤價來算漲跌幅
            data = yf.download(sym, period="5d", progress=False)
            if len(data) >= 2:
                # 取得最後兩天的收盤價 (處理 yfinance 可能的 MultiIndex 格式)
                close_prices = data['Close'].iloc[-2:].values.flatten()
                prev_close = close_prices[0]
                last_close = close_prices[1]
                
                pct_change = ((last_close - prev_close) / prev_close) * 100
                summary[name] = {"price": round(last_close, 2), "pct": round(pct_change, 2)}
            else:
                summary[name] = {"price": 0, "pct": 0}
        except Exception as e:
            print(f"⚠️ 抓取 {name} 失敗: {e}")
            summary[name] = {"price": 0, "pct": 0}
            
    return summary

def generate_morning_script_via_groq(market_data):
    """將數據餵給 Groq，產出阿土伯的嚴格晨間劇本"""
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return "⚠️ 未設定 GROQ_API_KEY，無法產生晨間劇本。請遵守 20MA 紀律操作。"

    # 組合給 AI 看的數據
    data_str = ", ".join([f"{k}: 變化 {v['pct']}% (收 {v['price']})" for k, v in market_data.items()])
    
    # 💡 這就是【阿土伯專屬 Prompt】，鎖死它的語氣與風控邏輯！
    system_prompt = """
    你現在是台灣股市老手「阿土伯」，極度重視風險控制，極度痛恨賭徒式加碼與凹單。
    你的任務是根據提供的【昨夜美股數據】，給出【今日台股開盤的行動指南】。
    
    規則：
    1. 語氣要果斷、嚴厲、接地氣（可使用「接刀」、「韭菜」、「抱牢」、「紀律」等詞彙）。
    2. 必須給出「今日資金曝險上限建議（例如 20% 或 50%）」。
    3. 如果費半(SOXX)或台積電ADR(TSM)大跌，必須嚴格警告「開盤嚴禁接刀」。
    4. 字數嚴格限制在 80 字以內，不要廢話，直接給指令！
    """
    
    user_prompt = f"昨夜美股數據：{data_str}。請阿土伯下達今日台股操作鐵律！"

    try:
        print("🧠 呼叫 Groq AI 撰寫晨間劇本...")
        headers = {
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            # 💡 換成 Groq 目前官方最新、最穩定的模型名稱
            "model": "llama-3.1-8b-instant", 
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 150
        }
        
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        
        # 💡 阿土伯超級抓蟲器：如果伺服器退件，印出「詳細退件原因」
        if response.status_code != 200:
            print(f"❌ Groq 退件詳細原因: {response.text}")
            
        response.raise_for_status()
        script = response.json()["choices"][0]["message"]["content"].strip()
        return script
    except Exception as e:
        print(f"⚠️ Groq API 呼叫失敗: {e}")
        return "🤖 AI 戰情室連線異常，請手動依據 20MA 鐵律操作，縮小部位。"

def generate_dashboard_data():
    #ptt_data = get_ptt_sentiment(get_ptt_news())
    bear_markets = check_market_regime() 
    
    # 💡 阿土伯新增：讀取雲端庫存保險箱
    portfolio_file = "portfolio.json"
    try:
        with open(portfolio_file, "r", encoding="utf-8") as f:
            cloud_portfolio = json.load(f)
    except:
        cloud_portfolio = {}
    portfolio_updated = False
    
    tw_idx = yf.download("0050.TW", period="6mo", progress=False)
    us_idx = yf.download("SPY", period="6mo", progress=False)
    if isinstance(tw_idx.columns, pd.MultiIndex): tw_idx.columns = tw_idx.columns.droplevel(1)
    if isinstance(us_idx.columns, pd.MultiIndex): us_idx.columns = us_idx.columns.droplevel(1)
    
    dashboard_data = []

for symbol, info in STOCKS.items():
        print(f"處理中: {symbol}")
        df = yf.download(symbol, start="2021-01-01", progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            
        # ... (中間你原本獲取 Finnhub 即時報價跟計算 ma, macd, rsi 的程式碼保持不變) ...
        # (從 df['Signal'] = ... 之後接續以下內容)
        
        # 確保我們先算出基礎的 ATR
        df = calculate_atr_stop_loss(df, period=14, multiplier=1.5)
        current_price = round(df['Close'].iloc[-1], 2)
        current_atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.03) # 防呆

        # 💡 阿土伯 ATR 動態回測 (尋找最佳 ATR 倍數)
        best_multiplier, best_ev = 1.5, -999
        for mult in [1.5, 2.0, 2.5, 3.0]:
            res = calculate_ev_from_df(df, atr_period=14, atr_multiplier=mult)
            if res and res['ev'] > best_ev: best_ev, best_multiplier = res['ev'], mult
                
        is_bear = bear_markets["TW"] if symbol.endswith(".TW") else bear_markets["US"]
        # 如果大盤破線，防守倍數強制收緊至 1 倍 ATR，否則用最佳倍數
        actual_multiplier = 1.0 if is_bear else best_multiplier 
        actual_res = calculate_ev_from_df(df, atr_period=14, atr_multiplier=actual_multiplier)
        actual_ev = actual_res['ev'] if actual_res else 0
        actual_win = actual_res['win_rate'] if actual_res else 0

        # 為了配合前端網頁，將 ATR 距離換算回百分比 (%)
        best_sl_pct = (current_atr * best_multiplier) / current_price
        actual_sl_pct = (current_atr * actual_multiplier) / current_price

        # ... (中間你原本 LINE 警報檢查的程式碼保持不變，將 actual_sl 替換為 actual_sl_pct 即可) ...

        hist = [{"date": i.strftime("%Y-%m-%d"), "price": round(r['Close'], 2), "volume": int(r['Volume']), "ma5": round(r['ma5'], 2), "ma20": round(r['ma20'], 2), "ma60": round(r['ma60'], 2), "macd": round(r['macd'], 2), "macd_signal": round(r['macd_signal'], 2), "macd_hist": round(r['macd_hist'], 2), "rsi": round(r['rsi'], 2), "bb_upper": round(r['bb_upper'], 2), "bb_lower": round(r['bb_lower'], 2)} for i, r in df.tail(60).iterrows()]
        
        rs_comment = f"【主力資金偏好】近期表現強於大盤 {rs_score}%！" if rs_score > 5 else (f"【溫吞股】近期表現落後大盤 {rs_score}%。" if rs_score < 0 else "與大盤同步。")
        
        # 💡 動態生成系統點評 (消滅死板的 3%)
        ai_msg = f"🎯 最佳動態停損為 {int(best_sl_pct*100)}% (ATR {best_multiplier}倍)。"
        if is_bear:
            ai_msg += f"目前大盤破線，防守強制收緊至 {int(actual_sl_pct*100)}% (ATR 1倍)！ {rs_comment}"
        else:
            ai_msg += f"目前大盤穩定。 {rs_comment}"

        # 💡 呼叫 AI 新聞掃雷器，把菜煮好！
        news_list = get_ai_news_sentiment(symbol, info["name"])
        
        # 👉 將所有數據正式打包進 JSON (包含新聞！)
        dashboard_data.append({
            "symbol": symbol, "name": info["name"], "category": info["category"],
            "price": current_price, "rsi": round(df['rsi'].iloc[-1], 2), "bias": round(((current_price - df['ma20'].iloc[-1]) / df['ma20'].iloc[-1]) * 100, 2) if df['ma20'].iloc[-1] else 0,
            "vol_ratio": 1.2, "optimal_sl": int(best_sl_pct*100), "actual_sl": int(actual_sl_pct*100),
            "ev": actual_ev, "win_rate": actual_win, "history": hist, 
            "rs_score": rs_score, 
            "ai_summary": ai_msg,
            "news_items": news_list, # 👈 關鍵！終於把新聞塞進去了！
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        })

    # (這裡是你原本整理 dashboard_data.append 的地方)
        # ... 上面保持不變 ...

    # 💡 阿土伯新增：爬取 VIX 恐慌指數
    try:
        vix_price = round(yf.Ticker("^VIX").fast_info.get('lastPrice', 0), 2)
    except:
        vix_price = 0

    # 💡 呼叫阿土伯晨間戰情室 (獲取昨夜美股 + Groq AI 劇本)
    us_market_data = get_us_market_summary()
    morning_script = generate_morning_script_via_groq(us_market_data)

    above_20ma_count = sum(1 for d in dashboard_data if d['price'] > d['history'][-1]['ma20'])
    health_pct = int((above_20ma_count / len(dashboard_data)) * 100) if dashboard_data else 50

    # 把 AI 劇本跟美股數據一起打包
    market_health = {
        "vix": us_market_data.get("恐慌指數", {}).get("price", 0),
        "health_pct": health_pct,
        "us_summary": us_market_data,     # 傳給前端顯示紅綠燈
        "ai_script": morning_script       # 傳給前端顯示阿土伯指令
    }

    # 💡 存檔時，把原本的 "ptt": ptt_data 換成 "market_health": market_health
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({
            "last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"), 
            "data": dashboard_data, 
            "market_health": market_health, # 👈 這裡換成客觀數據雷達
            "macro": {"tw_insight": "⚠️ 0050破線避險" if bear_markets["TW"] else "✅ 0050多頭穩定", "us_insight": "⚠️ SPY破線避險" if bear_markets["US"] else "✅ SPY多頭穩定"}
        }, f, ensure_ascii=False, indent=4)

    # (這段原本就在 generate_dashboard_data 函數的最後面，保持這樣即可)
    # 💡 將更新後的庫存存回雲端
    if portfolio_updated:
        with open(portfolio_file, "w", encoding="utf-8") as f:
            json.dump(cloud_portfolio, f, ensure_ascii=False, indent=4)

# 確保這行是在最外層（沒有縮排）
if __name__ == "__main__": 
    generate_dashboard_data()







