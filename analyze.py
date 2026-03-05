import yfinance as yf
import pandas as pd
import json
from datetime import datetime
import numpy as np
import requests
import os

def send_line_alert(message):
    """阿土伯專屬 LINE 警報系統 (Messaging API 版)"""
    token = os.environ.get("LINE_ACCESS_TOKEN")
    target_id = os.environ.get("LINE_TARGET_ID")
    
    # 防呆：如果在本地端測試沒設定環境變數，就只印在螢幕上
    if not token or not target_id:
        print(f"🔕 [未連線 LINE] 模擬發送通知：{message}")
        return
        
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    data = {
        "to": target_id,
        "messages": [
            {
                "type": "text",
                "text": message
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            print("✅ LINE 警報發送成功！")
        else:
            print(f"❌ LINE 警報發送失敗: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"❌ LINE 系統發生錯誤: {e}")

# --- 1. 期望值計算機 (核心大腦) ---
def calculate_strategy_ev(ticker, start_date, end_date, stop_loss_pct):
    """依照傳入的停損比例 (stop_loss_pct) 計算歷史期望值"""
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if df.empty: return None
    
    # 防呆：處理 yfinance 多重索引問題
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
            # 盤中最低價觸發停損
            if row['Low'] <= stop_loss_price:
                trades.append(-stop_loss_pct)
                in_position = False
                continue
            # 跌破均線正常出場
            elif row['Signal'] == -1:
                trades.append((row['Close'] - entry_price) / entry_price)
                in_position = False
        # 突破均線進場
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
        "ev": round(ev * 100, 2),        
        "win_rate": round(p_win * 100, 2) 
    }

# --- 2. 大盤環境偵測器 (風控盾牌) ---
def check_market_regime():
    """判斷大盤 (以0050為代表) 是否在多頭趨勢"""
    print("🌍 正在偵測大盤多空環境 (0050.TW)...")
    df = yf.download("0050.TW", period="2mo", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    latest_close = df['Close'].iloc[-1]
    ma20 = df['Close'].rolling(window=20).mean().iloc[-1]
    
    if latest_close >= ma20:
        print("✅ 大盤站上月線，多頭環境：策略停損放寬至 5%")
        return 0.05
    else:
        print("⚠️ 大盤跌破月線，空頭環境：強制啟動避險，策略停損縮緊至 3%")
        return 0.03

# --- 3. 股票清單與主程式 ---
STOCKS = {
    "2330.TW": {"name": "台積電", "category": "晶圓代工"},
    "2303.TW": {"name": "聯電", "category": "晶圓代工"},
    "0050.TW": {"name": "元大台灣50", "category": "台股龍頭"},
    "9802.TW": {"name": "鈺齊-KY", "category": "運動鞋"},
    "9910.TW": {"name": "豐泰", "category": "運動鞋"}
}

def generate_dashboard_data():
    print(f"🚀 阿土伯資料中心啟動 [{datetime.now().strftime('%H:%M:%S')}]")
    
    # 決定今天的動態停損比例
    current_stop_loss = check_market_regime()
    
    dashboard_data = []
    backtest_start = "2021-01-01"
    today_str = datetime.now().strftime("%Y-%m-%d")

    for symbol, info in STOCKS.items():
        print(f"   ➤ 正在解析: {info['name']} ({symbol})")
        
        # 取得 K 線資料算均線與技術指標
        df = yf.download(symbol, period="6mo", progress=False)
        if df.empty: continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        # 💡 核心修正：嘗試抓取盤中即時報價覆蓋 K 線收盤價
        ticker_obj = yf.Ticker(symbol)
        try:
            # fast_info 可以抓到目前最新跳動的價格
            latest_price = round(ticker_obj.fast_info.get('lastPrice', df['Close'].iloc[-1]), 2)
        except:
            latest_price = round(df['Close'].iloc[-1], 2)
            
        # 計算技術指標
        ma5 = round(df['Close'].rolling(window=5).mean().iloc[-1], 2)
        ma20 = round(df['Close'].rolling(window=20).mean().iloc[-1], 2)
        ma60 = round(df['Close'].rolling(window=60).mean().iloc[-1], 2)
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = round(100 - (100 / (1 + rs)).iloc[-1], 2)
        bias = round(((latest_price - ma20) / ma20) * 100, 2)
        
        # 執行期望值回測 (帶入動態停損)
        strategy_result = calculate_strategy_ev(symbol, backtest_start, today_str, stop_loss_pct=current_stop_loss)
        ev_val = strategy_result['ev'] if strategy_result else 0
        win_rate_val = strategy_result['win_rate'] if strategy_result else 0
        
        # 組合前端資料
        stock_obj = {
            "symbol": symbol,
            "name": info["name"],
            "category": info["category"],
            "price": latest_price,
            "rsi": rsi if not np.isnan(rsi) else 50,
            "bias": bias if not np.isnan(bias) else 0,
            "vol_ratio": 1.2, 
            "eps": "N/A",     
            "pe_ratio": "N/A",
            "ev": ev_val,             
            "win_rate": win_rate_val, 
            "ai_summary": f"阿土伯分析：目前大盤停損機制設為 {int(current_stop_loss*100)}%，此策略歷史期望值為 {ev_val}%，勝率 {win_rate_val}%。",
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        }
        dashboard_data.append(stock_obj)

    # 寫入 JSON
    final_output = {
        "last_update": datetime.now().strftime("%Y-%m-%d [%H:%M]"),
        "data": dashboard_data,
        "ptt": {"score": 50, "sentiment": "中立", "summary": "請結合你的 PTT 爬蟲"}, 
        "macro": {"tw_insight": f"大盤停損防護網啟動，目前停損限制: {int(current_stop_loss*100)}%", "us_insight": "美股數據讀取中"}
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=4)
        
    print(f"✅ 報告完成！已成功產生即時 data.json，趕快去重新整理你的戰情室網頁！")

if __name__ == "__main__":
    generate_dashboard_data()

