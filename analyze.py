import yfinance as yf
import pandas as pd
import json
from datetime import datetime
import numpy as np
import os
import requests
import xml.etree.ElementTree as ET

# --- 全域設定 ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# --- 1. LINE 警報發送器 ---
def send_line_alert(message):
    token = os.environ.get("LINE_ACCESS_TOKEN")
    target_id = os.environ.get("LINE_TARGET_ID")
    if not token or not target_id:
        print(f"🔕 [未連線 LINE] 模擬發送通知：\n{message}")
        return
        
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    data = {"to": target_id, "messages": [{"type": "text", "text": message}]}
    try:
        requests.post(url, headers=headers, json=data)
        print("✅ LINE 警報發送成功！")
    except Exception as e:
        print(f"❌ LINE 系統錯誤: {e}")

# --- 2. PTT 爬蟲與 AI 情緒分析 ---
def get_ptt_news():
    print("📡 啟動 PTT 爬蟲，潛水抓取鄉民留言...")
    try:
        res = requests.get("https://www.ptt.cc/atom/stock.xml", headers=HEADERS, timeout=10)
        root = ET.fromstring(res.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        entries = root.findall('atom:entry', ns)
        ptt_list = []
        for entry in entries[:20]:
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            ptt_list.append({"title": title, "link": link})
        return ptt_list
    except Exception as e:
        print(f"❌ PTT 爬蟲失敗: {e}")
        return []

def get_ptt_sentiment(ptt_list):
    api_key = os.environ.get('GEMINI_API_KEY') 
    default_response = {"score": 50, "sentiment": "中立", "summary": "系統暫無情緒數據", "top_stocks": [], "bull_view": "無", "bear_view": "無", "raw_links": ptt_list[:5]}
    if not api_key or not ptt_list: return default_response

    print("🧠 啟動 LLM 語意分析，解讀散戶貪婪指數...")
    titles = [p['title'] for p in ptt_list]
    prompt = """你是頂級股市心理學家。請分析以下PTT股版最新標題，判斷台灣散戶情緒。
請嚴格輸出 JSON 格式，必須包含以下 key，不要任何其他文字：
{"score": 貪婪指數(0-100的整數), "sentiment": "極度恐慌|恐慌|中立|貪婪|極度貪婪", "summary": "25字以內的點評", "top_stocks": ["熱門股1", "熱門股2"], "bull_view": "多方論點(30字)", "bear_view": "空方擔憂(30字)"}
標題：\n""" + "\n".join(titles)

    url = "https://api.groq.com/openai/v1/chat/completions"
    data = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "response_format": {"type": "json_object"}}
    
    try:
        res = requests.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=data, timeout=20)
        if res.status_code == 200:
            text = res.json()['choices'][0]['message']['content'].strip()
            result = json.loads(text)
            result["raw_links"] = ptt_list[:5] 
            return result
        else: return default_response
    except Exception as e:
        print(f"❌ LLM 分析失敗: {e}")
        return default_response

# --- 3. 期望值計算機 ---
def calculate_strategy_ev(ticker, start_date, end_date, stop_loss_pct):
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['Signal'] = 0
    df.loc[df['Close'] > df['SMA_20'], 'Signal'] = 1
    df.loc[df['Close'] < df['SMA_20'], 'Signal'] = -1
    trades, entry_price, in_position = [], 0, False

    for index, row in df.iterrows():
        if in_position:
            stop_loss_price = entry_price * (1 - stop_loss_pct)
            if row['Low'] <= stop_loss_price:
                trades.append(-stop_loss_pct)
                in_position = False
                continue
            elif row['Signal'] == -1:
                trades.append((row['Close'] - entry_price) / entry_price)
                in_position = False
        elif not in_position and row['Signal'] == 1:
            entry_price, in_position = row['Close'], True

    if not trades: return None
    trades_series = pd.Series(trades)
    winning_trades = trades_series[trades_series > 0]
    losing_trades = trades_series[trades_series <= 0]
    p_win = len(winning_trades) / len(trades_series) if len(trades_series) > 0 else 0
    p_loss = len(losing_trades) / len(trades_series) if len(trades_series) > 0 else 0
    avg_win = winning_trades.mean() if not winning_trades.empty else 0
    avg_loss = abs(losing_trades.mean()) if not losing_trades.empty else 0 
    ev = (p_win * avg_win) - (p_loss * avg_loss)
    return {"ev": round(ev * 100, 2), "win_rate": round(p_win * 100, 2)}

