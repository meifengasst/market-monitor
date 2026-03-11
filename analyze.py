import yfinance as yf
import feedparser
import pandas as pd
from datetime import datetime, timedelta
import json
from datetime import datetime
import numpy as np
import os
import requests
import xml.etree.ElementTree as ET
import re
import time


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

def get_ai_news_sentiment(stock_name, symbol):
    """抓取近15天內最多5則重大新聞，並交由 AI 判斷多空"""
    print(f"📰 啟動精準雷達，抓取 {stock_name} 近15日新聞...")
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news
        
        recent_news = []
        now = datetime.now()
        fifteen_days_ago = now - timedelta(days=15) # 💡 設定時間軸：15天前
        
        # 1. 過濾時間
        for item in raw_news:
            # Yahoo 的時間戳是秒數，轉換成日期格式
            pub_time = datetime.fromtimestamp(item['providerPublishTime'])
            if pub_time >= fifteen_days_ago:
                recent_news.append({
                    "title": item['title'],
                    "link": item['link'],
                    "date": pub_time.strftime("%Y-%m-%d") # 順便把日期記下來
                })
                
        # 2. 擷取前 5 則最新新聞
        top_news = recent_news[:5]
        
        if not top_news:
            return [{"title": "近半個月內無重大新聞，主力可能在休假😴", "sentiment": "中立", "link": "#", "date": now.strftime("%Y-%m-%d")}]

        # 3. 組裝給 AI 看的新聞報紙
        news_text = ""
        for i, n in enumerate(top_news):
            news_text += f"新聞 {i+1} ({n['date']}): {n['title']}\n"

        groq_api_key = os.environ.get("GROQ_API_KEY")
        if not groq_api_key:
            return [{"title": n['title'], "sentiment": "未連線", "link": n['link'], "date": n['date']} for n in top_news]

        system_prompt = """
        你是一位華爾街資深分析師。請閱讀以下近15日內的重大新聞標題，判斷其對該公司的影響。
        請【嚴格以純 JSON 陣列格式】回傳。
        每個新聞項目包含：title (請將新聞標題翻譯成繁體中文), sentiment (僅限回傳：利多、利空、中立)。
        
        【回傳格式範例】：
        [
            {"title": "輝達發布新一代AI晶片...", "sentiment": "利多"},
            {"title": "特斯拉降價促銷...", "sentiment": "利空"}
        ]
        """
        user_prompt = f"股票：{stock_name}\n近期新聞：\n{news_text}"

        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.3,
            "max_tokens": 800
        }
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        res.raise_for_status()
        
        ai_text = res.json()["choices"][0]["message"]["content"].strip()
        ai_text = re.sub(r'```json|```', '', ai_text).strip()
        parsed_data = json.loads(ai_text)
        
        # 4. 把 AI 翻譯好的標題跟原本的連結、日期合併起來
        final_result = []
        for i, item in enumerate(parsed_data):
            if i < len(top_news): # 防呆，避免 AI 回傳太多或太少
                final_result.append({
                    "title": item.get("title", top_news[i]["title"]),
                    "sentiment": item.get("sentiment", "中立"),
                    "link": top_news[i]["link"],
                    "date": top_news[i]["date"] # 💡 把日期傳給網頁
                })
        return final_result

    except Exception as e:
        print(f"⚠️ 新聞掃雷失敗 ({stock_name}): {e}")
        return [{"title": "新聞掃雷器故障或限速中", "sentiment": "未判定", "link": "#", "date": "未知"}]

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
        
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        if response.status_code != 200:
            print(f"❌ Groq 退件詳細原因: {response.text}")
            
        response.raise_for_status()
        script = response.json()["choices"][0]["message"]["content"].strip()
        return script
    except Exception as e:
        print(f"⚠️ Groq API 呼叫失敗: {e}")
        return "🤖 AI 戰情室連線異常，請手動依據 20MA 鐵律操作，縮小部位。"
        
