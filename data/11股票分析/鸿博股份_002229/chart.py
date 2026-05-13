import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 设置输出路径
output_path = r"C:\Users\34077\Desktop\hongbo_chart.png"

# 1. 获取鸿博股份 002229 近120个交易日数据
print("正在获取鸿博股份(002229)日K线数据...")

import json as _json

data_file = r"C:\Users\34077\Desktop\stock_data.json"
raw = None

# 先尝试从缓存文件加载
if os.path.exists(data_file):
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            raw = _json.load(f)
        print(f"从缓存文件加载 {len(raw)} 条数据")
    except Exception:
        raw = None

# 缓存不存在则实时获取
if raw is None:
    try:
        from curl_cffi import requests
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz002229,day,,,120,qfq"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"},
                         impersonate="chrome120", timeout=15)
        raw = r.json()["data"]["sz002229"]["qfqday"]
        print(f"API获取到 {len(raw)} 条数据")
    except Exception as e:
        print(f"API获取失败: {e}，尝试备用...")
        import urllib.request
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz002229,day,,,120,qfq"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        raw = _json.loads(resp.read().decode())["data"]["sz002229"]["qfqday"]
        print(f"备用接口获取到 {len(raw)} 条数据")

df = pd.DataFrame(raw, columns=["日期", "开盘", "收盘", "最高", "最低", "成交量"])
for col in ["开盘", "最高", "最低", "收盘", "成交量"]:
    df[col] = pd.to_numeric(df[col], errors='coerce')
df["日期"] = pd.to_datetime(df["日期"])
df = df.dropna(subset=["收盘", "开盘", "最高", "最低"])

# 2. 数据处理
df = df.sort_values("日期").reset_index(drop=True)
df.columns = [c.strip() for c in df.columns]

# 统一列名
col_map = {}
for c in df.columns:
    cl = c.lower()
    if "日期" in c or "date" in cl:
        col_map[c] = "日期"
    elif "开" in c or "open" in cl:
        col_map[c] = "开盘"
    elif "高" in c or "high" in cl:
        col_map[c] = "最高"
    elif "低" in c or "low" in cl:
        col_map[c] = "最低"
    elif "收" in c or "close" in cl:
        col_map[c] = "收盘"
    elif "量" in c or "vol" in cl or "成交" in c:
        col_map[c] = "成交量"
df = df.rename(columns=col_map)

if not pd.api.types.is_datetime64_any_dtype(df["日期"]):
    df["日期"] = pd.to_datetime(df["日期"])

df["收盘"] = df["收盘"].astype(float)
df["开盘"] = df["开盘"].astype(float)
df["最高"] = df["最高"].astype(float)
df["最低"] = df["最低"].astype(float)
df["成交量"] = df["成交量"].astype(float)

# 计算均线
df["MA5"] = df["收盘"].rolling(5).mean()
df["MA10"] = df["收盘"].rolling(10).mean()
df["MA20"] = df["收盘"].rolling(20).mean()
df["MA60"] = df["收盘"].rolling(60).mean()

# 计算MACD
df["EMA12"] = df["收盘"].ewm(span=12, adjust=False).mean()
df["EMA26"] = df["收盘"].ewm(span=26, adjust=False).mean()
df["DIF"] = df["EMA12"] - df["EMA26"]
df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
df["MACD"] = 2 * (df["DIF"] - df["DEA"])

# 计算布林带
df["BOLL_MID"] = df["收盘"].rolling(20).mean()
df["BOLL_STD"] = df["收盘"].rolling(20).std()
df["BOLL_UP"] = df["BOLL_MID"] + 2 * df["BOLL_STD"]
df["BOLL_DN"] = df["BOLL_MID"] - 2 * df["BOLL_STD"]

print(f"数据范围: {df['日期'].iloc[0].strftime('%Y-%m-%d')} 至 {df['日期'].iloc[-1].strftime('%Y-%m-%d')}")

# 3. 画图
fig = plt.figure(figsize=(20, 14))
gs = fig.add_gridspec(3, 1, height_ratios=[3, 1, 1], hspace=0.08)

# ---- 主图：K线 + 均线 + 布林带 ----
ax1 = fig.add_subplot(gs[0])

# K线颜色
colors = ['red' if df.loc[i, '收盘'] >= df.loc[i, '开盘'] else 'green' for i in range(len(df))]

# 画布林带
ax1.fill_between(range(len(df)), df["BOLL_UP"], df["BOLL_DN"], alpha=0.08, color='gray', label='Bollinger Band')
ax1.plot(df.index, df["BOLL_UP"], color='gray', linewidth=0.5, alpha=0.5)
ax1.plot(df.index, df["BOLL_MID"], color='orange', linewidth=0.5, alpha=0.5, linestyle='--')
ax1.plot(df.index, df["BOLL_DN"], color='gray', linewidth=0.5, alpha=0.5)

# 画K线
width = 0.6
for i in range(len(df)):
    color = colors[i]
    ax1.plot([i, i], [df.loc[i, '最低'], df.loc[i, '最高']], color=color, linewidth=0.8)
    bottom = min(df.loc[i, '开盘'], df.loc[i, '收盘'])
    height = abs(df.loc[i, '收盘'] - df.loc[i, '开盘'])
    rect = plt.Rectangle((i - width/2, bottom), width, max(height, 0.01),
                         facecolor=color, edgecolor=color, linewidth=0.5, alpha=0.9)
    ax1.add_patch(rect)

# 均线
ax1.plot(df.index, df["MA5"], color='white', linewidth=1.0, label='MA5')
ax1.plot(df.index, df["MA10"], color='yellow', linewidth=1.0, label='MA10')
ax1.plot(df.index, df["MA20"], color='magenta', linewidth=1.0, label='MA20')
ax1.plot(df.index, df["MA60"], color='cyan', linewidth=1.0, label='MA60')

