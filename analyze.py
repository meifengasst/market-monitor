import yfinance as yf
import pandas as pd
import json
from datetime import datetime
import numpy as np

# --- 1. 放入我們剛剛寫的期望值計算機 ---
def calculate_strategy_ev(ticker, start_date, end_date, stop_loss_pct=0.05):
    """5% 強制停損的期望值計算機"""
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

    return {
        "ev": round(ev * 100, 2),        # 轉成百分比
        "win_rate": round(p_win * 100, 2) # 轉成百分比
    }

# --- 2. 定義你的觀察名單 (以台積電、聯電為例) ---
STOCKS = {
    "2330.TW": {"name": "台積電", "category": "晶圓代工"},
    "2303.TW": {"name": "聯電", "category": "晶圓代工"},
    "0050.TW": {"name": "元大台灣50", "category": "台股龍頭"}
}

# --- 3. 產生 JSON 資料的主程式 ---
def generate_dashboard_data():
    print("🚀 阿土伯資料中心啟動：開始結算各檔股票期望值與最新數據...")
    
    dashboard_data = []
    # 設定回測區間 (例如近 5 年來驗證期望值)
    backtest_start = "2021-01-01"
    today_str = datetime.now().strftime("%Y-%m-%d")

    for symbol, info in STOCKS.items():
        print(f"   ➤ 正在處理: {info['name']} ({symbol})")
        
        # A. 取得最新報價與均線 (抓近半年算均線即可)
        df = yf.download(symbol, period="6mo", progress=False)
        if df.empty: continue
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        latest_price = round(df['Close'].iloc[-1], 2)
        ma5 = round(df['Close'].rolling(window=5).mean().iloc[-1], 2)
        ma20 = round(df['Close'].rolling(window=20).mean().iloc[-1], 2)
        ma60 = round(df['Close'].rolling(window=60).mean().iloc[-1], 2)
        
        # 計算簡單的 RSI (熱度) 與 乖離率 (Bias)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = round(100 - (100 / (1 + rs)).iloc[-1], 2)
        bias = round(((latest_price - ma20) / ma20) * 100, 2)
        
        # B. 呼叫「期望值計算機」跑歷史回測！
        strategy_result = calculate_strategy_ev(symbol, backtest_start, today_str, stop_loss_pct=0.05)
        
        # 如果回測成功，就取數值；如果失敗就給預設值
        ev_val = strategy_result['ev'] if strategy_result else 0
        win_rate_val = strategy_result['win_rate'] if strategy_result else 0
        
        # C. 整理成前端需要的格式
        stock_obj = {
            "symbol": symbol,
            "name": info["name"],
            "category": info["category"],
            "price": latest_price,
            "rsi": rsi if not np.isnan(rsi) else 50,
            "bias": bias if not np.isnan(bias) else 0,
            "vol_ratio": 1.2, # 這裡可以自己加入真實的量能計算
            "eps": "N/A",     # 基本面資料可透過 yf.Ticker(symbol).info 取得
            "pe_ratio": "N/A",
            "ev": ev_val,             # 🌟 亮點：剛算出來的期望值！
            "win_rate": win_rate_val, # 🌟 亮點：剛算出來的勝率！
            "ai_summary": f"阿土伯分析：目前歷史策略期望值為 {ev_val}%，勝率 {win_rate_val}%。",
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        }
        
        dashboard_data.append(stock_obj)

    # 4. 寫入 JSON 檔案
    final_output = {
        "last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"),
        "data": dashboard_data,
        "ptt": {"score": 55, "sentiment": "中立", "summary": "範例資料"}, # 你可以把原本的 PTT 爬蟲結果放進來
        "macro": {"tw_insight": "大盤量縮整理中", "us_insight": "等待通膨數據"}
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"✅ 報告完成！已成功產生 data.json，請重整你的儀表板網頁。")

# 執行主程式
if __name__ == "__main__":
    generate_dashboard_data()