def get_ai_technical_brain(stock_name, recent_df, rs_score):
    """【進化三】連貫型態與多空辯論綜合大腦 (傳入近5日數據)"""
    print(f"🕵️‍♂️ 啟動連貫型態掃描與多空辯論：{stock_name}...")
    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return {"pattern": "未知", "bull": "無法連線", "bear": "無法連線", "judge": "⚠️ 未設定 API KEY。"}

    # 💡 阿土伯秘笈：把過去 5 天的「收盤價、成交量、月線、RSI」串成文字，讓 AI 看出連續動作！
    trend_str = ""
    for date, row in recent_df.iterrows():
        trend_str += f"{date.strftime('%m/%d')} - 收:{row['Close']:.2f} | 量:{int(row['Volume'])} | 20MA:{row['ma20']:.2f} | RSI:{row['rsi']:.2f}\n"

    system_prompt = """
    你現在是一個「台股高階量化戰情室」。
    請觀察提供的【近5日價格與量能變化】，辨識出目前的「籌碼型態」（例如：量縮洗盤、爆量長黑、底部分型、破線崩跌、帶量突破等），並進行多空辯論。
    請【嚴格以純 JSON 格式】回傳。
    
    【阿土伯鐵律】：
    最後一天的收盤價如果小於 20MA，最終裁決(judge)必須是偏空或觀望，嚴禁建議買進！
    
    【回傳 JSON 格式】：
    {
        "pattern": "型態名稱(限8個字，如: 價平量縮)",
        "bull": "多方觀點(限15字，請結合近5日量價解讀)",
        "bear": "空方觀點(限15字，請結合近5日量價解讀)",
        "judge": "阿土伯最終裁決(限20字，嚴守紀律)"
    }
    """
    user_prompt = f"股票：{stock_name}\n相對大盤強弱：{rs_score}%\n近5日量價變化：\n{trend_str}"

    try:
        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.2, 
            "max_tokens": 200
        }
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        res.raise_for_status()
        
        ai_text = res.json()["choices"][0]["message"]["content"].strip()
        ai_text = re.sub(r'```json|```', '', ai_text).strip()
        
        match = re.search(r'\{.*\}', ai_text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            return {"pattern": "解析失敗", "bull": "格式錯誤", "bear": "格式錯誤", "judge": "🤖 格式跑掉啦！"}
            
    except Exception as e:
        print(f"⚠️ 綜合大腦失敗 ({stock_name}): {e}")
        return {"pattern": "連線中斷", "bull": "連線異常", "bear": "連線異常", "judge": "🤖 API 限速或異常。"}

def get_fundamental_risk(symbol, stock_name):
    """阿土伯的財報照妖鏡：抓取基本面數據，交給 Groq AI 抓出隱藏風險"""
    print(f"🔎 正在調閱 {stock_name} 的財務報表...")
    try:
        # 抓取基本面數據 (P/E, ROE, 營收成長, 毛利率)
        info = yf.Ticker(symbol).info
        pe = info.get('trailingPE', '未知')
        pb = info.get('priceToBook', '未知')
        roe = info.get('returnOnEquity', '未知')
        rev_growth = info.get('revenueGrowth', '未知')
        margins = info.get('profitMargins', '未知')

        # 如果連最基本的 PE 都沒有，代表可能沒抓到資料
        if pe == '未知' and roe == '未知':
            return "⚠️ 財報數據連線異常，請手動查閱公開資訊觀測站。"

        # 把小數點轉換成百分比，方便 AI 大腦閱讀
        if roe != '未知': roe = f"{round(roe * 100, 2)}%"
        if rev_growth != '未知': rev_growth = f"{round(rev_growth * 100, 2)}%"
        if margins != '未知': margins = f"{round(margins * 100, 2)}%"

    except Exception as e:
        print(f"⚠️ 抓取 {symbol} 財報失敗: {e}")
        return "⚠️ 財報數據連線異常，無法進行基本面掃雷。"

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        return "⚠️ 未設定 API KEY，無法啟動財報掃雷。"

    system_prompt = """
    你是一位極度嚴格、挑剔的華爾街財報分析師，現在為台灣老手「阿土伯」效力。
    你的任務是看著這家公司的「基本面數據」，用【一句話（嚴格限制 40 字以內）】挑出它最大的財務隱患或亮點。
    
    規則：
    1. 語氣要尖銳、一針見血（例如：「本益比高達30倍有泡沫風險」、「營收衰退但利潤率尚可」）。
    2. 如果數據看起來很健康，就直說「基本面健康，有業績支撐」。
    3. 絕對不要廢話，直接給出你的財務診斷結論！
    """
    user_prompt = f"股票：{stock_name}\n本益比(P/E): {pe}\n股價淨值比(P/B): {pb}\n股東權益報酬率(ROE): {roe}\n近期營收成長率: {rev_growth}\n淨利率: {margins}"

    try:
        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.3,
            "max_tokens": 100
        }
        res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=10)
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return "🤖 AI 財報解讀中斷，請手動確認風險。"