# --- 4. 雙引擎大盤環境偵測器 (阿土伯升級版) ---
def check_market_regime():
    print("🌍 正在偵測大盤多空環境 (台股 0050 & 美股 SPY)...")
    stop_loss_config = {"TW": 0.05, "US": 0.05} # 預設都是多頭 5%
    alert_triggered = False
    alert_msg = "⚠️【阿土伯雙引擎戰報】\n大盤跌破月線防禦區！\n\n"

    # A. 偵測台股 (0050.TW)
    try:
        df_tw = yf.download("0050.TW", period="2mo", progress=False)
        if isinstance(df_tw.columns, pd.MultiIndex): df_tw.columns = df_tw.columns.droplevel(1)
        close_tw = df_tw['Close'].iloc[-1]
        ma20_tw = df_tw['Close'].rolling(window=20).mean().iloc[-1]
        if close_tw < ma20_tw:
            print("⚠️ 台股大盤跌破月線，啟動防禦！")
            stop_loss_config["TW"] = 0.03
            alert_triggered = True
            alert_msg += f"🇹🇼 台股 (0050): 收盤 {close_tw:.2f} < 月線 {ma20_tw:.2f}\n👉 策略停損縮緊至 3%\n\n"
        else:
            print("✅ 台股大盤站上月線，維持 5% 停損")
    except: pass

    # B. 偵測美股 (SPY)
    try:
        df_us = yf.download("SPY", period="2mo", progress=False)
        if isinstance(df_us.columns, pd.MultiIndex): df_us.columns = df_us.columns.droplevel(1)
        close_us = df_us['Close'].iloc[-1]
        ma20_us = df_us['Close'].rolling(window=20).mean().iloc[-1]
        if close_us < ma20_us:
            print("⚠️ 美股大盤跌破月線，啟動防禦！")
            stop_loss_config["US"] = 0.03
            alert_triggered = True
            alert_msg += f"🇺🇸 美股 (SPY): 收盤 {close_us:.2f} < 月線 {ma20_us:.2f}\n👉 策略停損縮緊至 3%\n\n"
        else:
            print("✅ 美股大盤站上月線，維持 5% 停損")
    except: pass

    # 如果有任何一個市場破線，發送 LINE 警報
    if alert_triggered:
        alert_msg += "🚨 系統已自動進入防禦模式，請嚴控資金風險！"
        send_line_alert(alert_msg)

    return stop_loss_config

# --- 5. 阿土狗決策大腦 ---
def get_expert_commentary(stock_name, ev, win_rate, rsi, bias, price, ma20, stop_loss):
    if ev >= 2.0: base_msg = f"📊 歷史回測表現極佳 (期望值 {ev}%)！這是一檔爆發力強的潛力股。"
    elif ev > 0:
        if win_rate >= 50: base_msg = f"📈 走勢穩健，期望值 {ev}% 且勝率過半 ({win_rate}%)，適合沿著均線順勢操作。"
        else: base_msg = f"🐺 標準的「賺大賠小」型態！勝率僅 {win_rate}%，代表主力洗盤洗得很兇，但嚴守 {int(stop_loss*100)}% 停損，長期期望值仍有 {ev}%！"
    else: base_msg = f"⚠️ 警告：目前策略陷入負期望值 ({ev}%)。近期容易雙巴，建議空手觀望，切忌賭徒式進場！"

    tech_msg = ""
    if rsi >= 75: tech_msg = f"不過目前 RSI 高達 {rsi} 嚴重過熱，短線隨時拉回，千萬別追高！"
    elif rsi <= 25: tech_msg = f"目前 RSI 僅 {rsi} 進入超賣區，配合乖離率 {bias}%，隨時醞釀反彈契機。"
    elif price < ma20 and ev > 0: tech_msg = f"需注意目前股價仍壓在月線 ({ma20}) 之下，上方壓力沉重，進場請嚴控資金。"
    elif bias > 10: tech_msg = f"目前正乖離來到 {bias}% 偏高，股價短線衝太快，沿著 5日線防守即可。"
    else: tech_msg = "技術指標目前處於溫和區間，請耐心等待量能表態的關鍵紅K。"
    return f"{base_msg} {tech_msg}"

# --- 6. 產生前端所需資料 (加入美股) ---
STOCKS = {
    "NVDA": {"name": "Nvidia (AI之王)", "category": "美國科技"},
    "TSLA": {"name": "Tesla (電動車)", "category": "美國科技"},
    "SPY": {"name": "S&P 500 ETF", "category": "美股大盤"},
    "2330.TW": {"name": "台積電", "category": "晶圓代工"},
    "2303.TW": {"name": "聯電", "category": "晶圓代工"},
    "0050.TW": {"name": "元大台灣50", "category": "台股龍頭"},
    "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"},
    "9910.TW": {"name": "豐泰", "category": "運動鞋"},
    "9904.TW": {"name": "寶成", "category": "運動鞋"}
}

