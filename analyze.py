import yfinance as yf
import feedparser
import pandas as pd
from datetime import datetime, timedelta
import json
import numpy as np
import os
import requests
import xml.etree.ElementTree as ET
import re
import time
import urllib.parse

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"}

def send_telegram_alert(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    print(f"👉 [Telegram 發射台] 準備發送... Token: {'✅已連線' if token else '❌空的'}, Chat_ID: {'✅已連線' if chat_id else '❌空的'}")
    
    if not token or not chat_id:
        print("⚠️ 找不到 Telegram 金鑰，請去 GitHub Secrets 設定 TELEGRAM_BOT_TOKEN 與 TELEGRAM_CHAT_ID！")
        return
        
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        
        # 💡 阿土伯的黑科技：Telegram 快捷按鈕 (Inline Keyboard)
        reply_markup = {
            "inline_keyboard": [
                [
                    # 這裡放你的專屬戰情室網址
                    {"text": "📊 點我開啟戰情室", "url": "https://catdontbiteme.github.io/market-monitor/"}
                ]
            ]
        }
        
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            # TG 的 API 規定這個按鈕包裹必須轉成文字格式 (JSON String) 才能寄送
            "reply_markup": json.dumps(reply_markup) 
        }
        
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status() 
        print("✅ Telegram 逃命警報 (含直達按鈕) 成功發送至你的手機！")
    except Exception as e:
        print(f"⚠️ Telegram 警報發送失敗，原因: {e}")
        if 'res' in locals():
            print(f"⚠️ Telegram 官方回傳的錯誤細節: {res.text}")

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
    if triggered: send_telegram_alert(alert_msg)
    return regime

STOCKS = {
    "NVDA": {"name": "Nvidia", "category": "美國科技"}, "TSLA": {"name": "Tesla", "category": "美國科技"}, "SPY": {"name": "S&P 500", "category": "美股大盤"},
    "2330.TW": {"name": "台積電", "category": "晶圓代工"}, "2337.TW": {"name": "旺宏", "category": "記憶體"},"3105.TWO": {"name": "穩懋", "category": "半導體"},
    "0050.TW": {"name": "台灣50", "category": "台股龍頭"},"00981A.TW": {"name": "主動統一台股增長", "category": "台股"}, "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"}, "9910.TW": {"name": "豐泰", "category": "運動鞋"}, 
    "9904.TW": {"name": "寶成", "category": "運動鞋"}
}

# 把它加在 STOCKS 列表的下方
TOTAL_TOKENS_USED = 0

