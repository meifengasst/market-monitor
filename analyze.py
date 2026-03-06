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
    "2330.TW": {"name": "台積電", "category": "晶圓代工"}, "2337.TW": {"name": "旺宏", "category": "記憶體"},"3105.TW": {"name": "穩懋", "category": "半導體"},
    "0050.TW": {"name": "台灣50", "category": "台股龍頭"}, "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"}, "9910.TW": {"name": "豐泰", "category": "運動鞋"}, 
    "9904.TW": {"name": "寶成", "category": "運動鞋"}
}

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
            
        # 💡 阿土伯升級：美股/台股 雙引擎即時報價系統
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
        
        # 技術指標計算
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

        # 🚨 阿土伯 LINE 專屬風險管家 (停損觸發檢查) 🚨
        if symbol in cloud_portfolio:
            trade = cloud_portfolio[symbol]
            entry_price = trade.get('entryPrice', current_price)
            peak_price = trade.get('peakPrice', entry_price)

            # 1. 檢查是否創新高 (移動停利機制)
            if current_price > peak_price:
                trade['peakPrice'] = current_price
                portfolio_updated = True
                peak_price = current_price

            # 2. 計算這檔股票的嚴格停損/停利價
            actual_exit_price = max(entry_price * (1 - actual_sl), peak_price * (1 - actual_sl))

            # 3. 檢查是否跌破防線
            if current_price <= actual_exit_price:
                if not trade.get('alerted', False): # 如果還沒叫過，就馬上發 LINE！
                    
                    # 💡 阿土伯新增：動態判斷並生成「收緊原因」的文字
                    if is_bear:
                        reason_msg = f"\n⚠️ [大盤避險啟動]\n停損已由 {int(best_sl*100)}% 強制收緊至 3%！"
                    else:
                        reason_msg = f"\n(套用系統最佳停損 {int(best_sl*100)}%)"

                    alert_msg = f"🚨【阿土伯停損逃命警報】🚨\n\n股票：{info['name']} ({symbol})\n現價：${current_price}\n防線：${round(actual_exit_price, 2)}{reason_msg}\n\n⚡ 已跌破嚴格防線，請立即無情清倉，保護本金！"
                    
                    send_line_alert(alert_msg)
                    trade['alerted'] = True
                    portfolio_updated = True
            else:
                # 若股價爭氣站回防線之上，解除警報標記
                if trade.get('alerted', False):
                    trade['alerted'] = False
                    portfolio_updated = True

        hist = [{"date": i.strftime("%Y-%m-%d"), "price": round(r['Close'], 2), "volume": int(r['Volume']), "ma5": round(r['ma5'], 2), "ma20": round(r['ma20'], 2), "ma60": round(r['ma60'], 2), "macd": round(r['macd'], 2), "macd_signal": round(r['macd_signal'], 2), "macd_hist": round(r['macd_hist'], 2), "rsi": round(r['rsi'], 2), "bb_upper": round(r['bb_upper'], 2), "bb_lower": round(r['bb_lower'], 2)} for i, r in df.tail(60).iterrows()]
        
        rs_comment = f"【主力資金偏好】近期表現強於大盤 {rs_score}%！" if rs_score > 5 else (f"【溫吞股】近期表現落後大盤 {rs_score}%。" if rs_score < 0 else "與大盤同步。")
        
        dashboard_data.append({
            "symbol": symbol, "name": info["name"], "category": info["category"],
            "price": current_price, "rsi": round(df['rsi'].iloc[-1], 2), "bias": round(((current_price - df['ma20'].iloc[-1]) / df['ma20'].iloc[-1]) * 100, 2) if df['ma20'].iloc[-1] else 0,
            "vol_ratio": 1.2, "optimal_sl": int(best_sl*100), "actual_sl": int(actual_sl*100),
            "ev": actual_ev, "win_rate": actual_win, "history": hist, 
            "rs_score": rs_score, 
            "ai_summary": f"🎯 最佳移動停利/停損為 {int(best_sl*100)}%。{'目前大盤破線，已強制縮緊至 3% 防守！' if is_bear else '目前大盤穩定。'} {rs_comment}",
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        })

    # (這裡是你原本整理 dashboard_data.append 的地方)
        # ... 上面保持不變 ...

    # 💡 阿土伯新增：爬取 VIX 恐慌指數
    try:
        vix_price = round(yf.Ticker("^VIX").fast_info.get('lastPrice', 0), 2)
    except:
        vix_price = 0

    # 💡 阿土伯新增：計算自選股多空健康度 (% 數站上月線)
    above_20ma_count = sum(1 for d in dashboard_data if d['price'] > d['history'][-1]['ma20'])
    health_pct = int((above_20ma_count / len(dashboard_data)) * 100) if dashboard_data else 50

    market_health = {
        "vix": vix_price,
        "health_pct": health_pct
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



