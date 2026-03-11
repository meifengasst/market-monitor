import yfinance as yf
import feedparser
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
    if not token or not target_id:
        return
    try:
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, 
                      json={"to": target_id, "messages": [{"type": "text", "text": message}]})
    except Exception as e:
        print(f"⚠️ LINE 警報發送失敗: {e}")

def calculate_ev_from_df(df, stop_loss_pct):
    trades, entry_price, in_position = [], 0, False
    peak_price = 0 
    
    for index, row in df.iterrows():
        if in_position:
            peak_price = max(peak_price, row['High'])
            fixed_stop = entry_price * (1 - stop_loss_pct)
            trailing_stop = peak_price * (1 - stop_loss_pct)
            actual_exit_price = max(fixed_stop, trailing_stop)

            if row['Low'] <= actual_exit_price:
                trades.append((actual_exit_price - entry_price) / entry_price)
                in_position = False
            elif row['Signal'] == -1:
                trades.append((row['Close'] - entry_price) / entry_price)
                in_position = False
        elif not in_position and row['Signal'] == 1:
            entry_price, in_position = row['Close'], True
            peak_price = row['Close']

    if not trades: return None
    ts = pd.Series(trades)
    win_ts, loss_ts = ts[ts > 0], ts[ts <= 0]
    p_win = len(win_ts) / len(ts) if len(ts) > 0 else 0
    ev = (p_win * (win_ts.mean() if not win_ts.empty else 0)) - ((len(loss_ts) / len(ts) if len(ts) > 0 else 0) * (abs(loss_ts.mean()) if not loss_ts.empty else 0))
    return {"ev": round(ev * 100, 2), "win_rate": round(p_win * 100, 2)}

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
    print(f"📰 正在掃描 {stock_name} 的新聞籌碼...")
    try:
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

    try:
        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.1
        }
        res = requests.post("[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)", headers=headers, json=payload, timeout=15)
        res.raise_for_status()
        
        ai_text = res.json()["choices"][0]["message"]["content"].strip()
        if ai_text.startswith("```json"):
            ai_text = ai_text[7:]
        if ai_text.endswith("```"):
            ai_text = ai_text[:-3]
            
        return json.loads(ai_text.strip())
    except Exception as e:
        print(f"⚠️ AI 新聞解析失敗 ({stock_name}): {e}")
        return [{"title": n["title"], "link": n["link"], "sentiment": "解析失敗 ⚠️"} for n in news_list]

def get_us_market_summary():
    symbols = {"SPY": "標普500", "SOXX": "費城半導體", "TSM": "台積電ADR", "^VIX": "恐慌指數"}
    summary = {}
    
    print("🌍 阿土伯正在收集昨夜美股戰報...")
    for sym, name in symbols.items():
        try:
            data = yf.download(sym, period="5d", progress=False)
            if len(data) >= 2:
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
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return "⚠️ 未設定 GROQ_API_KEY，無法產生晨間劇本。請遵守 20MA 紀律操作。"

    data_str = ", ".join([f"{k}: 變化 {v['pct']}% (收 {v['price']})" for k, v in market_data.items()])
    
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
            "model": "llama-3.1-8b-instant", 
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 150
        }
        
        response = requests.post("[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)", headers=headers, json=payload, timeout=20)
        if response.status_code != 200:
            print(f"❌ Groq 退件詳細原因: {response.text}")
            
        response.raise_for_status()
        script = response.json()["choices"][0]["message"]["content"].strip()
        return script
    except Exception as e:
        print(f"⚠️ Groq API 呼叫失敗: {e}")
        return "🤖 AI 戰情室連線異常，請手動依據 20MA 鐵律操作，縮小部位。"