def get_ai_news_sentiment(stock_name, symbol):
    """【進化五：情報網升級】改用 Google News 抓取近15天內最多5則重大新聞"""
    print(f"📰 啟動精準雷達，改用 Google News 抓取 {stock_name} 近15日新聞...")
    try:
        search_keyword = f"{stock_name} 股票" if not symbol.endswith(".TW") else stock_name
        
        # 💡 URL 編碼，確保 Google 看得懂
        query = urllib.parse.quote(f"{search_keyword} when:15d")
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        
        # 💡 披上隱形斗篷！用 requests 帶上 HEADERS 去抓
        res = requests.get(rss_url, headers=HEADERS, timeout=10)
        feed = feedparser.parse(res.text)
        
        top_news = []
        
        # 💡 乾淨俐落的 Google News 迴圈
        for entry in feed.entries[:5]:
            if hasattr(entry, 'published_parsed'):
                pub_time_str = time.strftime("%Y-%m-%d", entry.published_parsed)
            else:
                pub_time_str = datetime.now().strftime("%Y-%m-%d")
                
            clean_title = entry.title.rsplit(" - ", 1)[0]
                
            top_news.append({
                "title": clean_title,
                "link": entry.link,
                "date": pub_time_str
            })
            
        if not top_news:
            return [{"title": "近半個月內無重大新聞，主力可能在休假😴", "sentiment": "中立", "link": "#", "date": datetime.now().strftime("%Y-%m-%d")}]

        # 組裝給 AI 看的新聞報紙
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
        """
        user_prompt = f"股票：{stock_name}\n近期新聞：\n{news_text}"

        headers = {"Authorization": f"Bearer {groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.3,
            "max_tokens": 800
        }
        res_ai = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        res_ai.raise_for_status()
        
        ai_text = res_ai.json()["choices"][0]["message"]["content"].strip()
        ai_text = re.sub(r'```json|```', '', ai_text).strip()
        
        # 💡 強制過濾器：只抓 JSON
        match = re.search(r'\[.*\]', ai_text, re.DOTALL)
        if match:
            parsed_data = json.loads(match.group(0))
        else:
            raise ValueError("AI 回傳格式錯誤")
        
        # 把 AI 翻譯好的標題跟原本的連結、日期合併起來
        final_result = []
        for i, item in enumerate(parsed_data):
            if i < len(top_news): 
                final_result.append({
                    "title": item.get("title", top_news[i]["title"]),
                    "sentiment": item.get("sentiment", "中立"),
                    "link": top_news[i]["link"],
                    "date": top_news[i]["date"] 
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

# 💡 阿土伯黑科技 2：板塊輪動雷達 (追蹤聰明錢流向)
def get_sector_rotation():
    print("🧭 啟動板塊輪動雷達 (追蹤聰明錢)...")
    # 設定觀測名單：科技攻擊 vs 金融/高息防禦
    sectors = {
        "XLK": {"name": "🇺🇸美股科技", "bm": "SPY"},
        "XLF": {"name": "🇺🇸美股金融", "bm": "SPY"},
        "00881.TW": {"name": "🇹🇼台股科技", "bm": "0050.TW"},
        "00878.TW": {"name": "🇹🇼台股高息", "bm": "0050.TW"}
    }
    results = []
    for sym, info in sectors.items():
        try:
            # 抓取近一個月歷史
            stock_df = yf.Ticker(sym).history(period="1mo")
            bm_df = yf.Ticker(info["bm"]).history(period="1mo")
            if len(stock_df) >= 20 and len(bm_df) >= 20:
                # 計算近 20 日報酬率
                stock_ret = (stock_df['Close'].iloc[-1] - stock_df['Close'].iloc[-20]) / stock_df['Close'].iloc[-20]
                bm_ret = (bm_df['Close'].iloc[-1] - bm_df['Close'].iloc[-20]) / bm_df['Close'].iloc[-20]
                # 算出相對大盤的強弱度 (RS)
                rs = (stock_ret - bm_ret) * 100
                results.append({"name": info["name"], "rs": round(rs, 2)})
        except Exception as e:
            print(f"⚠️ 板塊 {sym} 掃描失敗: {e}")
    
    # 依照強弱度由大到小排序
    results.sort(key=lambda x: x['rs'], reverse=True)
    return results

# 💡 注意參數多了一個 poc_price
# 💡 參數新增了 smart_money
def get_unified_o3_brain(stock_name, current_price, ma20, rsi, atr, poc_price, recent_df, rs_score, news_data, funda_insight, smart_money):
    print(f"🧠 [o3-mini 大合體] 啟動全白話文戰情分析 (含POC籌碼視角)：{stock_name}...")
    
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        return {"pattern": "未連線", "bull": "API未設定", "bear": "API未設定", "trap": "無法掃描", "stop_price": 0, "sizing": "未知", "action": "無法判斷"}

    trend_str = "\n".join([f"{r.name.strftime('%m/%d')} - 收:{r['Close']:.2f} | 量:{int(r['Volume'])}" for _, r in recent_df.iterrows()])
    news_str = "\n".join([f"- [{n['sentiment']}] {n['title']}" for n in news_data]) if news_data else "無重大新聞"
    
    ma_status = "【已站上 20MA，趨勢偏多】" if current_price > ma20 else "【已跌破 20MA，趨勢偏空】"

    system_prompt = """
    你現在是台灣股市老手「阿土伯」的首席量化風控長。你需要綜合【技術面】、【籌碼密集區(POC)】、【基本面】、【新聞】給出唯一裁決。
    
    【極度重要：必須說白話文】
    請用台灣股民最熟悉的「白話文」撰寫！
    - 不要說「MACD頂背離」，要說「漲不動了，動能衰退」。
    - 語氣要接地氣、直接、冷酷。

    【籌碼密集區 (POC) 判斷密技】：
    - POC 代表過去半年市場最大的「主力成本區」。
    - 如果現價遠高於 POC：代表「主力已經拉開成本，獲利滿滿，隨時可能倒貨」。
    - 如果現價剛好在 POC 附近：代表「有鐵板支撐，適合建倉防守」。
    - 如果現價跌破 POC：代表「連主力都被套牢，上方壓力極大，快逃」。
    請務必將 POC 的觀察寫進你的 bull, bear 或 trap 分析中！

    【輸出格式要求】：純 JSON 格式，嚴格遵守以下 Key 與字數：
    {
        "pattern": "目前的狀態 (例如: 強勢突破 / 跌破月線轉弱，限10字)",
        "bull": "多方好消息 (白話文，限25字)",
        "bear": "空方壞消息 (白話文，限25字)",
        "trap": "騙線警告 (包含POC籌碼判斷，例如：現價乖離POC太遠，小心主力倒貨，限30字)",
        "stop_price": 數字 (用現價與 ATR 算出的合理防守價，精確到小數點後兩位),
        "sizing": "資金建議 (例如: 波動大，買一半就好 / 安全，正常買，限20字)",
        "action": "最終指令 (限選一個：抱牢續賺 / 縮注試單 / 嚴格觀望 / 破線快逃)"
    }
    """

    user_prompt = f"""
    股票：{stock_name}
    大盤強弱：相對大盤 {rs_score}%
    事實：{ma_status}
    現價：{current_price}
    近半年籌碼密集區(POC)：{poc_price} 
    均線與波動：20MA {ma20}，RSI {rsi}，ATR {atr}
    近5日量價：\n{trend_str}
    財報：{funda_insight}
    大戶與內部人動向：{smart_money}
    新聞：\n{news_str}
    """

    try:
        headers = {"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "o3-mini",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "response_format": {"type": "json_object"}
        }
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        
        response_data = res.json()
        
        # 💡 阿土伯記帳法：把這次消耗的 Token 抓出來加總
        global TOTAL_TOKENS_USED
        usage = response_data.get("usage", {})
        TOTAL_TOKENS_USED += usage.get("total_tokens", 0)

        ai_text = response_data["choices"][0]["message"]["content"].strip()
        
        start_idx, end_idx = ai_text.find('{'), ai_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            return json.loads(ai_text[start_idx:end_idx+1])
        else:
            return {"pattern": "格式錯誤", "bull": "解析失敗", "bear": "解析失敗", "trap": "解析失敗", "stop_price": current_price*0.95, "sizing": "防禦狀態", "action": "觀望"}
    except Exception as e:
        return {"pattern": "連線異常", "bull": "API中斷", "bear": "API中斷", "trap": "API中斷", "stop_price": current_price*0.95, "sizing": "防禦狀態", "action": "觀望"}

# 💡 新增 sector_data 參數
def generate_morning_script_o3(market_data, sector_data):
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        return "⚠️ 未設定 OPENAI_API_KEY，無法產生晨間劇本。"

    data_str = ", ".join([f"{k}: 變化 {v['pct']}%" for k, v in market_data.items()])
    # 把板塊流向轉成文字給 AI 看
    sector_str = ", ".join([f"{s['name']}(動能 {s['rs']}%)" for s in sector_data]) if sector_data else "無資料"
    
    system_prompt = """
    你現在是台灣股市老手「阿土伯」，極度重視風險控制與資金輪動。
    你的任務是根據【昨夜美股數據】與【板塊資金流向(動能>0代表資金流入，<0代表流出)】，給出今日台股開盤的行動指南。
    
    規則：
    1. 語氣要果斷、嚴厲、接地氣（可使用「接刀」、「避風港」、「抱牢」等詞）。
    2. 必須給出「今日資金曝險上限建議（例如 20% 或 50%）」。
    3. 如果科技板塊動能為負，高息/金融為正，必須警告「資金正在撤出科技股，轉往防禦板塊」。
    4. 字數嚴格限制在 80 字以內，直接給指令！
    """
    user_prompt = f"昨夜美股：{data_str}。\n資金流向：{sector_str}。\n請阿土伯下達操作鐵律！"

    try:
        print("🧠 呼叫 o3-mini 撰寫晨間戰報 (結合資金輪動)...")
        headers = {"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": "o3-mini", 
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        }
        
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        
        response_data = res.json()
        
        # 💡 阿土伯記帳法：把這次消耗的 Token 抓出來加總
        global TOTAL_TOKENS_USED
        usage = response_data.get("usage", {})
        TOTAL_TOKENS_USED += usage.get("total_tokens", 0)

        ai_text = response_data["choices"][0]["message"]["content"].strip()
        return res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return "🤖 AI 戰情室連線異常，請縮小部位觀望。"
        
# 💡 阿土伯黑科技 3：華爾街暗池與內部人籌碼照妖鏡
def get_smart_money_flow(symbol):
    print(f"🕵️‍♂️ 啟動大戶照妖鏡，掃描 {symbol} 內部人與暗池動向...")
    fmp_key = os.environ.get("FMP_API_KEY")
    
    # 台股目前比較難透過 FMP 抓內部人，先跳過或給預設值
    if symbol.endswith(".TW") or not fmp_key:
        return "無明顯大戶異常動向"

    try:
        # 呼叫 FMP 內部人交易 API (抓取最新 10 筆)
        url = f"https://financialmodelingprep.com/api/v4/insider-trading?symbol={symbol}&limit=10&apikey={fmp_key}"
        res = requests.get(url, timeout=5)
        
        # 判斷是否為付費權限被擋，或無資料
        if res.status_code != 200 or not res.json():
            return "無明顯大戶異常動向"
            
        data = res.json()
        buy_amount = 0
        sell_amount = 0
        
        for trade in data:
            # 判斷是買進 (P-Purchase) 還是賣出 (S-Sale)
            # 有些 API 用 Acquired / Disposed
            acq_disp = trade.get('acquistionOrDisposition', '')
            shares = trade.get('securitiesTransacted', 0)
            price = trade.get('price', 0)
            
            if shares and price:
                value = shares * price
                if acq_disp == 'A': # Acquired (買進)
                    buy_amount += value
                elif acq_disp == 'D': # Disposed (賣出)
                    sell_amount += value
                    
        # 計算淨流向
        net_flow = buy_amount - sell_amount
        
        if net_flow > 1000000: # 淨買超大於 100 萬美金
            return f"🔥【內部大戶狂買】高管近期淨買入約 ${round(buy_amount/1000000, 2)}M 美金！"
        elif net_flow < -1000000: # 淨賣超大於 100 萬美金
            return f"🚨【高管偷倒貨】高管近期淨賣出約 ${round(sell_amount/1000000, 2)}M 美金，小心拉高出貨！"
        else:
            return "內部人大戶近期無明顯大動作。"
            
    except Exception as e:
        print(f"⚠️ 大戶照妖鏡掃描失敗: {e}")
        return "大戶動向偵測失敗"
# 💡 阿土伯黑科技 4：恐慌大屠殺生還者雷達 (Bloodbath Survivors)
def scan_bloodbath_survivors(vix_current, vix_threshold=40):
    print(f"🩸 [恐慌雷達] 目前 VIX: {vix_current}，觸發門檻: {vix_threshold}")
    
    # 沒到恐慌極點，我們把刀收起來，繼續泡茶
    if vix_current < vix_threshold:
        print("🟢 市場還沒到極度恐慌，阿土伯不出手。")
        return []

    print("🚨🚨 VIX 破表！大屠殺開始，阿土伯戴上鋼盔準備撿屍！🚨🚨")

    # 阿土伯的「優質好骨骼」觀測名單 (可自行擴充)
    # 建議放：金融股、老牌傳產、大型電子權值股、高息ETF
    hunting_list = [
        "2886.TW", "2884.TW", "2891.TW", "2892.TW", # 兆豐、玉山、中信、第一
        "1101.TW", "1102.TW", "2002.TW", "1301.TW", # 台泥、亞泥、中鋼、台塑
        "2308.TW", "2382.TW", "3231.TW", "2356.TW", # 台達電、廣達、緯創、英業達
        "0056.TW", "00878.TW", "00713.TW"           # 防禦型 ETF
    ]
    
    survivors = []

    for symbol in hunting_list:
        try:
            # 1. 抓取基本面 (PBR 與 殖利率)
            info = yf.Ticker(symbol).info
            
            pbr = info.get('priceToBook', 999) # 抓不到就給 999 讓他過濾掉
            yield_pct = info.get('dividendYield', 0)
            
            # 將殖利率轉成百分比格式
            yield_pct = (yield_pct * 100) if yield_pct else 0

            # 【條件 3 & 4】：股價淨值比 < 1.2 且 殖利率 >= 8%
            if pbr >= 1.2 or yield_pct < 8:
                continue # 基本面沒過，直接換下一檔，省去抓歷史股價的時間

            # 2. 抓取「月線」歷史資料算 KD (需要至少 5 年資料來跑月線)
            df_month = yf.download(symbol, period="5y", interval="1mo", progress=False)
            if df_month.empty or len(df_month) < 14:
                continue

            # 處理 yfinance 多重索引問題
            if isinstance(df_month.columns, pd.MultiIndex):
                df_month.columns = df_month.columns.droplevel(1)

            # 3. 計算月 KD (參數 9, 3, 3)
            # RSV = (今日收盤價 - 最近9個月最低價) / (最近9個月最高價 - 最近9個月最低價) * 100
            df_month['RSV'] = 100 * (df_month['Close'] - df_month['Low'].rolling(9).min()) / (df_month['High'].rolling(9).max() - df_month['Low'].rolling(9).min())
            
            # K = 2/3 * (昨日K值) + 1/3 * (今日RSV) -> Pandas 裡用 ewm(com=2) 替代
            df_month['K'] = df_month['RSV'].ewm(com=2, adjust=False).mean()
            df_month['D'] = df_month['K'].ewm(com=2, adjust=False).mean()

            last_k = df_month['K'].iloc[-1]
            last_d = df_month['D'].iloc[-1]

            # 【條件 2】：月 K < 30 且 月 D < 30 (低檔鈍化或打底)
            if last_k < 30 and last_d < 30:
                stock_name = info.get('shortName', symbol)
                current_price = round(df_month['Close'].iloc[-1], 2)
                
                print(f"🎯 逮到獵物！{stock_name} ({symbol}) 通過阿土伯四重考驗！")
                
                survivors.append({
                    "symbol": symbol,
                    "name": stock_name,
                    "price": current_price,
                    "pbr": round(pbr, 2),
                    "yield": round(yield_pct, 2),
                    "month_k": round(last_k, 2),
                    "month_d": round(last_d, 2)
                })

        except Exception as e:
            print(f"⚠️ 掃描 {symbol} 失敗: {e}")
            
    return survivors
# 💡 在你設定環境變數的地方加入 FMP_API_KEY
# FMP_API_KEY = os.environ.get("FMP_API_KEY")
def get_fundamental_risk_o3(symbol, stock_name):
    print(f"🔎 [o3-mini 財報掃雷] 正在調閱 {stock_name} 的財務報表...")
    # 阿土伯預設變數
    pe = pb = roe = rev_growth = margins = '未知'
    
    fmp_key = os.environ.get("FMP_API_KEY")
    
    # 🌟 美股走專用高速公路 (FMP API)
    if not symbol.endswith(".TW") and fmp_key:
        try:
            # 呼叫 FMP 的關鍵指標 API
            metrics_url = f"https://financialmodelingprep.com/api/v3/key-metrics/{symbol}?apikey={fmp_key}"
            res = requests.get(metrics_url, timeout=5).json()
            if len(res) > 0:
                pe = round(res[0].get('peRatio', 0), 2)
                pb = round(res[0].get('pbRatio', 0), 2)
                roe = f"{round(res[0].get('roe', 0) * 100, 2)}%"
                
            # 呼叫 FMP 的財務成長 API
            growth_url = f"https://financialmodelingprep.com/api/v3/financial-growth/{symbol}?apikey={fmp_key}"
            res_growth = requests.get(growth_url, timeout=5).json()
            if len(res_growth) > 0:
                rev_growth = f"{round(res_growth[0].get('revenueGrowth', 0) * 100, 2)}%"
                
            margins = "請參考ROE" # 簡化傳遞
            print(f"✅ 成功透過 FMP 獲取 {stock_name} 財報！")
        except Exception as e:
            print(f"⚠️ FMP 抓取失敗，準備退回 Yahoo: {e}")
            
    # 🌟 台股或 FMP 失敗時，退回原本的 yfinance 備用路線
    if pe == '未知' or pe == 0:
        try:
            info = yf.Ticker(symbol).info
            pe = info.get('trailingPE', '未知')
            pb = info.get('priceToBook', '未知')
            roe_val = info.get('returnOnEquity', '未知')
            roe = f"{round(roe_val * 100, 2)}%" if roe_val != '未知' else '未知'
            rg_val = info.get('revenueGrowth', '未知')
            rev_growth = f"{round(rg_val * 100, 2)}%" if rg_val != '未知' else '未知'
            m_val = info.get('profitMargins', '未知')
            margins = f"{round(m_val * 100, 2)}%" if m_val != '未知' else '未知'
        except:
            pass

    # ... 下面繼續接你原本呼叫 o3-mini 判讀財報的程式碼 ...
    # (system_prompt, user_prompt, requests.post... 保留原樣)
    try:
        info = yf.Ticker(symbol).info
        pe = info.get('trailingPE', '未知')
        pb = info.get('priceToBook', '未知')
        roe = info.get('returnOnEquity', '未知')
        rev_growth = info.get('revenueGrowth', '未知')
        margins = info.get('profitMargins', '未知')

        if pe == '未知' and roe == '未知':
            return "⚠️ 財報數據連線異常，請手動查閱公開資訊觀測站。"

        if roe != '未知': roe = f"{round(roe * 100, 2)}%"
        if rev_growth != '未知': rev_growth = f"{round(rev_growth * 100, 2)}%"
        if margins != '未知': margins = f"{round(margins * 100, 2)}%"

    except Exception as e:
        print(f"⚠️ 抓取 {symbol} 財報失敗: {e}")
        return "⚠️ 財報數據連線異常，無法進行基本面掃雷。"

    # 💡 換上我們剛設定好的 OpenAI 金鑰
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        return "⚠️ 未設定 OPENAI_API_KEY，無法啟動財報掃雷。"

    system_prompt = """
    你是一位極度嚴格、挑剔的華爾街財報分析師，現在為台灣老手「阿土伯」效力。
    你的任務是看著這家公司的「基本面數據」，用【一句話（嚴格限制 40 字以內）】挑出它最大的財務隱患或亮點。
    請直接給出致命的點評，不要講廢話。
    """
    user_prompt = f"股票：{stock_name}\n本益比(P/E): {pe}\n股價淨值比(P/B): {pb}\n股東權益報酬率(ROE): {roe}\n近期營收成長率: {rev_growth}\n淨利率: {margins}"

    try:
        headers = {
            "Authorization": f"Bearer {openai_api_key}", 
            "Content-Type": "application/json"
        }
        payload = {
            "model": "o3-mini",
            "messages": [
                {"role": "system", "content": system_prompt}, 
                {"role": "user", "content": user_prompt}
            ]
            # 💡 o3-mini 同樣不需要設定 temperature
        }
        
        # 思考財報需要一點時間，timeout 設 20 秒
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        
        response_data = res.json()
        
        # 💡 阿土伯記帳法：把這次消耗的 Token 抓出來加總
        global TOTAL_TOKENS_USED
        usage = response_data.get("usage", {})
        TOTAL_TOKENS_USED += usage.get("total_tokens", 0)

        ai_text = response_data["choices"][0]["message"]["content"].strip()
        
        return res.json()["choices"][0]["message"]["content"].strip()
        
    except Exception as e:
        print(f"⚠️ o3-mini 財報解讀中斷: {e}")
        return "🤖 AI 財報解讀中斷，請手動確認風險。"
# 💡 阿土伯黑科技：計算近半年最大籌碼密集區 (POC)
def calculate_poc(df, days=120, bins=20):
    try:
        # 取近半年的資料來算籌碼
        recent_df = df.tail(days).copy()
        if len(recent_df) < 20: 
            return round(df['Close'].iloc[-1], 2)
        
        # 把價格切成 20 個抽屜 (bins)
        recent_df['Price_Bin'] = pd.cut(recent_df['Close'], bins=bins)
        
        # 計算每個抽屜裡累積了多少成交量
        volume_by_price = recent_df.groupby('Price_Bin', observed=False)['Volume'].sum()
        
        # 找出裝最多成交量的那個抽屜
        poc_bin = volume_by_price.idxmax()
        
        # 取這個抽屜的中間價，當作主力成本區 (POC)
        poc_price = poc_bin.mid
        return round(float(poc_price), 2)
    except Exception as e:
        print(f"⚠️ POC 計算失敗: {e}")
        return round(df['Close'].iloc[-1], 2)
        
def get_best_ma_strategy(df):
    ma_list = ['ma5', 'ma10', 'ma20', 'ma60']
    best_ma = 'ma20'
    best_profit = -9999

    try:
        for ma in ma_list:
            if ma not in df.columns: continue
            
            test_df = df.tail(120).copy()
            in_position = False
            entry_price, profit = 0, 0
            
            for i in range(1, len(test_df)):
                prev_close = test_df['Close'].iloc[i-1]
                prev_ma = test_df[ma].iloc[i-1]
                curr_close = test_df['Close'].iloc[i]
                curr_ma = test_df[ma].iloc[i]
                
                if not in_position and prev_close < prev_ma and curr_close > curr_ma:
                    in_position, entry_price = True, curr_close
                elif in_position and prev_close > prev_ma and curr_close < curr_ma:
                    in_position = False
                    profit += (curr_close - entry_price) / entry_price
                    
            if in_position and entry_price > 0:
                profit += (test_df['Close'].iloc[-1] - entry_price) / entry_price
                
            if profit > best_profit:
                best_profit, best_ma = profit, ma
                
        return best_ma.replace('ma', '') + 'MA' 
    except Exception as e:
        print(f"⚠️ 回測均線失敗: {e}")
        return "20MA"

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
        
        try:
            df = yf.download(symbol, start="2021-01-01", progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
                
            if not symbol.endswith(".TW"):
                finnhub_key = os.environ.get("FINNHUB_API_KEY")
                if finnhub_key:
                    try:
                        res = requests.get(f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={finnhub_key}", timeout=5)
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
            
            df['ma5'] = df['Close'].rolling(window=5).mean()
            df['ma10'] = df['Close'].rolling(window=10).mean()
            df['ma20'] = df['Close'].rolling(window=20).mean()
            df['ma60'] = df['Close'].rolling(window=60).mean()
            
            best_ma_name = get_best_ma_strategy(df)
            best_ma_col = 'ma' + best_ma_name.replace('MA', '') 
            best_ma_price = round(df[best_ma_col].iloc[-1], 2) if not pd.isna(df[best_ma_col].iloc[-1]) else round(df['ma20'].iloc[-1], 2)
            
            df['std'] = df['Close'].rolling(20).std()
            df['bb_upper'], df['bb_lower'] = df['ma20'] + 2 * df['std'], df['ma20'] - 2 * df['std']
            df['macd'] = df['Close'].ewm(span=12).mean() - df['Close'].ewm(span=26).mean()
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']
            delta = df['Close'].diff()
            df['rsi'] = 100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / -delta.where(delta < 0, 0).rolling(14).mean())))
            
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
            
            # --- 雲端帳務與停損警報 ---
            if symbol in cloud_portfolio:
                trade = cloud_portfolio[symbol]
                entry_price = trade.get('entryPrice', current_price)
                peak_price = trade.get('peakPrice', entry_price)
                custom_sl_price = trade.get('customSL')

                if current_price > peak_price:
                    trade['peakPrice'] = current_price
                    portfolio_updated = True
                    peak_price = current_price

                if custom_sl_price:
                    actual_exit_price = float(custom_sl_price)
                    reason_msg = f"\n(觸發自訂嚴格停損防線)"
                else:
                    actual_exit_price = max(entry_price * (1 - actual_sl), peak_price * (1 - actual_sl))
                    if is_bear:
                        reason_msg = f"\n⚠️ [大盤避險啟動]\n停損已強制收緊至 3%！"
                    else:
                        reason_msg = f"\n(觸發移動停利網 {int(best_sl*100)}%)"

                if current_price <= actual_exit_price:
                    if not trade.get('alerted', False):
                        alert_msg = f"🚨【阿土伯停損逃命警報】🚨\n\n股票：{info['name']} ({symbol})\n現價：${current_price}\n防線：${round(actual_exit_price, 2)}{reason_msg}\n\n⚡ 已跌破嚴格防線，請立即無情清倉，保護本金！"
                        send_telegram_alert(alert_msg)
                        trade['alerted'] = True
                        portfolio_updated = True
                else:
                    if trade.get('alerted', False):
                        trade['alerted'] = False
                        portfolio_updated = True


            # --- 🔥 阿土伯的戰情便當生產線開始 ---
            news_sentiment_data = get_ai_news_sentiment(symbol, info["name"])
            time.sleep(2) 

            funda_insight = get_fundamental_risk_o3(symbol, info["name"])
            time.sleep(2) 
            
            # 💡 1. 呼叫大戶照妖鏡
            smart_money_insight = get_smart_money_flow(symbol)
            time.sleep(1)

            recent_5d = df.tail(5)
            poc_price = calculate_poc(df, days=120, bins=20)
            
            # 💡 2. 把 smart_money_insight 傳給大腦
            unified_brain = get_unified_o3_brain(
                stock_name=info["name"],
                current_price=current_price,
                ma20=round(df['ma20'].iloc[-1], 2),
                rsi=round(df['rsi'].iloc[-1], 2),
                atr=round(df['atr'].iloc[-1], 2),
                poc_price=poc_price,
                recent_df=recent_5d,
                rs_score=rs_score,
                news_data=news_sentiment_data,
                funda_insight=funda_insight,
                smart_money=smart_money_insight   # 👈 傳遞進去！
            )
            


            # 動態停損價改從 unified_brain 拿
            dynamic_stop_price = unified_brain.get('stop_price', current_price * 0.95)

            # 準備畫圖用的歷史資料
            hist = [{"date": i.strftime("%Y-%m-%d"), "price": round(r['Close'], 2), "volume": int(r['Volume']), "ma5": round(r['ma5'], 2), "ma20": round(r['ma20'], 2), "ma60": round(r['ma60'], 2), "macd": round(r['macd'], 2), "macd_signal": round(r['macd_signal'], 2), "macd_hist": round(r['macd_hist'], 2), "rsi": round(r['rsi'], 2), "bb_upper": round(r['bb_upper'], 2), "bb_lower": round(r['bb_lower'], 2), "atr": round(r['atr'], 2)} for i, r in df.tail(60).iterrows()]
            
            avg_vol_20 = df['Volume'].rolling(20).mean().iloc[-1]
            current_vol = df['Volume'].iloc[-1]
            real_vol_ratio = round(float(current_vol / avg_vol_20), 2) if avg_vol_20 > 0 else 1.0

            dashboard_data.append({
                "symbol": symbol, "name": info["name"], "category": info["category"],
                "price": current_price, "rsi": round(df['rsi'].iloc[-1], 2), 
                "bias": round(((current_price - df['ma20'].iloc[-1]) / df['ma20'].iloc[-1]) * 100, 2) if df['ma20'].iloc[-1] else 0,
                "atr": round(df['atr'].iloc[-1], 2),
                "poc_price": poc_price,
                "news_sentiment": news_sentiment_data,
                "vol_ratio": real_vol_ratio, 
                "optimal_sl": int(best_sl*100), "actual_sl": int(actual_sl*100),
                "ev": actual_ev, "win_rate": actual_win, "history": hist, 
                "rs_score": rs_score,
                "unified_brain": unified_brain,  # 👈 打包新的大腦裁決
                "funda_summary": funda_insight, 
                "best_ma_name": best_ma_name,        
                "best_ma_price": best_ma_price,      
                "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
            })

        except Exception as e:
            print(f"⚠️ 處理 {symbol} 時發生錯誤: {e}")
            
        print(f"⏳ {info['name']} 運算完畢，冷卻 15 秒鐘...")
        time.sleep(15)

    print("📊 準備結算並產出 JSON 報表...")
    us_market_data = get_us_market_summary()
    # 取出 VIX 恐慌指數，如果沒抓到預設為 0
    current_vix = us_market_data.get("恐慌指數", {}).get("price", 0) if isinstance(us_market_data, dict) else 0
    
    # 🚀 啟動阿土伯的恐慌雷達 (為了平常可以測試，你可以先把 vix_threshold 設成 15 或 20 跑跑看)
    survivors_list = scan_bloodbath_survivors(current_vix, vix_threshold=40)
    
    if survivors_list:
        alert_msg = "🚨【阿土伯血拚警報】大屠殺生還者出列！🚨\n\n市場極度恐慌，但以下標的已跌出『黃金價值』：\n"
        for s in survivors_list:
            alert_msg += f"\n💰 {s['name']} ({s['symbol']})\n現價: ${s['price']} | 殖利率: {s['yield']}%\n淨值比: {s['pbr']} | 月K: {s['month_k']}"
        alert_msg += "\n\n請留意資金控管，分批建倉！"
        
        # 呼叫你原本寫好的 TG 警報器發送到手機
        send_telegram_alert(alert_msg)
    # 💡 1. 呼叫雷達
    sector_data = get_sector_rotation()
    morning_script = generate_morning_script_o3(us_market_data, sector_data)

    above_20ma_count = sum(1 for d in dashboard_data if d['price'] > d['history'][-1]['ma20'])
    health_pct = int((above_20ma_count / len(dashboard_data)) * 100) if dashboard_data else 50

    market_health = {
        "vix": us_market_data.get("恐慌指數", {}).get("price", 0) if isinstance(us_market_data, dict) else 0,
        "health_pct": health_pct,
        "us_summary": us_market_data,
        "sector_data": sector_data,
        "ai_script": morning_script        
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({
            "last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"), 
            "data": dashboard_data, 
            "market_health": market_health,
            "macro": {"tw_insight": "⚠️ 0050破線避險" if bear_markets["TW"] else "✅ 0050多頭穩定", "us_insight": "⚠️ SPY破線避險" if bear_markets["US"] else "✅ SPY多頭穩定"},
            "token_usage": TOTAL_TOKENS_USED # 👈 把總消耗量傳給前端！
        }, f, ensure_ascii=False, indent=4)

    if portfolio_updated:
        with open(portfolio_file, "w", encoding="utf-8") as f:
            json.dump(cloud_portfolio, f, ensure_ascii=False, indent=4)

if __name__ == "__main__": 
    generate_dashboard_data()


