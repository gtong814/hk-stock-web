import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime

# 1. 網頁基本設定
st.set_page_config(layout="wide", page_title="港股 AI 技術分析儀表板")

# 常見港股中文名稱對照（方便自動搜尋中文新聞）
HK_STOCK_NAMES = {
    "0700.HK": "騰訊控股",
    "9988.HK": "阿里巴巴",
    "0005.HK": "匯豐控股",
    "3690.HK": "美團",
    "0388.HK": "香港交易所",
    "0941.HK": "中國移動",
    "1299.HK": "友邦保險",
    "1810.HK": "小米集團",
    "9618.HK": "京東集團",
    "1211.HK": "比亞迪股份"
}

col_input1, col_input2 = st.columns([1, 3])
with col_input1:
    ticker = st.text_input("輸入港股代碼 (例如 0700.HK, 9988.HK, 0005.HK)", value="0700.HK").strip().upper()
with col_input2:
    period = st.selectbox("選擇時間範圍", ["6mo", "1y", "2y"], index=1)

# 2. 抓取港股歷史數據
@st.cache_data(ttl=300)
def load_data(symbol, time_period):
    df = yf.download(symbol, period=time_period, progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

df = load_data(ticker, period)

if df.empty:
    st.error(f"找不到代碼 `{ticker}` 的資料，請確認格式（例如：騰訊請輸入 `0700.HK`）。")
    st.stop()

# 3. 使用純 Pandas 計算各項技術指標
# (A) 移動平均線 (MA)
df['MA5'] = df['Close'].rolling(window=5).mean()
df['MA20'] = df['Close'].rolling(window=20).mean()
df['MA60'] = df['Close'].rolling(window=60).mean()

# (B) RSI (14日)
delta = df['Close'].diff()
gain = delta.clip(lower=0)
loss = -delta.clip(upper=0)
avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
rs = avg_gain / avg_loss
df['RSI'] = 100 - (100 / (1 + rs))

# (C) KD 指標 (9, 3, 3)
low_9 = df['Low'].rolling(window=9).min()
high_9 = df['High'].rolling(window=9).max()
rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
df['K'] = rsv.ewm(com=2, adjust=False).mean()
df['D'] = df['K'].ewm(com=2, adjust=False).mean()

# (D) MACD (12, 26, 9)
ema12 = df['Close'].ewm(span=12, adjust=False).mean()
ema26 = df['Close'].ewm(span=26, adjust=False).mean()
df['MACD'] = ema12 - ema26
df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

# (E) 布林通道 (20日, 2倍標準差)
std20 = df['Close'].rolling(window=20).std()
df['BBU'] = df['MA20'] + (2 * std20)
df['BBL'] = df['MA20'] - (2 * std20)

# 取得最新與前一日數據
latest = df.iloc[-1]
prev = df.iloc[-2]
price_change = latest['Close'] - prev['Close']
pct_change = (price_change / prev['Close']) * 100

# 4. 自動計算多空評分與指標狀態邏輯
score = 0

if latest['Close'] > latest['MA20'] and latest['MA5'] > latest['MA20']:
    ma_status = "多頭排列"
    score += 2
elif latest['Close'] < latest['MA20'] and latest['MA5'] < latest['MA20']:
    ma_status = "空頭排列"
    score -= 2
else:
    ma_status = "盤整震盪"

rsi_val = latest['RSI']
if rsi_val > 70:
    rsi_status = f"超買 ({rsi_val:.1f})"
    score -= 1
elif rsi_val < 30:
    rsi_status = f"超賣 ({rsi_val:.1f})"
    score += 1
else:
    rsi_status = f"中性 ({rsi_val:.1f})"

k_val, d_val = latest['K'], latest['D']
if k_val > d_val and k_val < 80:
    kd_status = f"黃金交叉 (K:{k_val:.1f})"
    score += 2
elif k_val < d_val and k_val > 20:
    kd_status = f"死亡交叉 (K:{k_val:.1f})"
    score -= 2
else:
    kd_status = f"高/低檔鈍化 (K:{k_val:.1f})"

macd_hist = latest['MACD_Hist']
if macd_hist > 0:
    macd_status = f"多方動能 ({macd_hist:.2f})"
    score += 2
else:
    macd_status = f"空方動能 ({macd_hist:.2f})"
    score -= 2

overall_rating = "偏多進攻" if score >= 3 else ("偏空防守" if score <= -3 else "中性觀望")

# 5. 抓取財經新聞函數
def fetch_stock_news(symbol):
    zh_news = []
    yf_news = []
    stock_name = HK_STOCK_NAMES.get(symbol, symbol)

    # (A) 抓取中文財經新聞 (Bing News RSS)
    try:
        query_keyword = f"{stock_name} 股價" if stock_name != symbol else f"{symbol} 港股"
        encoded_q = urllib.parse.quote(query_keyword)
        rss_url = f"https://www.bing.com/news/search?q={encoded_q}&format=rss&mkt=zh-HK"
        
        req = urllib.request.Request(
            rss_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        for item in root.findall('./channel/item')[:6]:
            title = item.find('title').text if item.find('title') is not None else "無標題"
            link = item.find('link').text if item.find('link') is not None else "#"
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
            source = "Bing 財經"
            for child in item:
                if child.tag.endswith('Source') and child.text:
                    source = child.text
                    break
            zh_news.append({
                "title": title,
                "link": link,
                "publisher": source,
                "time": pub_date[:16]
            })
    except Exception as e:
        st.warning(f"中文新聞抓取異常：{e}")

    # (B) 抓取 Yahoo Finance 相關新聞
    try:
        raw_news = yf.Ticker(symbol).news or []
        if not raw_news:
            raw_news = yf.Search(symbol, news_count=6).news or []
            
        for item in raw_news[:6]:
            if 'content' in item and isinstance(item['content'], dict):
                c = item['content']
                title = c.get('title', '無標題')
                publisher = c.get('provider', {}).get('displayName', 'Yahoo Finance')
                link = (c.get('canonicalUrl') or {}).get('url') or (c.get('clickThroughUrl') or {}).get('url') or '#'
                pub_time = c.get('pubDate', '')[:10]
            else:
                title = item.get('title', '無標題')
                publisher = item.get('publisher', 'Yahoo Finance')
                link = item.get('link', '#')
                ts = item.get('providerPublishTime', 0)
                pub_time = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else ''
            
            if title and title != '無標題':
                yf_news.append({
                    "title": title,
                    "link": link,
                    "publisher": publisher,
                    "time": pub_time
                })
    except Exception as e:
        st.warning(f"Yahoo 新聞抓取異常：{e}")

    return zh_news, yf_news

# ==========================================
# 畫面渲染區塊
# ==========================================
display_title = f"{HK_STOCK_NAMES[ticker]} ({ticker})" if ticker in HK_STOCK_NAMES else ticker
st.title(f"📊 {display_title} 技術分析看盤儀表板")

st.subheader("1. 市場概況與多空評級")
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("最新收盤價 (HKD)", f"HK$ {latest['Close']:.2f}", f"{price_change:+.2f} ({pct_change:+.2f}%)")
kpi2.metric("最新成交量 (股)", f"{int(latest['Volume']):,}")
kpi3.metric("區間高低點 (HKD)", f"{df['Low'].min():.2f} ~ {df['High'].max():.2f}")
kpi4.metric("綜合多空評級", overall_rating, f"評分: {score} / 8", delta_color="normal" if score >= 0 else "inverse")

st.divider()

st.subheader("2. 技術指標參考 (Technical Indicators Reference)")
ind1, ind2, ind3, ind4 = st.columns(4)
ind1.metric("均線排列 (MA5 / MA20)", ma_status)
ind2.metric("KD 指標 (9,3,3)", kd_status)
ind3.metric("RSI 指標 (14日)", rsi_status)
ind4.metric("MACD 柱狀體", macd_status)

st.divider()

st.subheader(f"3. {display_title} 主 K 線與多空均線走勢圖")
fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
    name='K線', increasing_line_color='#00C805', decreasing_line_color='#FF3B30'
))
fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='#FFA500', width=1.2), name='MA5 (週線)'))
fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#00E5FF', width=1.5), name='MA20 (月線)'))
fig.add_trace(go.Scatter(x=df.index, y=df['MA60'], line=dict(color='#B388FF', width=1.5), name='MA60 (季線)'))
fig.add_trace(go.Scatter(x=df.index, y=df['BBU'], line=dict(color='rgba(150, 150, 150, 0.5)', dash='dot'), name='布林上軌'))
fig.add_trace(go.Scatter(
    x=df.index, y=df['BBL'], line=dict(color='rgba(150, 150, 150, 0.5)', dash='dot'),
    fill='tonexty', fillcolor='rgba(100, 149, 237, 0.08)', name='布林下軌'
))

fig.update_layout(
    template="plotly_dark", xaxis_rangeslider_visible=False, height=600,
    margin=dict(l=20, r=20, t=30, b=20), yaxis_title="股價 (HKD)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig, use_container_width=True)

st.divider()

# ==========================================
# 第 4 區塊：相關財經新聞動態
# ==========================================
st.subheader(f"4. 📰 {display_title} 相關財經新聞")

zh_news_list, yf_news_list = fetch_stock_news(ticker)

news_col1, news_col2 = st.columns(2)

with news_col1:
    st.markdown("#### 🇭🇰 香港財經快訊")
    if zh_news_list:
        for item in zh_news_list:
            st.markdown(f"- **[{item['title']}]({item['link']})**  \n  <small>來源：{item['publisher']} ｜ {item['time']}</small>", unsafe_allow_html=True)
    else:
        st.info("暫無相關中文新聞。")

with news_col2:
    st.markdown("#### 🌐 Yahoo Finance 市場報導")
    if yf_news_list:
        for item in yf_news_list:
            st.markdown(f"- **[{item['title']}]({item['link']})**  \n  <small>來源：{item['publisher']} ｜ {item['time']}</small>", unsafe_allow_html=True)
    else:
        st.info("暫無相關英文新聞。")
