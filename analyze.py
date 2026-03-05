import yfinance as yf
import pandas as pd
import json
from datetime import datetime
import numpy as np
import os
import requests

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

# --- 2. 期望值計算機 ---
def calculate_strategy_ev(ticker, start_date, end_date, stop_loss_pct):
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['Signal'] = 0
    df.loc[df['Close'] > df['SMA_20'], 'Signal'] = 1
    df.loc[df['Close'] < df['SMA_20'], 'Signal'] = -1

    trades = []
    entry_price = 0
    in_position = False

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
            entry_price = row['Close']
            in_position = True

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

# --- 3. 大盤環境偵測器 ---
def check_market_regime():
    print("🌍 正在偵測大盤多空環境 (0050.TW)...")
    df = yf.download("0050.TW", period="2mo", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    latest_close = df['Close'].iloc[-1]
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    
    if latest_close >= ma20:
        print("✅ 大盤站上月線，多頭環境")
        return 0.05
    else:
        alert_msg = f"⚠️【阿土伯戰報】\n大盤跌破月線！\n收盤 {latest_close:.2f} < 月線 {ma20:.2f}\n\n🚨 系統已啟動防禦模式，停損縮緊至 3%！"
        print(alert_msg)
        send_line_alert(alert_msg)
        return 0.03

# --- 4. 產生前端所需資料 ---
STOCKS = {
    "2330.TW": {"name": "台積電", "category": "晶圓代工"},
    "2303.TW": {"name": "聯電", "category": "晶圓代工"},
    "0050.TW": {"name": "元大台灣50", "category": "台股龍頭"},
    "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"},
    "9910.TW": {"name": "豐泰", "category": "運動鞋"},
    "9904.TW": {"name": "寶成", "category": "運動鞋"}
}

def generate_dashboard_data():
    print(f"🚀 阿土伯資料中心啟動 [{datetime.now().strftime('%H:%M:%S')}]")
    current_stop_loss = check_market_regime()
    dashboard_data = []
    backtest_start = "2021-01-01"
    today_str = datetime.now().strftime("%Y-%m-%d")

    for symbol, info in STOCKS.items():
        print(f"   ➤ 正在解析並計算技術指標: {info['name']} ({symbol})")
        
        # 抓取一年資料以利計算長天期均線與 MACD
        df = yf.download(symbol, period="1y", progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        # 取得即時報價
        ticker_obj = yf.Ticker(symbol)
        try:
            latest_price = round(ticker_obj.fast_info.get('lastPrice', df['Close'].iloc[-1]), 2)
            df.iloc[-1, df.columns.get_loc('Close')] = latest_price # 用即時價格更新最後一根 K 棒
        except:
            latest_price = round(df['Close'].iloc[-1], 2)
            
        # 💡 阿土伯修復：計算前端畫圖所需的技術指標
        df['ma5'] = df['Close'].rolling(window=5).mean()
        df['ma20'] = df['Close'].rolling(window=20).mean()
        df['ma60'] = df['Close'].rolling(window=60).mean()
        
        # 布林通道
        df['std'] = df['Close'].rolling(window=20).std()
        df['bb_upper'] = df['ma20'] + 2 * df['std']
        df['bb_lower'] = df['ma20'] - 2 * df['std']
        
        # MACD
        ema12 = df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        df = df.fillna(0) # 補齊空值
        
        # 💡 將最後 60 天的資料打包成前端線圖需要的 history 格式
        history_data = []
        for idx, row in df.tail(60).iterrows():
            history_data.append({
                "date": idx.strftime("%Y-%m-%d"),
                "price": round(row['Close'], 2),
                "volume": int(row['Volume']),
                "ma5": round(row['ma5'], 2),
                "ma20": round(row['ma20'], 2),
                "ma60": round(row['ma60'], 2),
                "macd": round(row['macd'], 2),
                "macd_signal": round(row['macd_signal'], 2),
                "macd_hist": round(row['macd_hist'], 2),
                "rsi": round(row['rsi'], 2),
                "bb_upper": round(row['bb_upper'], 2),
                "bb_lower": round(row['bb_lower'], 2)
            })

        # 計算卡片顯示數值
        latest_rsi = round(df['rsi'].iloc[-1], 2)
        ma20_val = round(df['ma20'].iloc[-1], 2)
        bias = round(((latest_price - ma20_val) / ma20_val) * 100, 2) if ma20_val != 0 else 0
        
        # 執行回測
        strategy_result = calculate_strategy_ev(symbol, backtest_start, today_str, stop_loss_pct=current_stop_loss)
        ev_val = strategy_result['ev'] if strategy_result else 0
        win_rate_val = strategy_result['win_rate'] if strategy_result else 0
        
        stock_obj = {
            "symbol": symbol,
            "name": info["name"],
            "category": info["category"],
            "price": latest_price,
            "rsi": latest_rsi,
            "bias": bias,
            "vol_ratio": 1.2, 
            "eps": "N/A",     
            "pe_ratio": "N/A",
            "ev": ev_val,             
            "win_rate": win_rate_val, 
            "history": history_data, # 🌟 關鍵修復：把歷史線圖數據交給前端！
            "ai_summary": f"大盤停損設為 {int(current_stop_loss*100)}%，策略期望值 {ev_val}%，勝率 {win_rate_val}%。",
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        }
        dashboard_data.append(stock_obj)

    final_output = {
        "last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"),
        "data": dashboard_data,
        "ptt": {"score": 50, "sentiment": "中立", "summary": "請結合你的 PTT 爬蟲"}, 
        "macro": {"tw_insight": f"大盤停損防護網啟動中，目前限制: {int(current_stop_loss*100)}%", "us_insight": "美股數據讀取中"}
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
    print("✅ data.json 更新完成！")

if __name__ == "__main__":
    generate_dashboard_data()