def get_best_ma_strategy(df):
    """【進化四】股性動態最佳化：回測找出這檔股票最適合的防守均線"""
    ma_list = ['ma5', 'ma10', 'ma20', 'ma60']
    best_ma = 'ma20'
    best_profit = -9999

    try:
        for ma in ma_list:
            if ma not in df.columns:
                continue
            
            # 💡 簡易回測邏輯：過去半年(約120天)，站上MA買進，跌破MA賣出的總報酬
            test_df = df.tail(120).copy()
            in_position = False
            entry_price = 0
            profit = 0
            
            for i in range(1, len(test_df)):
                prev_close = test_df['Close'].iloc[i-1]
                prev_ma = test_df[ma].iloc[i-1]
                curr_close = test_df['Close'].iloc[i]
                curr_ma = test_df[ma].iloc[i]
                
                # 突破均線 -> 買進
                if not in_position and prev_close < prev_ma and curr_close > curr_ma:
                    in_position = True
                    entry_price = curr_close
                # 跌破均線 -> 賣出
                elif in_position and prev_close > prev_ma and curr_close < curr_ma:
                    in_position = False
                    profit += (curr_close - entry_price) / entry_price
                    
            # 如果最後一天還在場內，把未實現也算進去
            if in_position and entry_price > 0:
                profit += (test_df['Close'].iloc[-1] - entry_price) / entry_price
                
            if profit > best_profit:
                best_profit = profit
                best_ma = ma
                
        # 把 ma10 轉換成 10MA 這種易讀格式
        return best_ma.replace('ma', '') + 'MA' 
    except Exception as e:
        print(f"⚠️ 回測均線失敗: {e}")
        return "20MA" # 如果算不出來，就退回傳統月線
        
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
        
# 計算各種均線
        df['ma5'] = df['Close'].rolling(window=5).mean()
        df['ma10'] = df['Close'].rolling(window=10).mean() # 👈 新增十日線給飆股用
        df['ma20'] = df['Close'].rolling(window=20).mean()
        df['ma60'] = df['Close'].rolling(window=60).mean()
        
        # 💡 阿土伯進化四：呼叫回測大腦，找出專屬均線！
        best_ma_name = get_best_ma_strategy(df)
        best_ma_col = 'ma' + best_ma_name.replace('MA', '') # 轉回 ma10 的格式去抓價格
        best_ma_price = round(df[best_ma_col].iloc[-1], 2) if not pd.isna(df[best_ma_col].iloc[-1]) else round(df['ma20'].iloc[-1], 2)
        
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
        
# ... 上面維持原本的邏輯 (包含算 RSI, ATR, 新聞掃雷等) ...

# 💡 阿土伯特調：啟動多空雙 AI 辯論室！
        print(f"⚖️ 正在請求多空 AI 辯論 {info['name']} 的技術面...")
        # 💡 阿土伯特調：把最後 5 天的連續資料 (DataFrame) 切出來餵給 AI
        recent_5d = df.tail(5)
        debate_result = get_ai_technical_brain(info["name"], recent_5d, rs_score)
        
        # 💡 阿土伯升級：調用財報照妖鏡 (基本面掃雷)
        funda_insight = get_fundamental_risk(symbol, info["name"])
        
# ... 前面是財報照妖鏡跟 AI 辯論 ...
        
dashboard_data.append({
            "symbol": symbol, "name": info["name"], "category": info["category"],
            "price": current_price, "rsi": round(df['rsi'].iloc[-1], 2), 
            "bias": round(((current_price - df['ma20'].iloc[-1]) / df['ma20'].iloc[-1]) * 100, 2) if df['ma20'].iloc[-1] else 0,
            "atr": round(df['atr'].iloc[-1], 2),
            "news_sentiment": news_sentiment_data,
            "vol_ratio": 1.2, "optimal_sl": int(best_sl*100), "actual_sl": int(actual_sl*100),
            "ev": actual_ev, "win_rate": actual_win, "history": hist, 
            "rs_score": rs_score, 
            "ai_debate": debate_result, 
            "funda_summary": funda_insight, 
            "best_ma_name": best_ma_name,       # 👈 塞入最強防守線名稱 (例如 "10MA")
            "best_ma_price": best_ma_price,     # 👈 塞入最強防守線的價格
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        })

        # 💡 阿土伯降溫機制：每算完一檔股票，強迫 Python 休息 3 秒，避免塞爆 Groq API 導致斷線！
        print(f"⏳ {info['name']} 運算完畢，冷卻 15 秒鐘...")
        time.sleep(15)

    # 迴圈結束後，底下是算 VIX 跟晨間劇本的地方 (維持不變)
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




















