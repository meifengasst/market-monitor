return json.loads(ai_text)
    except: return [{"title": n["title"], "link": n["link"], "sentiment": "中立 ⚪"} for n in news_list]

def generate_dashboard_data():
    bear_markets = check_market_regime() 
    portfolio_file = "portfolio.json"
    try:
        with open(portfolio_file, "r", encoding="utf-8") as f: cloud_portfolio = json.load(f)
    except: cloud_portfolio = {}
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
                    res = requests.get(f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={finnhub_key}", timeout=5)
                    if res.status_code == 200 and res.json().get('c') > 0:
                        df.iloc[-1, df.columns.get_loc('Close')] = round(res.json().get('c'), 2)
                except: pass
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
        df['Signal'] = np.where(df['Close'] > df['ma20'], 1, np.where(df['Close'] < df['ma20'], -1, 0))
        df = df.fillna(0)
        
        df = calculate_atr_stop_loss(df, period=14, multiplier=1.5)
        current_price = round(df['Close'].iloc[-1], 2)
        current_atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.03)

        try:
            market_idx = tw_idx if symbol.endswith(".TW") else us_idx
            stock_ret_20 = (df['Close'].iloc[-1] - df['Close'].iloc[-20]) / df['Close'].iloc[-20]
            idx_ret_20 = (market_idx['Close'].iloc[-1] - market_idx['Close'].iloc[-20]) / market_idx['Close'].iloc[-20]
            rs_score = round((stock_ret_20 - idx_ret_20) * 100, 2)
        except: rs_score = 0
        
        best_multiplier, best_ev = 1.5, -999
        for mult in [1.5, 2.0, 2.5, 3.0]:
            res = calculate_ev_from_df(df, atr_period=14, atr_multiplier=mult)
            if res and res['ev'] > best_ev: best_ev, best_multiplier = res['ev'], mult
                
        is_bear = bear_markets["TW"] if symbol.endswith(".TW") else bear_markets["US"]
        actual_multiplier = 1.0 if is_bear else best_multiplier 
        actual_res = calculate_ev_from_df(df, atr_period=14, atr_multiplier=actual_multiplier)
        actual_ev = actual_res['ev'] if actual_res else 0
        actual_win = actual_res['win_rate'] if actual_res else 0

        best_sl_pct = (current_atr * best_multiplier) / current_price
        actual_sl_pct = (current_atr * actual_multiplier) / current_price

        if symbol in cloud_portfolio:
            trade = cloud_portfolio[symbol]
            entry_price = trade.get('entryPrice', current_price)
            peak_price = trade.get('peakPrice', entry_price)

            if current_price > peak_price:
                trade['peakPrice'] = current_price
                portfolio_updated = True
                peak_price = current_price

            actual_exit_price = max(entry_price * (1 - actual_sl_pct), peak_price * (1 - actual_sl_pct))

            if current_price <= actual_exit_price:
                if not trade.get('alerted', False): 
                    if is_bear: reason_msg = f"\n⚠️ [大盤避險啟動]\n停損強制收緊至 {int(actual_sl_pct*100)}%！"
                    else: reason_msg = f"\n(套用系統最佳停損 {int(best_sl_pct*100)}%)"
                    alert_msg = f"🚨【阿土伯停損逃命警報】🚨\n\n股票：{info['name']} ({symbol})\n現價：${current_price}\n防線：${round(actual_exit_price, 2)}{reason_msg}\n\n⚡ 已跌破嚴格防線，請立即無情清倉，保護本金！"
                    send_line_alert(alert_msg)
                    trade['alerted'] = True
                    portfolio_updated = True
            else:
                if trade.get('alerted', False):
                    trade['alerted'] = False
                    portfolio_updated = True

        hist = [{"date": i.strftime("%Y-%m-%d"), "price": round(r['Close'], 2), "volume": int(r['Volume']), "ma5": round(r['ma5'], 2), "ma20": round(r['ma20'], 2), "ma60": round(r['ma60'], 2), "macd": round(r['macd'], 2), "macd_signal": round(r['macd_signal'], 2), "macd_hist": round(r['macd_hist'], 2), "rsi": round(r['rsi'], 2), "bb_upper": round(r['bb_upper'], 2), "bb_lower": round(r['bb_lower'], 2)} for i, r in df.tail(60).iterrows()]
        rs_comment = f"【主力資金偏好】近期表現強於大盤 {rs_score}%！" if rs_score > 5 else (f"【溫吞股】近期表現落後大盤 {rs_score}%。" if rs_score < 0 else "與大盤同步。")
        
        ai_msg = f"🎯 最佳動態停損為 {int(best_sl_pct*100)}% (ATR {best_multiplier}倍)。"
        if is_bear: ai_msg += f"目前大盤破線，防守強制收緊至 {int(actual_sl_pct*100)}% (ATR 1倍)！ {rs_comment}"
        else: ai_msg += f"目前大盤穩定。 {rs_comment}"

        news_list = get_ai_news_sentiment(symbol, info["name"])
        
        dashboard_data.append({
            "symbol": symbol, "name": info["name"], "category": info["category"],
            "price": current_price, "rsi": round(df['rsi'].iloc[-1], 2), "bias": round(((current_price - df['ma20'].iloc[-1]) / df['ma20'].iloc[-1]) * 100, 2) if df['ma20'].iloc[-1] else 0,
            "vol_ratio": 1.2, "optimal_sl": int(best_sl_pct*100), "actual_sl": int(actual_sl_pct*100),
            "ev": actual_ev, "win_rate": actual_win, "history": hist, 
            "rs_score": rs_score, 
            "ai_summary": ai_msg,
            "news_items": news_list, 
            "lights": {"short": "⚪", "mid": "⚪", "long": "⚪"}
        })

    try: vix_price = round(yf.Ticker("^VIX").fast_info.get('lastPrice', 0), 2)
    except: vix_price = 0

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