# X轴刻度
tick_positions = np.linspace(0, len(df)-1, min(10, len(df))).astype(int)
tick_labels = [df.loc[p, "日期"].strftime("%m-%d") if 0 <= p < len(df) else "" for p in tick_positions]
ax1.set_xticks(tick_positions)
ax1.set_xticklabels(tick_labels, fontsize=8)

ax1.set_title("鸿博股份(002229) 日K线走势图", fontsize=16, fontweight='bold')
ax1.set_ylabel("价格 (元)", fontsize=11)
ax1.legend(loc='upper left', fontsize=9, ncol=5)
ax1.grid(True, alpha=0.15)
ax1.set_facecolor('#1a1a2e')

# 价格标注
last_price = df["收盘"].iloc[-1]
change_pct = (df["收盘"].iloc[-1] - df["收盘"].iloc[-2]) / df["收盘"].iloc[-2] * 100 if len(df) > 1 else 0
price_text = f"最新价: {last_price:.2f}  ({change_pct:+.2f}%)"
ax1.annotate(price_text, xy=(len(df)-1, last_price),
             xytext=(len(df)+5, last_price), fontsize=11, fontweight='bold',
             color='red' if change_pct >= 0 else 'green',
             arrowprops=dict(arrowstyle='->', color='gray', lw=1))

fig.patch.set_facecolor('#0d0d1a')

# ---- 子图2：成交量 ----
ax2 = fig.add_subplot(gs[1])
vol_colors = ['red' if df.loc[i, '收盘'] >= df.loc[i, '开盘'] else 'green' for i in range(len(df))]
ax2.bar(range(len(df)), df["成交量"]/10000, color=vol_colors, width=0.6, alpha=0.8)
ax2.set_ylabel("成交量(万手)", fontsize=10)
ax2.set_facecolor('#1a1a2e')
ax2.grid(True, alpha=0.15)
ax2.set_xticks(tick_positions)
ax2.set_xticklabels([])

# ---- 子图3：MACD ----
ax3 = fig.add_subplot(gs[2])
# MACD柱
macd_colors = ['red' if v >= 0 else 'green' for v in df["MACD"]]
ax3.bar(range(len(df)), df["MACD"], color=macd_colors, width=0.6, alpha=0.8)
ax3.plot(df.index, df["DIF"], color='white', linewidth=1.0, label='DIF')
ax3.plot(df.index, df["DEA"], color='yellow', linewidth=1.0, label='DEA')
ax3.axhline(y=0, color='gray', linewidth=0.5, linestyle='-')
ax3.set_ylabel("MACD", fontsize=10)
ax3.set_xlabel("日期", fontsize=11)
ax3.set_facecolor('#1a1a2e')
ax3.grid(True, alpha=0.15)
ax3.legend(loc='upper left', fontsize=9)
ax3.set_xticks(tick_positions)
ax3.set_xticklabels(tick_labels, fontsize=8)

# 趋势判断文字
ma5_v = df["MA5"].iloc[-1]
ma20_v = df["MA20"].iloc[-1]
ma60_v = df["MA60"].iloc[-1]
macd_v = df["MACD"].iloc[-1]
dif_v = df["DIF"].iloc[-1]
dea_v = df["DEA"].iloc[-1]

# 趋势判断
price_above_ma60 = last_price > ma60_v if not pd.isna(ma60_v) else None
macd_positive = macd_v > 0
macd_golden = dif_v > dea_v
ma5_above_ma20 = ma5_v > ma20_v if not pd.isna(ma5_v) and not pd.isna(ma20_v) else None

trend_signals = []
if price_above_ma60:
    trend_signals.append("股价位于60日均线上方 → 中长期偏多")
elif price_above_ma60 is not None:
    trend_signals.append("股价位于60日均线下方 → 中长期偏空")

if ma5_above_ma20:
    trend_signals.append("MA5 > MA20 → 短期均线多头排列")
elif ma5_above_ma20 is not None:
    trend_signals.append("MA5 < MA20 → 短期均线空头排列")

if macd_positive:
    trend_signals.append("MACD正值 → 多头动能")
else:
    trend_signals.append("MACD负值 → 空头动能")

if macd_golden:
    trend_signals.append("DIF > DEA → MACD金叉区域")
else:
    trend_signals.append("DIF < DEA → MACD死叉区域")

trend_text = " | ".join(trend_signals)
fig.text(0.5, 0.01, f"趋势综判: {trend_text}",
         ha='center', fontsize=11, fontweight='bold',
         color='white', bbox=dict(boxstyle='round,pad=0.5', facecolor='#1a1a2e', edgecolor='gray', alpha=0.8))

plt.tight_layout(pad=0.5)
plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
plt.close()

print(f"图表已保存至: {output_path}")
print(f"\n===== 鸿博股份(002229) 最新数据 =====")
print(f"日期: {df['日期'].iloc[-1].strftime('%Y-%m-%d')}")
print(f"开盘: {df['开盘'].iloc[-1]:.2f}  最高: {df['最高'].iloc[-1]:.2f}")
print(f"最低: {df['最低'].iloc[-1]:.2f}  收盘: {df['收盘'].iloc[-1]:.2f}")
print(f"涨幅: {change_pct:+.2f}%")
print(f"MA5: {ma5_v:.2f}  MA20: {ma20_v:.2f}  MA60: {ma60_v:.2f}")
print(f"DIF: {dif_v:.4f}  DEA: {dea_v:.4f}  MACD: {macd_v:.4f}")
print(f"\n{trend_text}")
