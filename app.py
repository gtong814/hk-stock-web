# 請在 app.py 最上方 import 區塊確認有這幾行：
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# 將原本的 fetch_stock_news 函數替換為以下版本：
def fetch_stock_news(symbol):
    zh_news = []
    yf_news = []
    stock_name = HK_STOCK_NAMES.get(symbol, symbol)
    hk_tz = timezone(timedelta(hours=8)) # 香港時區 (UTC+8)

    # (A) 抓取最新香港中文財經新聞 (限定最近 3 天 + 按時間排序)
    try:
        clean_name = stock_name.replace("-W", "").replace("-SW", "")
        # 加入 when:3d 強制只抓近 3 天新聞
        query_keyword = f"{clean_name} when:3d" if clean_name != symbol else f"{symbol} 港股 when:3d"
        encoded_q = urllib.parse.quote(query_keyword)
        rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
        
        req = urllib.request.Request(
            rss_url,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        temp_list = []
        for item in root.findall('./channel/item')[:10]:
            title = item.find('title').text if item.find('title') is not None else "無標題"
            link = item.find('link').text if item.find('link') is not None else "#"
            pub_date_str = item.find('pubDate').text if item.find('pubDate') is not None else ""
            source = item.find('source').text if item.find('source') is not None else "香港財經"
            
            # 解析發佈時間並轉為香港時間，方便由新到舊排序
            try:
                dt = parsedate_to_datetime(pub_date_str).astimezone(hk_tz)
                formatted_time = dt.strftime('%Y-%m-%d %H:%M')
                timestamp = dt.timestamp()
            except Exception:
                formatted_time = pub_date_str[:16]
                timestamp = 0

            temp_list.append({
                "title": title,
                "link": link,
                "publisher": source,
                "time": formatted_time,
                "ts": timestamp
            })
            
        # 依照時間戳記由新到舊排序，取最新 6 則
        temp_list.sort(key=lambda x: x["ts"], reverse=True)
        zh_news = temp_list[:6]
    except Exception as e:
        st.warning(f"中文新聞抓取異常：{e}")

    # (B) 抓取 Yahoo Finance 最新相關新聞 (按時間由新到舊排序)
    try:
        raw_news = yf.Ticker(symbol).news or []
        temp_yf = []
        for item in raw_news[:10]:
            if 'content' in item and isinstance(item['content'], dict):
                c = item['content']
                title = c.get('title', '無標題')
                publisher = c.get('provider', {}).get('displayName', 'Yahoo Finance')
                link = (c.get('canonicalUrl') or {}).get('url') or (c.get('clickThroughUrl') or {}).get('url') or '#'
                pub_str = c.get('pubDate', '')
                try:
                    dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00')).astimezone(hk_tz)
                    pub_time = dt.strftime('%Y-%m-%d %H:%M')
                    ts = dt.timestamp()
                except Exception:
                    pub_time = pub_str[:16]
                    ts = 0
            else:
                title = item.get('title', '無標題')
                publisher = item.get('publisher', 'Yahoo Finance')
                link = item.get('link', '#')
                ts = item.get('providerPublishTime', 0)
                pub_time = datetime.fromtimestamp(ts, tz=hk_tz).strftime('%Y-%m-%d %H:%M') if ts else ''
            
            if title and title != '無標題':
                temp_yf.append({
                    "title": title,
                    "link": link,
                    "publisher": publisher,
                    "time": pub_time,
                    "ts": ts
                })
                
        temp_yf.sort(key=lambda x: x["ts"], reverse=True)
        yf_news = temp_yf[:6]
    except Exception as e:
        st.warning(f"Yahoo 新聞抓取異常：{e}")

    return zh_news, yf_news