def generate_dashboard_data():
    bear_markets = check_market_regime() 
    
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
            
        if not symbol.endswith(".TW"):
            finnhub_key = os.environ.get("FINNHUB_API_KEY")
            if finnhub_key:
                try:
                    res = requests.get(f"[https://finnhub.io/api/v1/quote?symbol=](https://finnhub.io/api/v1/quote?symbol=){symbol}&token={finnhub_key}", timeout=5)
                    if res.status_code == 200:
                        real_time_price = res.json().get('c')
                        if real_time_price and real_time_price > 0:
                            df.iloc[-1, df.columns.get_loc('Close')] = round(real_time_price, 2)
                            print(f"⚡ {symbol} 成功獲取 Finnhub 即時報價: {real_time_price}")
                except Exception as e:
                    print(f"⚠️ {symbol} Finnhub 報價失敗，退回歷史收盤價")
        else:
            try: df.iloc[-1, df.columns.get_loc('Close')] = round(yf.Ticker(symbol).fast_info.get('lastPrice', df['Close'].iloc[-1]), 2)
            except: pass
        
        df['ma5'] = df['Close'].rolling(5).mean()
        df['ma20'] = df['Close'].rolling(20).mean()
        df['ma60'] = df['Close'].rolling(60).mean()
        df['std'] = df['Close'].rolling(20).std()
        df['bb_upper'], df['bb_lower'] = df['ma20'] + 2 * df['std'], df['ma20'] - 2 * df['std']
        df['macd'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        delta = df['Close'].diff()
        df['rsi'] = 100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / -delta.where(delta < 0, 0).rolling(14).mean())))
        
        # 💡 ATR 在這啦！
        df['prev_close'] = df['Close'].shift(1)
        df['tr1'] = df['High'] - df['Low']
        df['tr2'] = abs(df['High'] - df['prev_close'])
        df['tr3'] = abs(df['Low'] - df['prev_close'])
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['atr'] = df['tr'].rolling(window=14).mean()

        df['Signal'] = np.where(df['Close'] > df['ma20'], 1, np.where(df['Close'] < df['ma20'], -1, 0))
        df = df.fillna(0)
        
        try:
            market_idx = tw_idx if symbol.endswith(".TW") else us_idx
            stock_ret_20 = (df['Close'].iloc[-1] - df['Close'].iloc[-20]) / df['Close'].iloc[-20]
            idx_ret_20 = (market_idx['Close'].iloc[-1] - market_idx['Close'].iloc[-20]) / market_idx['Close'].iloc[-20]
            rs_score = round((stock_ret_20 - idx_ret_20) * 100, 2)
        except:
            rs_score = 0
        
        best_sl, best_ev = 0.05, -999
        for sl in [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12]:
            res = calculate_ev_from_df(df, sl)
            if res and res['ev'] > best_ev: best_ev, best_sl = res['ev'], sl
                
        is_bear = bear_markets["TW"] if symbol.endswith(".TW") else bear_markets["US"]
        actual_sl = 0.03 if is_bear else best_sl
        actual_res = calculate_ev_from_df(df, actual_sl)
        actual_ev = actual_res['ev'] if actual_res else 0
        actual_win = actual_res['win_rate'] if actual_res else 0

        current_price = round(df['Close'].iloc[-1], 2)

        if symbol in cloud_portfolio:
            trade = cloud_portfolio[symbol]
            entry_price = trade.get('entryPrice', current_price)
            peak_price = trade.get('peakPrice', entry_price)

            if current_price > peak_price:
                trade['peakPrice'] = current_price
                portfolio_updated = True
                peak_price = current_price

            actual_exit_price = max(entry_price * (1 - actual_sl), peak_price * (1 - actual_sl))

            if current_price <= actual_exit_price:
                if not trade.get('alerted', False):
                    if is_bear:
                        reason_msg = f"\n⚠️ [大盤避險啟動]\n停損已由 {int(best_sl*100)}% 強制收緊至 3%！"
                    else:
                        reason_msg = f"\n(套用系統最佳停損 {int(best_sl*100)}%)"

                    alert_msg = f"🚨【阿土伯停損逃命警報】🚨\n\n股票：{info['name']} ({symbol})\n現價：${current_price}\n防線：${round(actual_exit_price, 2)}{reason_msg}\n\n⚡ 已跌破嚴格防線，請立即無情清倉，保護本金！"
                    
                    send_line_alert(alert_msg)
                    trade['alerted'] = True
                    portfolio_updated = True
            else:
                if trade.get('alerted', False):
                    trade['alerted'] = False
                    portfolio_updated = True

        news_sentiment_data = get_ai_news_sentiment(symbol, info["name"])

        hist = [{"date": i.strftime("%Y-%m-%d"), "price": round(r['Close'], 2), "volume": int(r['Volume']), "ma5": round(r['ma5'], 2), "ma20": round(r['ma20'], 2), "ma60": round(r['ma60'], 2), "macd": round(r['macd'], 2), "macd_signal": round(r['macd_signal'], 2), "macd_hist": round(r['macd_hist'], 2), "rsi": round(r['rsi'], 2), "bb_upper": round(r['bb_upper'], 2), "bb_lower": round(r['bb_lower'], 2), "atr": round(r['atr'], 2)} for i, r in df.tail(60).iterrows()]
        
        rs_comment = f"【主力資金偏好】近期表現強於大盤 {rs_score}%！" if rs_score > 5 else (f"【溫吞股】近期表現落後大盤 {rs_score}%。" if rs_score < 0 else "與大盤同步。")
        
        dashboard_data.append({
            "symbol": symbol, "name": info["name"], "category": info["category"],
            "price": current_price, "rsi": round(df['rsi'].iloc[-1], 2), "bias": round(((current_price - df['ma20'].iloc[-1]) / df['ma20'].iloc[-1]) * 100, 2) if df['ma20'].iloc[-1] else 0,
            "atr": round(df['atr'].iloc[-1], 2),
            "news_sentiment": news_sentiment_data,
            "vol_ratio": 1.2, "optimal_sl": int(best_sl*100), "actual_sl": int(actual_sl*100),
            "ev": actual_ev, "win_rate": actual_win, "history": hist, 
            "rs_score": rs_score, 
            "ai_summary": f"🎯 最佳移動停利/停損為 {int(best_sl*100)}%。{'目前大盤破線，已強制縮緊至 3% 防守！' if is_bear else '目前大盤穩定。'} {rs_comment}",
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        })

    try:
        vix_price = round(yf.Ticker("^VIX").fast_info.get('lastPrice', 0), 2)
    except:
        vix_price = 0

    us_market_data = get_us_market_summary()
    morning_script = generate_morning_script_via_groq(us_market_data)

    above_20ma_count = sum(1 for d in dashboard_data if d['price'] > d['history'][-1]['ma20'])
    health_pct = int((above_20ma_count / len(dashboard_data)) * 100) if dashboard_data else 50

    market_health = {
        "vix": us_market_data.get("恐慌指數", {}).get("price", 0),
        "health_pct": health_pct,
        "us_summary": us_market_data,     
        "ai_script": morning_script       
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({
            "last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"), 
            "data": dashboard_data, 
            "market_health": market_health,
            "macro": {"tw_insight": "⚠️ 0050破線避險" if bear_markets["TW"] else "✅ 0050多頭穩定", "us_insight": "⚠️ SPY破線避險" if bear_markets["US"] else "✅ SPY多頭穩定"}
        }, f, ensure_ascii=False, indent=4)

    if portfolio_updated:
        with open(portfolio_file, "w", encoding="utf-8") as f:
            json.dump(cloud_portfolio, f, ensure_ascii=False, indent=4)

if __name__ == "__main__": 
    generate_dashboard_data()

