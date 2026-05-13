import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import datetime
import time
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 宝胜股份(600973) 完整技术分析 - 腾讯数据源
# ============================================================
code = "600973"
name = "宝胜股份"
market = "sh"  # 上海

print("=" * 60)
print(f"  {name}({code}) 技术面预判分析")
print(f"  分析时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"  数据源: 腾讯财经")
print("=" * 60)

# -------- 1. 拉取数据 --------
def fetch_tencent_kline(market, code, period, count=400):
    """从腾讯财经拉取K线数据"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},{period},,,{count},qfq"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://gu.qq.com/',
    }
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            data = r.json()
            if data.get('code') == 0:
                stock_key = f"{market}{code}"
                kline_data = data['data'][stock_key][f'qfq{period}']
                return kline_data
            else:
                raise Exception(f"API返回错误: {data}")
        except Exception as e:
            wait = 2 ** attempt
            print(f"   ⚠ {period}线 第{attempt+1}次失败, {wait}秒后重试... ({str(e)[:60]})")
            time.sleep(wait)
    raise RuntimeError(f"{period}线拉取失败")

def kline_to_df(kline_data):
    """腾讯K线数据转DataFrame"""
    # 格式: [date, open, close, high, low, volume]
    columns = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
    df = pd.DataFrame(kline_data, columns=columns)
    for col in ['开盘', '收盘', '最高', '最低']:
        df[col] = df[col].astype(float)
    df['成交量'] = df['成交量'].astype(float) * 100  # 手转股
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.set_index('日期').sort_index()
    # 计算其他字段
    df['涨跌幅'] = df['收盘'].pct_change() * 100
    # 估算成交额 (量*均价)
    df['成交额'] = df['成交量'] * (df['最高'] + df['最低'] + df['开盘'] + df['收盘']) / 4
    df['换手率'] = df['成交量'] / 898091487 * 100  # 总股本约8.98亿
    return df

print("正在拉取数据...")

raw_daily = fetch_tencent_kline(market, code, 'day', 400)
df_daily = kline_to_df(raw_daily)
time.sleep(0.5)

raw_weekly = fetch_tencent_kline(market, code, 'week', 120)
df_weekly = kline_to_df(raw_weekly)
time.sleep(0.5)

raw_monthly = fetch_tencent_kline(market, code, 'month', 80)
df_monthly = kline_to_df(raw_monthly)

print(f"日线: {df_daily.index[0].strftime('%Y-%m-%d')} ~ {df_daily.index[-1].strftime('%Y-%m-%d')}, 共{len(df_daily)}条")
print(f"周线: {df_weekly.index[0].strftime('%Y-%m-%d')} ~ {df_weekly.index[-1].strftime('%Y-%m-%d')}, 共{len(df_weekly)}条")

# -------- 2. 技术指标计算 --------
close = df_daily['收盘']
high = df_daily['最高']
low = df_daily['最低']
volume = df_daily['成交量']

# MA均线
df_daily['MA5'] = close.rolling(5).mean()
df_daily['MA10'] = close.rolling(10).mean()
df_daily['MA20'] = close.rolling(20).mean()
df_daily['MA60'] = close.rolling(60).mean()
df_daily['MA120'] = close.rolling(120).mean()

# 成交量均线
df_daily['VOL_MA5'] = volume.rolling(5).mean()
df_daily['VOL_MA20'] = volume.rolling(20).mean()

# MACD
ema12 = close.ewm(span=12, adjust=False).mean()
ema26 = close.ewm(span=26, adjust=False).mean()
df_daily['MACD_DIF'] = ema12 - ema26
df_daily['MACD_DEA'] = df_daily['MACD_DIF'].ewm(span=9, adjust=False).mean()
df_daily['MACD_BAR'] = 2 * (df_daily['MACD_DIF'] - df_daily['MACD_DEA'])

# RSI
delta = close.diff()
gain = delta.where(delta > 0, 0.0)
loss = (-delta).where(delta < 0, 0.0)
avg_gain = gain.ewm(span=14, adjust=False).mean()
avg_loss = loss.ewm(span=14, adjust=False).mean()
rs = avg_gain / avg_loss
df_daily['RSI14'] = 100 - (100 / (1 + rs))

# KDJ
low_9 = low.rolling(9).min()
high_9 = high.rolling(9).max()
rsv = (close - low_9) / (high_9 - low_9) * 100
df_daily['KDJ_K'] = rsv.ewm(com=2, adjust=False).mean()
df_daily['KDJ_D'] = df_daily['KDJ_K'].ewm(com=2, adjust=False).mean()
df_daily['KDJ_J'] = 3 * df_daily['KDJ_K'] - 2 * df_daily['KDJ_D']

# 布林带(20,2)
df_daily['BOLL_MID'] = close.rolling(20).mean()
bb_std = close.rolling(20).std()
df_daily['BOLL_UP'] = df_daily['BOLL_MID'] + 2 * bb_std
df_daily['BOLL_DN'] = df_daily['BOLL_MID'] - 2 * bb_std

# ATR
tr = pd.concat([high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()], axis=1).max(axis=1)
df_daily['ATR14'] = tr.rolling(14).mean()

# OBV
df_daily['OBV'] = (volume * ((close.diff() > 0).astype(int) * 2 - 1)).fillna(0).cumsum()

# -------- 3. 关键价位识别 --------
latest_close = close.iloc[-1]
resistance_short = df_daily['最高'].tail(20).max()
support_short = df_daily['最低'].tail(20).min()
month_high_60 = df_daily['最高'].tail(60).max()
month_low_60 = df_daily['最低'].tail(60).min()
quarter_high = df_daily['最高'].tail(120).max() if len(df_daily) >= 120 else df_daily['最高'].max()
quarter_low = df_daily['最低'].tail(120).min() if len(df_daily) >= 120 else df_daily['最低'].min()

print(f"\n最新行情 ({close.index[-1].strftime('%Y-%m-%d')})")
print(f"   收盘: {latest_close:.2f}  开盘: {df_daily['开盘'].iloc[-1]:.2f}")
print(f"   最高: {high.iloc[-1]:.2f}  最低: {low.iloc[-1]:.2f}")
print(f"   涨幅: {df_daily['涨跌幅'].iloc[-1]:.2f}%")
print(f"   换手: {df_daily['换手率'].iloc[-1]:.2f}%")

print(f"\n技术指标:")
ma5_v = df_daily['MA5'].iloc[-1]
ma10_v = df_daily['MA10'].iloc[-1]
ma20_v = df_daily['MA20'].iloc[-1]
ma60_v = df_daily['MA60'].iloc[-1]
print(f"   MA5:{ma5_v:.2f}  MA10:{ma10_v:.2f}  MA20:{ma20_v:.2f}  MA60:{ma60_v:.2f}")
print(f"   MACD_DIF:{df_daily['MACD_DIF'].iloc[-1]:.3f}  DEA:{df_daily['MACD_DEA'].iloc[-1]:.3f}  BAR:{df_daily['MACD_BAR'].iloc[-1]:.3f}")
print(f"   RSI14:{df_daily['RSI14'].iloc[-1]:.1f}  K:{df_daily['KDJ_K'].iloc[-1]:.1f}  D:{df_daily['KDJ_D'].iloc[-1]:.1f}  J:{df_daily['KDJ_J'].iloc[-1]:.1f}")
print(f"   BOLL上:{df_daily['BOLL_UP'].iloc[-1]:.2f}  中:{df_daily['BOLL_MID'].iloc[-1]:.2f}  下:{df_daily['BOLL_DN'].iloc[-1]:.2f}")
print(f"   ATR14:{df_daily['ATR14'].iloc[-1]:.2f}")

# -------- 4. 形态识别 --------
ret_5d = (close.iloc[-1] / close.iloc[-5] - 1) * 100
ret_10d = (close.iloc[-1] / close.iloc[-10] - 1) * 100
ret_20d = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0

# 均线排列
ma_values = [ma5_v, ma10_v, ma20_v, ma60_v]
bullish_align = all(ma_values[i] > ma_values[i+1] for i in range(len(ma_values)-1))
bearish_align = all(ma_values[i] < ma_values[i+1] for i in range(len(ma_values)-1))

# MACD交叉
macd_cross_up = (df_daily['MACD_DIF'].iloc[-2] < df_daily['MACD_DEA'].iloc[-2] and
                 df_daily['MACD_DIF'].iloc[-1] > df_daily['MACD_DEA'].iloc[-1])
macd_cross_down = (df_daily['MACD_DIF'].iloc[-2] > df_daily['MACD_DEA'].iloc[-2] and
                   df_daily['MACD_DIF'].iloc[-1] < df_daily['MACD_DEA'].iloc[-1])

vol_ratio = volume.iloc[-5:].mean() / volume.iloc[-20:].mean()

print(f"\n形态特征:")
print(f"   近5日涨幅:{ret_5d:.1f}%  近10日:{ret_10d:.1f}%  近20日:{ret_20d:.1f}%")
print(f"   均线排列: {'多头' if bullish_align else '空头' if bearish_align else '交织'}")
print(f"   MACD信号: {'金叉' if macd_cross_up else '死叉' if macd_cross_down else '持续'}")
print(f"   量比(5/20):{vol_ratio:.2f} ({'放量' if vol_ratio>1.3 else '缩量' if vol_ratio<0.7 else '正常'})")

# -------- 5. 关键价位 --------
print(f"\n关键价位:")
print(f"   当前价: {latest_close:.2f}")
print(f"   短期阻力(20日高): {resistance_short:.2f}")
print(f"   短期支撑(20日低): {support_short:.2f}")
print(f"   中期阻力(60日高): {month_high_60:.2f}")
print(f"   中期支撑(60日低): {month_low_60:.2f}")
print(f"   季度阻力(120日高): {quarter_high:.2f}")
print(f"   季度支撑(120日低): {quarter_low:.2f}")

# -------- 6. 综合评分 --------
score = 0
signals = []

if close.iloc[-1] > ma20_v:
    score += 10; signals.append("站上MA20 +10")
if close.iloc[-1] > ma60_v:
    score += 10; signals.append("站上MA60 +10")
if bullish_align:
    score += 10; signals.append("均线多头 +10")
elif not bearish_align and close.iloc[-1] > ma10_v:
    score += 5; signals.append("短线偏多 +5")

rsi = df_daily['RSI14'].iloc[-1]
if 40 <= rsi <= 70:
    score += 10; signals.append(f"RSI健康({rsi:.0f}) +10")
elif 30 <= rsi < 40:
    score += 5; signals.append(f"RSI偏低({rsi:.0f}) +5")

if df_daily['MACD_BAR'].iloc[-1] > 0:
    score += 8; signals.append("MACD红柱 +8")
    if df_daily['MACD_BAR'].iloc[-1] > df_daily['MACD_BAR'].iloc[-2]:
        score += 4; signals.append("MACD柱放大 +4")
elif df_daily['MACD_BAR'].iloc[-1] > df_daily['MACD_BAR'].iloc[-2]:
    score += 3; signals.append("MACD绿柱缩短 +3")

if 0.8 <= vol_ratio <= 2.0:
    score += 10; signals.append("量能正常 +10")
elif vol_ratio > 2.0:
    score += 5; signals.append("异常放量 +5")
if df_daily['OBV'].iloc[-1] > df_daily['OBV'].iloc[-20:].mean():
    score += 10; signals.append("OBV强势 +10")

price_position_60d = (close.iloc[-1] - month_low_60) / (month_high_60 - month_low_60) * 100 if month_high_60 != month_low_60 else 50
if 30 <= price_position_60d <= 70:
    score += 15; signals.append(f"价格中枢({price_position_60d:.0f}%) +15")
elif price_position_60d < 30:
    score += 20; signals.append(f"低位区间({price_position_60d:.0f}%) +20")
else:
    score += 5; signals.append(f"高位区间({price_position_60d:.0f}%) +5")

if ret_5d > 0 and ret_10d > 0:
    score += 5; signals.append("短期趋势向上 +5")

print(f"\n综合评分: {score}/100")
for s in signals:
    print(f"   {s}")

if score >= 80:
    grade = "A 强势看多"
elif score >= 60:
    grade = "B 偏多"
elif score >= 40:
    grade = "C 震荡"
elif score >= 20:
    grade = "D 偏空"
else:
    grade = "E 弱势看空"
print(f"   技术评级: {grade}")

# -------- 7. 周线/月线背景 --------
print(f"\n大周期背景:")
if len(df_weekly) > 4:
    w_close = df_weekly['收盘'].iloc[-1]
    w_ma20 = df_weekly['收盘'].rolling(20).mean().iloc[-1] if len(df_weekly) >= 20 else df_weekly['收盘'].mean()
    w_trend = "周线多头" if w_close > w_ma20 else "周线空头"
    print(f"   周线: 收盘{w_close:.2f}  MA20:{w_ma20:.2f}  {w_trend}")
if len(df_monthly) > 2:
    m_close = df_monthly['收盘'].iloc[-1]
    m_ma10 = df_monthly['收盘'].rolling(10).mean().iloc[-1] if len(df_monthly) >= 10 else df_monthly['收盘'].mean()
    print(f"   月线: 收盘{m_close:.2f}  MA10:{m_ma10:.2f}")

# -------- 8. 近5日交易记录 --------
print(f"\n近5日交易记录:")
last5 = df_daily.tail(5)
for idx, row in last5.iterrows():
    bar_type = "阳线" if row['收盘'] >= row['开盘'] else "阴线"
    print(f"   {idx.strftime('%m-%d')} | {bar_type} | O:{row['开盘']:.2f} H:{row['最高']:.2f} L:{row['最低']:.2f} C:{row['收盘']:.2f} | 换手:{row['换手率']:.1f}%")

# -------- 9. 短期预判 --------
print(f"\n短期预判 (1-5日):")

prediction_factors = []
if close.iloc[-1] > ma5_v and ma5_v > ma10_v:
    prediction_factors.append(("多", "MA5>MA10短线强势"))
elif close.iloc[-1] > ma5_v:
    prediction_factors.append(("偏多", "站上MA5"))
else:
    prediction_factors.append(("偏空", "受MA5压制"))

if macd_cross_up:
    prediction_factors.append(("多", "MACD刚金叉"))
elif df_daily['MACD_BAR'].iloc[-1] > 0:
    prediction_factors.append(("多", "MACD多头持续"))

if rsi < 30:
    prediction_factors.append(("多", "RSI超卖反弹"))
elif rsi > 80:
    prediction_factors.append(("空", "RSI超买"))

if vol_ratio > 1.5:
    if close.iloc[-1] > close.iloc[-2]:
        prediction_factors.append(("多", "放量上涨"))
    else:
        prediction_factors.append(("空", "放量下跌"))

for direction, reason in prediction_factors:
    icon = "+" if direction == "多" else "-" if direction == "空" else "~"
    print(f"   {icon} {reason}")

up_count = sum(1 for d, _ in prediction_factors if d == "多")
down_count = sum(1 for d, _ in prediction_factors if d == "空")

if up_count > down_count + 1:
    bias = "短期看涨"
elif down_count > up_count + 1:
    bias = "短期看跌"
else:
    bias = "短期震荡"

print(f"\n   -> 综合判断: {bias}")
print(f"   -> 预计波动区间: {max(quarter_low, close.iloc[-1]-df_daily['ATR14'].iloc[-1]*2):.2f} ~ {min(quarter_high, close.iloc[-1]+df_daily['ATR14'].iloc[-1]*2):.2f}")
print(f"   -> 止损参考: {min(support_short, close.iloc[-1]-df_daily['ATR14'].iloc[-1]*2.5):.2f}")
print(f"   -> 第一目标: {resistance_short:.2f}")
print(f"   -> 第二目标: {month_high_60:.2f}")

# -------- 10. 绘制走势图 --------
print(f"\n正在生成走势图...")

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

fig = plt.figure(figsize=(20, 14))
gs = fig.add_gridspec(6, 1, height_ratios=[3, 1.2, 1, 1, 1, 1], hspace=0.08)

plot_days = 90
plot_df = df_daily.tail(plot_days)

colors = {
    'bg': '#0d1117',
    'grid': '#21262d',
    'text': '#c9d1d9',
    'red': '#ff4444',
    'green': '#00c853',
    'blue': '#58a6ff',
    'orange': '#f0883e',
    'purple': '#bc8cff',
    'yellow': '#d2991d',
}

fig.patch.set_facecolor(colors['bg'])

# ---- K线主图 ----
ax1 = fig.add_subplot(gs[0])
ax1.set_facecolor(colors['bg'])
ax1.grid(True, alpha=0.2, color=colors['grid'])
ax1.tick_params(colors=colors['text'], labelsize=8)

for i, (idx, row) in enumerate(plot_df.iterrows()):
    color = colors['red'] if row['收盘'] >= row['开盘'] else colors['green']
    body_bottom = min(row['开盘'], row['收盘'])
    body_top = max(row['开盘'], row['收盘'])
    ax1.bar(i, body_top - body_bottom, bottom=body_bottom, color=color, width=0.6, alpha=0.9)
    ax1.plot([i, i], [row['最低'], row['最高']], color=color, linewidth=0.8)

for ma, clr, lw in [('MA5', colors['yellow'], 0.8), ('MA10', colors['blue'], 0.8),
                     ('MA20', colors['purple'], 1.0), ('MA60', colors['orange'], 1.0)]:
    ax1.plot(range(len(plot_df)), plot_df[ma].values, color=clr, linewidth=lw, alpha=0.8, label=ma)

ax1.plot(range(len(plot_df)), plot_df['BOLL_UP'].values, color=colors['text'],
         linewidth=0.4, alpha=0.4, linestyle='--')
ax1.plot(range(len(plot_df)), plot_df['BOLL_DN'].values, color=colors['text'],
         linewidth=0.4, alpha=0.4, linestyle='--')
ax1.fill_between(range(len(plot_df)), plot_df['BOLL_DN'].values,
                 plot_df['BOLL_UP'].values, alpha=0.03, color='white')

for level, label, lc in [(resistance_short, f'R1:{resistance_short:.2f}', colors['red']),
                           (support_short, f'S1:{support_short:.2f}', colors['green']),
                           (month_high_60, f'MH:{month_high_60:.2f}', '#ff6666'),
                           (month_low_60, f'ML:{month_low_60:.2f}', '#66ff66')]:
    ax1.axhline(y=level, color=lc, linewidth=0.5, alpha=0.5, linestyle=':')
    ax1.text(len(plot_df) - 1, level, f' {label}', color=lc, fontsize=7, va='center', alpha=0.8)

ax1.legend(loc='upper left', fontsize=7, facecolor=colors['bg'],
           labelcolor=colors['text'], edgecolor=colors['grid'])
ax1.set_ylabel('Price', color=colors['text'], fontsize=9)
ax1.set_title(f'{name}({code}) Daily Chart | Close:{latest_close:.2f} | Score:{score}/100 {grade}',
              color=colors['text'], fontsize=12, fontweight='bold', pad=10)

x_ticks_idx = list(range(0, len(plot_df), max(1, len(plot_df)//10)))
x_ticks_labels = [plot_df.index[i].strftime('%m-%d') for i in x_ticks_idx]
ax1.set_xticks(x_ticks_idx)
ax1.set_xticklabels(x_ticks_labels, fontsize=7)
ax1.set_xlim(-1, len(plot_df))

# ---- 成交量 ----
ax2 = fig.add_subplot(gs[1], sharex=ax1)
ax2.set_facecolor(colors['bg'])
ax2.grid(True, alpha=0.2, color=colors['grid'])
ax2.tick_params(colors=colors['text'], labelsize=7)

vol_scale = 1e4
for i, (idx, row) in enumerate(plot_df.iterrows()):
    color = colors['red'] if row['收盘'] >= row['开盘'] else colors['green']
    ax2.bar(i, row['成交量'] / vol_scale, color=color, width=0.6, alpha=0.6)
ax2.plot(range(len(plot_df)), plot_df['VOL_MA5'].values / vol_scale, color=colors['yellow'],
         linewidth=0.6, label='VOL_MA5')
ax2.plot(range(len(plot_df)), plot_df['VOL_MA20'].values / vol_scale, color=colors['purple'],
         linewidth=0.6, label='VOL_MA20')
ax2.set_ylabel('Vol(10k)', color=colors['text'], fontsize=8)
ax2.legend(loc='upper left', fontsize=6, facecolor=colors['bg'],
           labelcolor=colors['text'], edgecolor=colors['grid'])

# ---- MACD ----
ax3 = fig.add_subplot(gs[2], sharex=ax1)
ax3.set_facecolor(colors['bg'])
ax3.grid(True, alpha=0.2, color=colors['grid'])
ax3.tick_params(colors=colors['text'], labelsize=7)

for i, (idx, row) in enumerate(plot_df.iterrows()):
    bar_val = row['MACD_BAR']
    color = colors['red'] if bar_val >= 0 else colors['green']
    ax3.bar(i, bar_val, color=color, width=0.6, alpha=0.7)
ax3.plot(range(len(plot_df)), plot_df['MACD_DIF'].values, color=colors['blue'], linewidth=0.8, label='DIF')
ax3.plot(range(len(plot_df)), plot_df['MACD_DEA'].values, color=colors['orange'], linewidth=0.8, label='DEA')
ax3.axhline(y=0, color=colors['text'], linewidth=0.3, alpha=0.5)
ax3.set_ylabel('MACD', color=colors['text'], fontsize=8)
ax3.legend(loc='upper left', fontsize=6, facecolor=colors['bg'],
           labelcolor=colors['text'], edgecolor=colors['grid'])

# ---- RSI ----
ax4 = fig.add_subplot(gs[3], sharex=ax1)
ax4.set_facecolor(colors['bg'])
ax4.grid(True, alpha=0.2, color=colors['grid'])
ax4.tick_params(colors=colors['text'], labelsize=7)

ax4.plot(range(len(plot_df)), plot_df['RSI14'].values, color=colors['blue'], linewidth=0.8, label='RSI14')
ax4.axhline(y=70, color=colors['red'], linewidth=0.4, alpha=0.5, linestyle='--')
ax4.axhline(y=30, color=colors['green'], linewidth=0.4, alpha=0.5, linestyle='--')
ax4.axhline(y=50, color=colors['text'], linewidth=0.3, alpha=0.3)
ax4.fill_between(range(len(plot_df)), 70, plot_df['RSI14'].values, alpha=0.1, color=colors['red'])
ax4.fill_between(range(len(plot_df)), 30, plot_df['RSI14'].values, alpha=0.1, color=colors['green'],
                  where=plot_df['RSI14'].values < 30)
ax4.set_ylabel('RSI', color=colors['text'], fontsize=8)
ax4.set_ylim(0, 100)
ax4.legend(loc='upper left', fontsize=6, facecolor=colors['bg'],
           labelcolor=colors['text'], edgecolor=colors['grid'])

# ---- KDJ ----
ax5 = fig.add_subplot(gs[4], sharex=ax1)
ax5.set_facecolor(colors['bg'])
ax5.grid(True, alpha=0.2, color=colors['grid'])
ax5.tick_params(colors=colors['text'], labelsize=7)

ax5.plot(range(len(plot_df)), plot_df['KDJ_K'].values, color=colors['blue'], linewidth=0.7, label='K')
ax5.plot(range(len(plot_df)), plot_df['KDJ_D'].values, color=colors['orange'], linewidth=0.7, label='D')
ax5.plot(range(len(plot_df)), plot_df['KDJ_J'].values, color=colors['purple'], linewidth=0.7, label='J')
ax5.axhline(y=80, color=colors['red'], linewidth=0.4, alpha=0.5, linestyle='--')
ax5.axhline(y=20, color=colors['green'], linewidth=0.4, alpha=0.5, linestyle='--')
ax5.set_ylabel('KDJ', color=colors['text'], fontsize=8)
ax5.legend(loc='upper left', fontsize=6, facecolor=colors['bg'],
           labelcolor=colors['text'], edgecolor=colors['grid'])

# ---- 价格位置 ----
ax6 = fig.add_subplot(gs[5], sharex=ax1)
ax6.set_facecolor(colors['bg'])
ax6.grid(True, alpha=0.2, color=colors['grid'])
ax6.tick_params(colors=colors['text'], labelsize=7)

price_pos = (close.iloc[-1] - month_low_60) / (month_high_60 - month_low_60) * 100 if month_high_60 != month_low_60 else 50
ax6.barh(0, price_pos, color=colors['blue'], height=0.4, alpha=0.8)
ax6.barh(0, 100, color=colors['grid'], height=0.4, alpha=0.3)
ax6.set_xlim(0, 100)
ax6.set_yticks([])
ax6.set_xlabel('60-Day Price Position(%)', color=colors['text'], fontsize=8)

ax6.text(price_pos, 0, f'{price_pos:.0f}%', color='white', fontsize=8,
         va='center', ha='center', fontweight='bold')
ax6.text(0, -0.6, f'L:{month_low_60:.2f}', color=colors['green'], fontsize=7, va='top')
ax6.text(100, -0.6, f'H:{month_high_60:.2f}', color=colors['red'], fontsize=7, va='top', ha='right')

# 标注预判区间
ax1.annotate('', xy=(len(plot_df) + 2, support_short),
             xytext=(len(plot_df) + 2, resistance_short),
             arrowprops=dict(arrowstyle='<->', color=colors['yellow'], lw=1, alpha=0.5))
ax1.annotate(f'{latest_close}', xy=(len(plot_df) - 1, latest_close),
             xytext=(len(plot_df) - 1, latest_close + df_daily['ATR14'].iloc[-1]),
             fontsize=8, color='white', fontweight='bold', ha='center',
             arrowprops=dict(arrowstyle='->', color='white', lw=0.8))

# 保存到D盘
output_dir = r'C:\Users\34077\Desktop\11股票分析\宝胜股份_600973'
import os
os.makedirs(output_dir, exist_ok=True)
today_str = datetime.datetime.now().strftime('%Y-%m-%d')
output_path = os.path.join(output_dir, f'{today_str}_走势图.png')
plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=colors['bg'])
plt.close()

print(f"Chart saved: {output_path}")

# -------- 11. 月度情景分析 --------
print(f"\n{'='*60}")
print(f"Monthly Scenario Analysis")
print(f"{'='*60}")

atr_monthly = df_daily['ATR14'].iloc[-1] * 2

print(f"""
  BULLISH (prob ~30%):
     - Trigger: Grid equipment sector fund inflow + breakout above {resistance_short:.2f}
     - Target: {resistance_short + atr_monthly:.2f} ~ {month_high_60 + atr_monthly:.2f}
     - Gain: +{(resistance_short/latest_close - 1)*100:.1f}% ~ +{(month_high_60/latest_close - 1)*100:.1f}%

  NEUTRAL (prob ~45%):
     - Range: {support_short:.2f} - {resistance_short:.2f} consolidation
     - Strategy: Hold, wait for breakout

  BEARISH (prob ~25%):
     - Trigger: Break below {min(support_short, ma60_v):.2f} (MA60/support)
     - Stop: {min(support_short, ma60_v) - df_daily['ATR14'].iloc[-1]*0.5:.2f}
     - Max loss: {(latest_close - (min(support_short, ma60_v) - df_daily['ATR14'].iloc[-1]*0.5)):.2f}/share
""")

print(f"ADVICE:")
print(f"   Score {score}/100 -> Grade {grade}")
if score >= 60:
    print(f"   TRADEABLE, suggested position: 40-60%")
    print(f"   -> Entry zone: {support_short:.2f} ~ {latest_close:.2f}")
    print(f"   -> Stop at: {min(support_short, ma60_v) - df_daily['ATR14'].iloc[-1]*0.3:.2f}")
elif score >= 40:
    print(f"   WAIT for signal, suggested position: 20-30% test")
    print(f"   -> Wait for pullback to {support_short:.2f} or volume breakout above {resistance_short:.2f}")
else:
    print(f"   AVOID for now, wait for technical improvement")

print(f"\nAnalysis complete.")
