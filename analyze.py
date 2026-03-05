import yfinance as yf
import pandas as pd
import numpy as np

def calculate_strategy_ev(ticker, start_date, end_date, stop_loss_pct=0.05):
    """
    阿土伯的期望值計算機 (進階版：加入強制停損防護網)
    stop_loss_pct: 預設為 0.05，代表 5% 強制停損
    """
    print(f"📊 正在載入 {ticker} 從 {start_date} 到 {end_date} 的海量數據...")
    # 1. 抓取歷史數據
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    
    if df.empty:
        return "找不到數據，請確認股票代號或日期。"

    # 確保資料格式正確 (處理 yfinance 可能產生的 MultiIndex 問題)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    # 2. 定義策略：突破20日均線買進，跌破20日均線賣出
    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['Signal'] = 0
    
    # 產生進出場訊號 (用收盤價判定)
    df.loc[df['Close'] > df['SMA_20'], 'Signal'] = 1  # 多方環境
    df.loc[df['Close'] < df['SMA_20'], 'Signal'] = -1 # 空方環境

    # 3. 模擬交易與停損邏輯
    trades = []
    entry_price = 0
    in_position = False

    for index, row in df.iterrows():
        # -- 已經持有部位的狀態 --
        if in_position:
            # 🛑 優先檢查：盤中是否觸發強制停損 (最低價 <= 停損價)
            stop_loss_price = entry_price * (1 - stop_loss_pct)
            
            if row['Low'] <= stop_loss_price:
                # 觸發停損，假設我們以停損價精準砍倉 (實戰可能會有滑價，這裡先簡化)
                trade_return = -stop_loss_pct
                trades.append(trade_return)
                in_position = False
                continue # 這筆交易結束，跳到下一天
                
            # 📉 檢查正常出場訊號：跌破 20 日均線
            elif row['Signal'] == -1:
                exit_price = row['Close']
                trade_return = (exit_price - entry_price) / entry_price
                trades.append(trade_return)
                in_position = False

        # -- 空手狀態 --
        # 📈 檢查進場訊號：突破 20 日均線
        elif not in_position and row['Signal'] == 1:
            entry_price = row['Close']
            in_position = True

    if not trades:
        return "這段期間內沒有觸發任何完整交易。"

    # 4. 數據清洗與期望值 (EV) 計算
    trades_series = pd.Series(trades)
    winning_trades = trades_series[trades_series > 0]
    losing_trades = trades_series[trades_series <= 0]

    # 計算公式所需的四個變數
    p_win = len(winning_trades) / len(trades_series) if len(trades_series) > 0 else 0
    p_loss = len(losing_trades) / len(trades_series) if len(trades_series) > 0 else 0
    avg_win = winning_trades.mean() if not winning_trades.empty else 0
    avg_loss = abs(losing_trades.mean()) if not losing_trades.empty else 0 

    # 帶入阿土伯的期望值公式
    ev = (p_win * avg_win) - (p_loss * avg_loss)

    # 5. 輸出戰情報表
    report = {
        "測試標的": ticker,
        "停損設定": f"{stop_loss_pct * 100}%",
        "總交易次數": len(trades_series),
        "勝率 (%)": round(p_win * 100, 2),
        "平均獲利 (%)": round(avg_win * 100, 2),
        "平均虧損 (%)": round(avg_loss * 100, 2), # 有了停損，這個數字絕對不會超過 5% 太多！
        "單筆期望值 (%)": round(ev * 100, 2)
    }
    
    return report

# 🚀 執行範例：跑跑看台積電 (2330.TW)，比較看看有沒有停損的威力
print("--- 加上 5% 停損的績效 ---")
print(calculate_strategy_ev("2330.TW", "2015-01-01", "2026-03-01", stop_loss_pct=0.05))

print("\n--- 不設停損 (設為 100% 等同於不停損) 的績效 ---")
print(calculate_strategy_ev("2330.TW", "2015-01-01", "2026-03-01", stop_loss_pct=1.00))