def generate_dashboard_data():
    print(f"🚀 阿土伯資料中心啟動 [{datetime.now().strftime('%H:%M:%S')}]")
    
    ptt_articles = get_ptt_news()
    ptt_data = get_ptt_sentiment(ptt_articles)
    
    # 取得雙引擎停損設定 {"TW": 0.05/0.03, "US": 0.05/0.03}
    stop_loss_config = check_market_regime() 
    
    dashboard_data = []
    backtest_start = "2021-01-01"
    today_str = datetime.now().strftime("%Y-%m-%d")

    for symbol, info in STOCKS.items():
        print(f"   ➤ 正在解析並計算技術指標: {info['name']} ({symbol})")
        df = yf.download(symbol, period="1y", progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
            
        ticker_obj = yf.Ticker(symbol)
        try:
            latest_price = round(ticker_obj.fast_info.get('lastPrice', df['Close'].iloc[-1]), 2)
            df.iloc[-1, df.columns.get_loc('Close')] = latest_price
        except:
            latest_price = round(df['Close'].iloc[-1], 2)
            
        df['ma5'] = df['Close'].rolling(window=5).mean()
        df['ma20'] = df['Close'].rolling(window=20).mean()
        df['ma60'] = df['Close'].rolling(window=60).mean()
        df['std'] = df['Close'].rolling(window=20).std()
        df['bb_upper'] = df['ma20'] + 2 * df['std']
        df['bb_lower'] = df['ma20'] - 2 * df['std']
        
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df = df.fillna(0)
        
        history_data = []
        for idx, row in df.tail(60).iterrows():
            history_data.append({
                "date": idx.strftime("%Y-%m-%d"), "price": round(row['Close'], 2), "volume": int(row['Volume']),
                "ma5": round(row['ma5'], 2), "ma20": round(row['ma20'], 2), "ma60": round(row['ma60'], 2),
                "macd": round(row['macd'], 2), "macd_signal": round(row['macd_signal'], 2), "macd_hist": round(row['macd_hist'], 2),
                "rsi": round(row['rsi'], 2), "bb_upper": round(row['bb_upper'], 2), "bb_lower": round(row['bb_lower'], 2)
            })

        latest_rsi = round(df['rsi'].iloc[-1], 2)
        ma20_val = round(df['ma20'].iloc[-1], 2)
        bias = round(((latest_price - ma20_val) / ma20_val) * 100, 2) if ma20_val != 0 else 0
        
        # 💡 阿土伯核心邏輯：判斷這檔股票是美股還是台股，套用各自的大盤停損！
        market_type = "TW" if symbol.endswith(".TW") else "US"
        current_stop_loss = stop_loss_config[market_type]
        
        strategy_result = calculate_strategy_ev(symbol, backtest_start, today_str, stop_loss_pct=current_stop_loss)
        ev_val = strategy_result['ev'] if strategy_result else 0
        win_rate_val = strategy_result['win_rate'] if strategy_result else 0
        
        smart_summary = get_expert_commentary(info['name'], ev_val, win_rate_val, latest_rsi, bias, latest_price, ma20_val, current_stop_loss)
        
        stock_obj = {
            "symbol": symbol, "name": info["name"], "category": info["category"],
            "price": latest_price, "rsi": latest_rsi, "bias": bias,
            "vol_ratio": 1.2, "eps": "N/A", "pe_ratio": "N/A",
            "ev": ev_val, "win_rate": win_rate_val, 
            "history": history_data, 
            "ai_summary": f"[{'台股' if market_type=='TW' else '美股'}防禦等級: 停損 {int(current_stop_loss*100)}%] " + smart_summary,
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        }
        dashboard_data.append(stock_obj)

    # 💡 完美串接前端的總經速報區塊
    tw_status = "✅ 0050 穩居月線之上，維持 5% 停損" if stop_loss_config["TW"] == 0.05 else "⚠️ 0050 跌破月線！已啟動 3% 避險停損！"
    us_status = "✅ SPY 穩居月線之上，維持 5% 停損" if stop_loss_config["US"] == 0.05 else "⚠️ SPY 跌破月線！已啟動 3% 避險停損！"

    final_output = {
        "last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"),
        "data": dashboard_data,
        "ptt": ptt_data, 
        "macro": {"tw_insight": tw_status, "us_insight": us_status}
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
    print("✅ data.json 更新完成！台美雙引擎戰情室已全副武裝！")

if __name__ == "__main__":
    generate_dashboard_data()
