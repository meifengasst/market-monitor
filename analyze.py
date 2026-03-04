import yfinance as yf
import json
import pandas as pd
import os
import requests
import time
import xml.etree.ElementTree as ET
from datetime import datetime
import urllib.parse

# 1. 統一鑰匙庫
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') 
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN")
LINE_TARGET_ID = os.environ.get("LINE_TARGET_ID")

CATEGORIES = {"美國科技": ["NVDA", "TSLA"], "美股大盤": ["SPY"], "台股龍頭": ["0050.TW", "2330.TW"], "晶圓代工": ["2330.TW", "2303.TW"], "運動鞋": ["9802.TW", "9910.TW", "9904.TW"]}
STOCKS = {"NVDA": "Nvidia (AI之王)", "TSLA": "Tesla (電動車)", "SPY": "S&P 500 ETF", "0050.TW": "元大台灣50", "2330.TW": "台積電", "2303.TW": "聯電", "9802.TW": "鈺齊-KY", "9910.TW": "豐泰", "9904.TW": "寶成"}

def get_google_news(is_taiwan=True):
    url = "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh-Hant" if is_taiwan else "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en"
    try:
        res = requests.get(url, timeout=10)
        root = ET.fromstring(res.text)
        return [item.find('title').text for item in root.findall('.//item')[:5]]
    except: return ["暫無新聞"]

# 🚀 統一使用 Google 跨國新聞雷達 (拋棄不穩定的 Yahoo)
def get_specific_stock_news(keyword, is_taiwan=True):
    encoded_kw = urllib.parse.quote(keyword)
    if is_taiwan:
        url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    else:
        url = f"https://news.google.com/rss/search?q={encoded_kw}&hl=en-US&gl=US&ceid=US:en"
    
    try:
        res = requests.get(url, timeout=10)
        root = ET.fromstring(res.text)
        news = []
        for item in root.findall('.//item')[:3]: # 抓前3篇
            news.append({'title': item.find('title').text, 'link': item.find('link').text})
        return news
    except: return []

def get_ptt_news():
    try:
        res = requests.get("https://www.ptt.cc/atom/stock.xml", timeout=10)
        root = ET.fromstring(res.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        entries = root.findall('atom:entry', ns)
        ptt_list = []
        for entry in entries[:50]:
            title = entry.find('atom:title', ns).text
            link = entry.find('atom:link', ns).attrib['href']
            ptt_list.append({"title": title, "link": link})
        return ptt_list
    except: return []

def get_ptt_sentiment(ptt_list):
    if not GEMINI_API_KEY: return {"score": 50, "sentiment": "未連線", "summary": "找不到鑰匙"}
    if not ptt_list: return {"score": 50, "sentiment": "抓取失敗", "summary": "無法讀取 PTT 股版"}
    
    titles = [p['title'] for p in ptt_list]
    prompt = """你是頂級股市心理學家。請分析以下PTT股版最新標題，判斷台灣散戶情緒。
請嚴格輸出 JSON 格式，必須包含以下 key，不要任何其他文字：
{"score": 貪婪指數(0-100的整數), "sentiment": "極度恐慌|恐慌|中立|貪婪|極度貪婪", "summary": "25字以內的點評", "top_stocks": ["熱門股1", "熱門股2", "熱門股3"], "bull_view": "多方論點(30字)", "bear_view": "空方擔憂(30字)"}
標題：\n""" + "\n".join(titles)

    url = "https://api.groq.com/openai/v1/chat/completions"
    data = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "response_format": {"type": "json_object"}}
    try:
        res = requests.post(url, headers={"Authorization": f"Bearer {GEMINI_API_KEY}", "Content-Type": "application/json"}, json=data, timeout=20)
        if res.status_code == 200:
            text = res.json()['choices'][0]['message']['content'].strip()
            if text.startswith('
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1
http://googleusercontent.com/immersive_entry_chip/2
http://googleusercontent.com/immersive_entry_chip/3
http://googleusercontent.com/immersive_entry_chip/4
http://googleusercontent.com/immersive_entry_chip/5

### ☕ 這次請泡杯咖啡再回來！

覆蓋存檔後，去 **Actions 點擊 Run workflow**。
**🚨 注意：** 因為我們把安全冷卻時間拉長到了 5 秒，加上要處理 9 檔股票的翻譯與 2 檔大盤、還有 PTT 爬文，這次機器人大概會跑 **1 分鐘左右** 才會亮綠燈。

耐心等它跑完 ✅，然後回到網頁按 `F5` 重新整理。
你去點開 NVDA 或 TSLA 的「📰 深度外電」，絕對會有滿滿的繁體中文翻譯新聞跳出來迎接你！衝啊老闆，我們一定能戰勝它！
