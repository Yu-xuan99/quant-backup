#!/usr/bin/env python3
"""
专业趋势线分析图 - 自动识别趋势线/支撑阻力/通道 + 未来走势推演
纯 matplotlib 实现，完全控制绘制细节
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib.lines import Line2D
import matplotlib.ticker as mticker
from datetime import datetime, timedelta
import requests
import os
import sys

# ---- 字体 ----
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- 分析标的 ----
STOCKS = {
    '600973': {
        'name': '宝胜股份', 'cost': 7.94, 'capital': 2382,
        'events': {
            '2026-05-12': '主力+7701万\n买入信号',
            '2026-05-13': '← 你的买点\n7.94',
            '2026-05-14': '砸盘\n-1.12亿',
            '2026-05-15': '继续砸\n恐慌低点',
        }
    },
    '603181': {
        'name': '皇马科技', 'cost': None, 'capital': 3062,
        'events': {
            '2026-05-08': '洗盘开始',
            '2026-05-13': '主力低吸',
            '2026-05-20': '突破!\n+5.37%',
        }
    },
}


def fetch_kline(code, count=150):
    """腾讯K线"""
    market = 'sz' if code.startswith(('0', '3')) else 'sh'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,{count},qfq"
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}, timeout=10)
        data = r.json()
        if data.get('code') == 0:
            return data['data'][f'{market}{code}'].get('qfqday', [])
    except Exception as e:
        print(f"  K线获取失败: {e}")
    return None


# ============================================================
#  核心算法：波段高低点检测
# ============================================================
def find_swing_points(highs, lows, window=5):
    """
    找出波段高点和低点
    window: 左右各看N根K线，局部极值
    返回: (swing_highs_idx, swing_lows_idx)
    """
    n = len(highs)
    sh, sl = [], []

    for i in range(window, n - window):
        # 波段高点：比左右各window根K线的最高价都高
        is_high = True
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            if highs[j] >= highs[i]:
                is_high = False
                break
        if is_high:
            # 去重：不跟上一个太近
            if not sh or i - sh[-1] >= window:
                sh.append(i)

        # 波段低点：比左右各window根K线的最低价都低
        is_low = True
        for j in range(i - window, i + window + 1):
            if j == i:
                continue
            if lows[j] <= lows[i]:
                is_low = False
                break
        if is_low:
            if not sl or i - sl[-1] >= window:
                sl.append(i)

    return sh, sl


# ============================================================
#  核心算法：自动趋势线拟合
# ============================================================
def fit_trend_lines(swing_points, values, is_high=True):
    """
    从波段点中找出最优趋势线
    使用RANSAC思想：尝试多组点对，找经过最多点的线
    返回: [(slope, intercept, start_idx, end_future_idx, strength)], 按相关性排序
    """
    if len(swing_points) < 2:
        return []

    lines = []
    idx_arr = np.array(swing_points)
    val_arr = np.array([values[i] for i in swing_points])

    # 尝试所有可能的点对组合（最近的点优先）
    for i in range(len(swing_points)):
        for j in range(i + 1, len(swing_points)):
            p1_idx, p2_idx = idx_arr[i], idx_arr[j]
            p1_val, p2_val = val_arr[i], val_arr[j]

            # 斜率
            slope = (p2_val - p1_val) / (p2_idx - p1_idx)
            intercept = p1_val - slope * p1_idx

            # 判断趋势方向
            if is_high:
                # 下跌趋势线连接高点，斜率应为负
                if slope > 0:
                    continue
            else:
                # 上涨趋势线连接低点，斜率应为正
                if slope < 0:
                    continue

            # 计算这条线的"强度"：有多少其他波段点接近这条线
            tolerance = (max(val_arr) - min(val_arr)) * 0.03  # 3%容差
            touch_count = 0
            deviations = []
            for k, (pi, pv) in enumerate(zip(idx_arr, val_arr)):
                line_val = slope * pi + intercept
                dev = abs(pv - line_val)
                deviations.append(dev)
                if dev < tolerance:
                    touch_count += 1

            # 不能穿越K线（关键约束）
            # 下跌趋势线所有价格都应在线上方（或接近线），上涨趋势线所有价格都应在下方
            all_values = np.array(values)
            all_idx = np.arange(len(values))
            line_values_all = slope * all_idx + intercept

            if is_high:
                # 价格应该在趋势线下方（趋势线是压力）
                cross_count = np.sum(all_values > line_values_all + tolerance * 2)
                cross_ratio = cross_count / len(values)
            else:
                # 价格应该在趋势线上方（趋势线是支撑）
                cross_count = np.sum(all_values < line_values_all - tolerance * 2)
                cross_ratio = cross_count / len(values)

            # 交点不能太多
            if cross_ratio > 0.15:
                continue

            # 综合评分
            avg_dev = np.mean(deviations) if deviations else 999
            strength = touch_count * 2 - avg_dev / (max(val_arr) - min(val_arr)) * 10 - cross_ratio * 20
            strength = max(0, strength)

            lines.append({
                'slope': slope,
                'intercept': intercept,
                'start_idx': p1_idx,
                'p1': (p1_idx, p1_val),
                'p2': (p2_idx, p2_val),
                'touch_count': touch_count,
                'strength': strength,
                'avg_deviation': avg_dev,
                'cross_ratio': cross_ratio,
            })

    # 去重：合并相似的线
    lines.sort(key=lambda x: x['strength'], reverse=True)
    merged = []
    for l in lines:
        is_dup = False
        for m in merged:
            slope_diff = abs(l['slope'] - m['slope'])
            int_diff = abs(l['intercept'] - m['intercept']) / max(abs(m['intercept']), 1)
            if slope_diff < 0.001 and int_diff < 0.03:
                is_dup = True
                break
        if not is_dup:
            merged.append(l)

    return merged[:3]  # 最多3条线


# ============================================================
#  支撑阻力位识别
# ============================================================
def find_sr_levels(highs, lows, closes, volumes, n_recent=60):
    """找水平支撑阻力位"""
    levels = []

    recent_h = highs[-n_recent:]
    recent_l = lows[-n_recent:]
    recent_c = closes[-n_recent:]
    price_range = max(recent_h) - min(recent_l)

    # 1. 近期波段高低点
    sh, sl = find_swing_points(highs, lows, window=3)

    for idx in sh:
        if idx >= len(highs) - n_recent:
            levels.append({'price': highs[idx], 'type': 'resistance', 'source': f'波段高点',
                           'strength': 3, 'idx': idx})

    for idx in sl:
        if idx >= len(lows) - n_recent:
            levels.append({'price': lows[idx], 'type': 'support', 'source': f'波段低点',
                           'strength': 3, 'idx': idx})

    # 2. 20日/60日最高最低
    h20 = max(highs[-20:])
    l20 = min(lows[-20:])
    levels.append({'price': h20, 'type': 'resistance', 'source': '20日高点', 'strength': 4, 'idx': -1})
    levels.append({'price': l20, 'type': 'support', 'source': '20日低点', 'strength': 4, 'idx': -1})

    # 3. 当前价格位置的50% / 61.8% 斐波那契
    h60 = max(highs[-60:])
    l60 = min(lows[-60:])
    fib_range = h60 - l60
    for fib_pct, fib_name in [(0.382, '38.2%'), (0.5, '50%'), (0.618, '61.8%'), (0.786, '78.6%')]:
        if closes[-1] < h60 and closes[-1] > l60:
            price = h60 - fib_range * fib_pct
            ptype = 'resistance' if price > closes[-1] else 'support'
            levels.append({'price': price, 'type': ptype, 'source': f'斐波那契{fib_name}',
                           'strength': 2, 'idx': -1})

    # 4. 整数关口
    current = closes[-1]
    step = 0.5 if current < 20 else 1.0 if current < 50 else 2.0
    for base in np.arange(min(recent_l) - step, max(recent_h) + step, step):
        base = round(base, 1)
        if abs(base - current) / current < 0.15:  # 15%范围内
            ptype = 'resistance' if base > current else 'support'
            # 检查是否已有相近的水平
            dup = False
            for l in levels:
                if abs(l['price'] - base) / max(base, 0.1) < 0.01:
                    dup = True
                    break
            if not dup:
                levels.append({'price': base, 'type': ptype, 'source': '整数关口', 'strength': 1, 'idx': -1})

    # 合并相近的水平
    levels.sort(key=lambda x: x['price'])
    merged = []
    for l in levels:
        if not merged:
            merged.append(l)
            continue
        last = merged[-1]
        if abs(l['price'] - last['price']) < price_range * 0.02:
            # 合并，保留强度高的
            if l['strength'] > last['strength']:
                merged[-1] = l
        else:
            merged.append(l)

    return merged


# ============================================================
#  启动点检测
# ============================================================
def find_launch_point(swing_lows, lows, closes, volumes, window=60):
    """
    找最近一轮行情的启动点
    特征: 波段最低点 + 之后放量回升 + 不再创新低
    """
    if len(swing_lows) < 2:
        return None

    n = len(closes)
    recent_sl = [s for s in swing_lows if s >= n - window]

    if not recent_sl:
        return None

    # 找最近的最低波段低点
    lowest_idx = min(recent_sl, key=lambda i: lows[i])

    # 验证: 启动点后应有放量
    if lowest_idx < n - 3:
        post_vol = np.mean(volumes[lowest_idx:])
        pre_vol = np.mean(volumes[max(0, lowest_idx-10):lowest_idx]) if lowest_idx > 10 else post_vol
        vol_ratio = post_vol / max(pre_vol, 1)

        # 启动点后价格应回升
        post_low = min(lows[lowest_idx:])
        if post_low >= lows[lowest_idx] and vol_ratio > 0.8:
            return {'idx': lowest_idx, 'price': lows[lowest_idx],
                    'vol_ratio': vol_ratio, 'type': '底部启动'}

    return None


def find_breakout_points(closes, highs, swing_highs, ma20, ma60, volumes, window=60):
    """找突破点: 放量突破MA20/MA60 或 突破前高"""
    n = len(closes)
    breakouts = []

    for i in range(max(5, n - window), n):
        # 突破MA20且放量
        if closes[i] > ma20[i] and closes[i-1] <= ma20[i-1]:
            vr = volumes[i] / np.mean(volumes[max(0,i-10):i]) if i >= 10 else 1
            if vr > 1.2:
                breakouts.append({'idx': i, 'price': closes[i], 'type': '突破MA20', 'strength': 3})

        # 突破前一个波段高点
        prev_highs = [h for h in swing_highs if h < i]
        if prev_highs:
            prev_h = prev_highs[-1]
            if closes[i] > highs[prev_h] and closes[i-1] <= highs[prev_h]:
                breakouts.append({'idx': i, 'price': closes[i], 'type': '突破前高', 'strength': 5})

    # 去重相近的突破点
    filtered = []
    for b in sorted(breakouts, key=lambda x: x['idx']):
        if not filtered or b['idx'] - filtered[-1]['idx'] >= 3:
            filtered.append(b)
        elif b['strength'] > filtered[-1]['strength']:
            filtered[-1] = b

    return filtered[-3:]  # 最近3个


def calc_fib_targets(highs, lows, closes, swing_highs, swing_lows):
    """
    斐波那契目标位计算
    取最近一轮完整波段(低→高 或 高→低)做扩展
    """
    n = len(closes)
    targets = []

    # 找最近的一个完整上升波段: 波段低点 → 波段高点
    if len(swing_lows) >= 1 and len(swing_highs) >= 1:
        recent_sl = [s for s in swing_lows if s >= n - 90]
        recent_sh = [s for s in swing_highs if s >= n - 90]

        if recent_sl and recent_sh:
            low_idx = max(recent_sl, key=lambda i: lows[i] if i < max(recent_sh) else -999)
            # 找低点之后的最高点
            later_highs = [h for h in recent_sh if h > low_idx]
            if later_highs:
                high_idx = max(later_highs, key=lambda i: highs[i])
                swing_low_price = lows[low_idx]
                swing_high_price = highs[high_idx]
                fib_range = swing_high_price - swing_low_price

                if fib_range > 0:
                    for ext, ext_name, ext_color in [
                        (1.272, '127.2%', '#FFD740'),
                        (1.618, '161.8%', '#FF6E40'),
                        (2.000, '200%', '#FF3D00'),
                    ]:
                        target = swing_low_price + fib_range * ext
                        targets.append({
                            'price': target,
                            'label': f'目标{ext_name}',
                            'color': ext_color,
                            'source': f'从{swing_low_price:.2f}→{swing_high_price:.2f}扩展'
                        })

    return targets


# ============================================================
#  主绘图函数
# ============================================================
def draw_pro_chart(code, info):
    name = info['name']
    print(f"\n  {'='*50}")
    print(f"  分析 {name}({code}) ...")

    raw = fetch_kline(code, 150)
    if not raw:
        print("    无数据")
        return

    # 解析
    dates_str = [k[0] for k in raw]
    date_dt = [datetime.strptime(d, '%Y-%m-%d') for d in dates_str]
    opens = np.array([float(k[1]) for k in raw])
    closes = np.array([float(k[2]) for k in raw])
    highs = np.array([float(k[3]) for k in raw])
    lows = np.array([float(k[4]) for k in raw])
    volumes = np.array([float(k[5]) * 100 for k in raw])
    n = len(closes)

    # 未来投影天数
    FUTURE_BARS = 15
    future_dates = [date_dt[-1] + timedelta(days=i) for i in range(1, FUTURE_BARS + 1)]
    all_dates = date_dt + future_dates
    future_x = np.arange(n, n + FUTURE_BARS)

    # ---- 均线 ----
    def rolling_mean(arr, period):
        result = np.full(len(arr), np.nan)
        for i in range(period - 1, len(arr)):
            result[i] = np.mean(arr[i - period + 1:i + 1])
        return result

    ma5 = rolling_mean(closes, 5)
    ma10 = rolling_mean(closes, 10)
    ma20 = rolling_mean(closes, 20)
    ma60 = rolling_mean(closes, 60)

    # ---- 波段点 ----
    sh, sl = find_swing_points(highs, lows, window=5)

    # ---- 趋势线 ----
    downtrend_lines = fit_trend_lines(sh, highs, is_high=True)   # 下跌趋势线（压力）
    uptrend_lines = fit_trend_lines(sl, lows, is_high=False)     # 上涨趋势线（支撑）

    # ---- 通道线 ----
    # 对每条趋势线找对应的通道另一侧
    channels = []
    for tl in uptrend_lines[:1]:  # 最强的上涨趋势线
        slope, intercept = tl['slope'], tl['intercept']
        # 找离这条线最远的波段高点作为通道上轨
        max_dist = 0
        best_high_idx = None
        for hi in sh:
            if hi >= tl['start_idx']:
                line_val = slope * hi + intercept
                dist = highs[hi] - line_val
                if dist > max_dist:
                    max_dist = dist
                    best_high_idx = hi
        if best_high_idx and max_dist > 0:
            ch_intercept = highs[best_high_idx] - slope * best_high_idx
            channels.append({
                'slope': slope, 'lower_intercept': intercept,
                'upper_intercept': ch_intercept,
                'type': 'up', 'width': max_dist,
                'start_idx': tl['start_idx'],
            })

    for tl in downtrend_lines[:1]:  # 最强的下跌趋势线
        slope, intercept = tl['slope'], tl['intercept']
        max_dist = 0
        best_low_idx = None
        for li in sl:
            if li >= tl['start_idx']:
                line_val = slope * li + intercept
                dist = line_val - lows[li]
                if dist > max_dist:
                    max_dist = dist
                    best_low_idx = li
        if best_low_idx and max_dist > 0:
            ch_intercept = lows[best_low_idx] - slope * best_low_idx
            channels.append({
                'slope': slope, 'upper_intercept': intercept,
                'lower_intercept': ch_intercept,
                'type': 'down', 'width': max_dist,
                'start_idx': tl['start_idx'],
            })

    # ---- 支撑阻力 ----
    sr_levels = find_sr_levels(highs, lows, closes, volumes)

    # ---- 启动点 / 突破点 / 目标位 ----
    launch_pt = find_launch_point(sl, lows, closes, volumes)
    breakout_pts = find_breakout_points(closes, highs, sh, ma20, ma60, volumes)
    fib_targets = calc_fib_targets(highs, lows, closes, sh, sl)

    # ---- 止损位 ----
    stop_loss = None
    if info.get('cost'):
        # 技术止损: 取最近波段低点下方1%
        if sl:
            recent_sl_val = min(lows[i] for i in sl if i >= n - 30)
            tech_stop = recent_sl_val * 0.99
        else:
            tech_stop = info['cost'] * 0.98
        # 取成本-2%和技术止损的较低者
        cost_stop = info['cost'] * 0.98
        stop_loss = min(cost_stop, tech_stop) if tech_stop else cost_stop
    elif sl:
        recent_sl_val = min(lows[i] for i in sl if i >= n - 30)
        stop_loss = recent_sl_val * 0.99

    # ---- MACD ----
    ema12 = pd_ema(closes, 12)
    ema26 = pd_ema(closes, 26)
    dif = ema12 - ema26
    dea = pd_ema(dif, 9)
    macd_bar = 2 * (dif - dea)

    # ---- RSI ----
    rsi = compute_rsi(closes, 14)

    # ---- KDJ ----
    k_val, d_val, j_val = compute_kdj(highs, lows, closes, 9)

    # ============================================================
    #  创建图表
    # ============================================================
    fig = plt.figure(figsize=(20, 14), facecolor='#1a1a2e')
    gs = fig.add_gridspec(6, 1, height_ratios=[3.5, 0.8, 1.2, 1.0, 1.0, 1.2],
                          hspace=0.05, left=0.04, right=0.96, top=0.94, bottom=0.04)

    ax_main = fig.add_subplot(gs[0])     # K线主图
    ax_vol = fig.add_subplot(gs[1])      # 成交量
    ax_macd = fig.add_subplot(gs[2])     # MACD
    ax_rsi = fig.add_subplot(gs[3])      # RSI
    ax_kdj = fig.add_subplot(gs[4])      # KDJ
    ax_info = fig.add_subplot(gs[5])     # 信息面板

    # 深色主题
    bg_color = '#1a1a2e'
    grid_color = '#2a2a4a'
    text_color = '#c0c0d0'
    for ax in [ax_main, ax_vol, ax_macd, ax_rsi, ax_kdj]:
        ax.set_facecolor(bg_color)
        ax.grid(True, color=grid_color, linestyle=':', linewidth=0.5, alpha=0.6)
        ax.tick_params(colors=text_color, labelsize=8)
        ax.yaxis.label.set_color(text_color)

    # ============================================================
    #  主图: K线 + 均线 + 趋势线 + 通道 + 支撑阻力
    # ============================================================
    x = np.arange(n)

    # K线
    bar_width = 0.6
    for i in range(n):
        color = '#ef5350' if closes[i] >= opens[i] else '#26a69a'
        ax_main.plot([i, i], [lows[i], highs[i]], color=color, linewidth=0.8)
        body_bottom = min(opens[i], closes[i])
        body_height = abs(closes[i] - opens[i])
        ax_main.bar(i, body_height, bar_width, bottom=body_bottom, color=color,
                    edgecolor=color, linewidth=0.3, alpha=0.9)

    # 均线
    ax_main.plot(x, ma5, color='#FFB74D', linewidth=0.8, label='MA5', alpha=0.9)
    ax_main.plot(x, ma10, color='#64B5F6', linewidth=0.8, label='MA10', alpha=0.9)
    ax_main.plot(x, ma20, color='#E57373', linewidth=1.0, label='MA20', alpha=0.9)
    ax_main.plot(x, ma60, color='#81C784', linewidth=1.0, label='MA60', alpha=0.9)

    # 提前获取Y范围（后续标注需要）
    y_min, y_max = ax_main.get_ylim()
    y_range = y_max - y_min

    # ---- 趋势线 (延伸到未来) ----
    extended_x = np.arange(n + FUTURE_BARS)

    # 上涨趋势线（支撑）- 绿色虚线
    for rank, tl in enumerate(uptrend_lines[:2]):
        line_vals = tl['slope'] * extended_x + tl['intercept']
        alpha = 0.9 if rank == 0 else 0.5
        lw = 2.5 if rank == 0 else 1.2
        label = '上升趋势线(支撑)' if rank == 0 else None
        ax_main.plot(extended_x, line_vals, color='#00E676', linewidth=lw,
                     linestyle='--', alpha=alpha, label=label)
        if rank == 0:
            # 预测区标签 - 显示未来价格
            for future_day in [5, 10, 15]:
                fx = n + future_day
                fy = tl['slope'] * fx + tl['intercept']
                if 0 < fx < n + FUTURE_BARS:
                    ax_main.scatter(fx, fy, marker='o', color='#00E676', s=20, alpha=0.8)
                    ax_main.annotate(f'{fy:.2f}', xy=(fx, fy),
                                    xytext=(fx, fy - y_range * 0.02),
                                    fontsize=6, color='#00E676', ha='center', va='top')
            # 趋势线标签
            ax_main.text(n + FUTURE_BARS - 0.5, tl['slope'] * (n + FUTURE_BARS - 0.5) + tl['intercept'],
                        f'支撑 ↗', fontsize=8, color='#00E676', alpha=0.9,
                        fontweight='bold', va='center', ha='right')

    # 下跌趋势线（压力）- 红色虚线
    for rank, tl in enumerate(downtrend_lines[:2]):
        line_vals = tl['slope'] * extended_x + tl['intercept']
        alpha = 0.9 if rank == 0 else 0.5
        lw = 2.5 if rank == 0 else 1.2
        label = '下降趋势线(压力)' if rank == 0 else None
        ax_main.plot(extended_x, line_vals, color='#FF5252', linewidth=lw,
                     linestyle='--', alpha=alpha, label=label)
        if rank == 0:
            for future_day in [5, 10, 15]:
                fx = n + future_day
                fy = tl['slope'] * fx + tl['intercept']
                if 0 < fx < n + FUTURE_BARS:
                    ax_main.scatter(fx, fy, marker='o', color='#FF5252', s=20, alpha=0.8)
                    ax_main.annotate(f'{fy:.2f}', xy=(fx, fy),
                                    xytext=(fx, fy + y_range * 0.02),
                                    fontsize=6, color='#FF5252', ha='center', va='bottom')
            ax_main.text(n + FUTURE_BARS - 0.5, tl['slope'] * (n + FUTURE_BARS - 0.5) + tl['intercept'],
                        f'压力 ↘', fontsize=8, color='#FF5252', alpha=0.9,
                        fontweight='bold', va='center', ha='right')

    # ---- 通道 ----
    for ch in channels:
        lower_vals = ch['slope'] * extended_x + ch['lower_intercept']
        upper_vals = ch['slope'] * extended_x + ch['upper_intercept']
        ax_main.fill_between(extended_x, lower_vals, upper_vals, alpha=0.06,
                             color='#FFD700' if ch['type'] == 'up' else '#FF9800')
        ax_main.plot(extended_x, upper_vals, color='#FFD700', linewidth=0.8,
                     linestyle=':', alpha=0.5)
        prefix = '上升' if ch['type'] == 'up' else '下降'
        ax_main.annotate(f'{prefix}通道上轨', xy=(n + 3, upper_vals[-3]),
                        fontsize=7, color='#FFD700', alpha=0.6)

    # ---- 支撑阻力水平线 (加粗+右标签+延伸到预测区) ----
    sr_drawn = set()
    for sr in sr_levels:
        price_key = round(sr['price'], 2)
        if price_key in sr_drawn:
            continue
        sr_drawn.add(price_key)

        if sr['strength'] >= 3:
            is_resist = sr['type'] == 'resistance'
            color = '#FF5252' if is_resist else '#00E676'
            lw = 2.0 if sr['strength'] >= 4 else 1.2
            alpha = 0.75 if sr['strength'] >= 4 else 0.55
            style = '-' if sr['strength'] >= 4 else '--'

            # 横跨全图(含预测区)
            ax_main.axhline(y=sr['price'], color=color, linewidth=lw,
                           linestyle=style, alpha=alpha, zorder=4,
                           xmin=0, xmax=1)
            # 左侧标签
            label = f"{'压力' if is_resist else '支撑'} {sr['price']:.2f}"
            ax_main.text(1, sr['price'], f'{label}', fontsize=7,
                        color=color, alpha=alpha, va='bottom', ha='left', fontweight='bold')
            # 右侧标签延伸到预测区
            ax_main.text(n + FUTURE_BARS - 1, sr['price'],
                        f'{label} ({sr["source"]})', fontsize=7,
                        color=color, alpha=alpha, va='bottom', ha='right',
                        bbox=dict(boxstyle='round,pad=0.15', facecolor='#1a1a2e',
                                edgecolor=color, alpha=0.7))

    # ---- 斐波那契 ----
    h60 = max(highs[-60:])
    l60 = min(lows[-60:])
    fib_colors = [(0.382, '#FFD740', '38.2%'), (0.5, '#FFAB40', '50%'),
                  (0.618, '#FF6E40', '61.8%'), (0.786, '#FF3D00', '78.6%')]
    for pct, color, fib_name in fib_colors:
        price = h60 - (h60 - l60) * pct
        ax_main.axhline(y=price, color=color, linewidth=0.6, linestyle='-.', alpha=0.35)
        ax_main.text(2, price, f'Fib {fib_name} {price:.2f}', fontsize=6, color=color, alpha=0.5, va='bottom')

    # ---- 斐波那契扩展目标位 (投影到预测区) ----
    for ft in fib_targets:
        ax_main.axhline(y=ft['price'], color=ft['color'], linewidth=1.0,
                       linestyle='-', alpha=0.6)
        ax_main.text(n + FUTURE_BARS - 1, ft['price'],
                    f" {ft['label']} {ft['price']:.2f}", fontsize=7,
                    color=ft['color'], alpha=0.85, va='center', fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.15', facecolor='#1a1a2e',
                             edgecolor=ft['color'], alpha=0.8))
        ax_main.text(2, ft['price'], f'>> {ft["source"]}', fontsize=6,
                    color=ft['color'], alpha=0.5, va='bottom')

    # ---- 波段点标记 ----
    for idx in sh[-10:]:
        ax_main.scatter(idx, highs[idx], marker='v', color='#FF5252', s=40, zorder=5, alpha=0.7)
    for idx in sl[-10:]:
        ax_main.scatter(idx, lows[idx], marker='^', color='#00E676', s=40, zorder=5, alpha=0.7)

    # ---- 启动点标记 (大圆+放射线) ----
    if launch_pt:
        lx, lp = launch_pt['idx'], launch_pt['price']
        ax_main.scatter(lx, lp, marker='o', color='#00E5FF', s=300, zorder=10,
                       edgecolors='white', linewidth=2, alpha=0.9)
        ax_main.annotate(f"启动!\n{launch_pt['type']}\n{lp:.2f}",
                        xy=(lx, lp),
                        xytext=(lx + 15, lp + y_range * 0.06),
                        fontsize=8, fontweight='bold', color='#00E5FF',
                        ha='center', va='center',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='#003344',
                                edgecolor='#00E5FF', alpha=0.9),
                        arrowprops=dict(arrowstyle='->', color='#00E5FF', lw=2.0))

    # ---- 突破点标记 ----
    for bp in breakout_pts:
        bx, bprice = bp['idx'], bp['price']
        # 画向上的箭头
        ax_main.annotate(f"{bp['type']}",
                        xy=(bx, bprice),
                        xytext=(bx, bprice - y_range * 0.05),
                        fontsize=7, fontweight='bold', color='#FFD740',
                        ha='center', va='top',
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='#222244',
                                edgecolor='#FFD740', alpha=0.85),
                        arrowprops=dict(arrowstyle='->', color='#FFD740', lw=1.5))

    # ---- 止损线 (粗红线横跨全图) ----
    if stop_loss:
        ax_main.axhline(y=stop_loss, color='#FF1744', linewidth=1.8,
                       linestyle='--', alpha=0.8, zorder=6)
        # 左侧标签
        ax_main.text(1, stop_loss, f'止损 {stop_loss:.2f}', fontsize=8,
                    color='#FF1744', fontweight='bold', va='bottom', ha='left',
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='#330000',
                            edgecolor='#FF1744', alpha=0.85))
        # 右侧标签 - 延伸到预测区
        ax_main.text(n + FUTURE_BARS - 1, stop_loss, f'止损 {stop_loss:.2f}',
                    fontsize=8, color='#FF1744', fontweight='bold', va='bottom', ha='right')

    # ---- 成本线 ----
    if info.get('cost'):
        cost = info['cost']
        ax_main.axhline(y=cost, color='#B0BEC5', linewidth=1.0, linestyle='-', alpha=0.5, zorder=5)
        ax_main.text(n + FUTURE_BARS - 1, cost, f'成本 {cost:.2f}', fontsize=7,
                    color='#B0BEC5', va='bottom', ha='right', alpha=0.8)

    # ---- 事件标注 ----
    events = info.get('events', {})
    for date_str, label in events.items():
        idx = None
        for i, d in enumerate(dates_str):
            if d.startswith(date_str):
                idx = i
                break
        if idx is not None:
            y_pos = highs[idx] + y_range * 0.03
            ax_main.annotate(label, xy=(idx, highs[idx]), xytext=(idx, y_pos + y_range * 0.05),
                            fontsize=7, fontweight='bold', color='#FFF176',
                            ha='center', va='bottom',
                            bbox=dict(boxstyle='round,pad=0.2', facecolor='#333355',
                                      edgecolor='#FFF176', alpha=0.85),
                            arrowprops=dict(arrowstyle='->', color='#FFF176', lw=1.0))

    # 当前位置虚线
    ax_main.axhline(y=closes[-1], color='white', linewidth=0.6, linestyle='--', alpha=0.3)
    ax_main.annotate(f'现价 {closes[-1]:.2f}', xy=(n - 1, closes[-1]),
                    fontsize=8, color='white', fontweight='bold', va='bottom', ha='right')

    # 未来投影区域（灰色半透明）
    ax_main.axvspan(n - 0.5, n + FUTURE_BARS - 0.5, alpha=0.08, color='#B0BEC5')
    ax_main.text(n + FUTURE_BARS / 2, y_max - y_range * 0.02, '← 预测区域 →',
                fontsize=9, color='#B0BEC5', ha='center', alpha=0.7, fontstyle='italic')

    # ---- 图例和标题 ----
    ax_main.legend(loc='upper left', fontsize=7, facecolor='#222244', edgecolor='#444466',
                  labelcolor=text_color, ncol=4)

    # 标题
    pnl_str = ''
    if info.get('cost'):
        pnl = (closes[-1] - info['cost']) / info['cost'] * 100
        pnl_str = f' | 成本:{info["cost"]:.2f} 浮盈:{pnl:+.1f}%'

    r5 = (closes[-1] / closes[-5] - 1) * 100 if n >= 5 else 0
    r20 = (closes[-1] / closes[-20] - 1) * 100 if n >= 20 else 0

    fig.suptitle(
        f'{name} {code}  现价:{closes[-1]:.2f}  5日:{r5:+.1f}%  20日:{r20:+.1f}%{pnl_str}',
        fontsize=14, fontweight='bold', color='white', y=0.98)

    # ============================================================
    #  成交量
    # ============================================================
    vol_colors = ['#ef5350' if closes[i] >= opens[i] else '#26a69a' for i in range(n)]
    ax_vol.bar(x, volumes, bar_width, color=vol_colors, alpha=0.7)
    vol_ma5 = rolling_mean(volumes, 5)
    ax_vol.plot(x, vol_ma5, color='#FFB74D', linewidth=0.8, alpha=0.7)
    ax_vol.set_ylabel('量', fontsize=8, color=text_color)
    ax_vol.tick_params(labelsize=7)

    # ============================================================
    #  MACD
    # ============================================================
    macd_colors = ['#ef5350' if v >= 0 else '#26a69a' for v in macd_bar]
    ax_macd.bar(x, macd_bar, bar_width, color=macd_colors, alpha=0.8)
    ax_macd.plot(x, dif, color='#64B5F6', linewidth=0.8, label='DIF')
    ax_macd.plot(x, dea, color='#FFB74D', linewidth=0.8, label='DEA')
    ax_macd.axhline(y=0, color='white', linewidth=0.5, alpha=0.3)
    ax_macd.legend(loc='upper left', fontsize=7, facecolor='#222244', edgecolor='#444466',
                   labelcolor=text_color)
    ax_macd.set_ylabel('MACD', fontsize=8, color=text_color)
    ax_macd.tick_params(labelsize=7)

    # ============================================================
    #  RSI
    # ============================================================
    ax_rsi.plot(x, rsi, color='#CE93D8', linewidth=0.8)
    ax_rsi.axhline(y=70, color='#FF5252', linewidth=0.6, linestyle='--', alpha=0.5)
    ax_rsi.axhline(y=30, color='#00E676', linewidth=0.6, linestyle='--', alpha=0.5)
    ax_rsi.axhline(y=50, color='white', linewidth=0.4, linestyle=':', alpha=0.3)
    ax_rsi.fill_between(x, 70, rsi, where=(rsi > 70), color='#FF5252', alpha=0.15)
    ax_rsi.fill_between(x, 30, rsi, where=(rsi < 30), color='#00E676', alpha=0.15)
    ax_rsi.set_ylabel('RSI(14)', fontsize=8, color=text_color)
    ax_rsi.set_ylim(0, 100)
    ax_rsi.tick_params(labelsize=7)

    # ============================================================
    #  KDJ
    # ============================================================
    ax_kdj.plot(x, k_val, color='#64B5F6', linewidth=0.8, label='K')
    ax_kdj.plot(x, d_val, color='#FFB74D', linewidth=0.8, label='D')
    ax_kdj.plot(x, j_val, color='#E57373', linewidth=0.8, label='J', alpha=0.7)
    ax_kdj.axhline(y=80, color='#FF5252', linewidth=0.5, linestyle='--', alpha=0.4)
    ax_kdj.axhline(y=20, color='#00E676', linewidth=0.5, linestyle='--', alpha=0.4)
    ax_kdj.axhline(y=50, color='white', linewidth=0.3, linestyle=':', alpha=0.2)
    ax_kdj.legend(loc='upper left', fontsize=7, facecolor='#222244', edgecolor='#444466',
                  labelcolor=text_color, ncol=3)
    ax_kdj.set_ylabel('KDJ(9)', fontsize=8, color=text_color)
    ax_kdj.set_ylim(0, 100)
    ax_kdj.tick_params(labelsize=7)

    # ============================================================
    #  信息面板（文字总结）
    # ============================================================
    ax_info.set_facecolor('#1a1a2e')
    ax_info.axis('off')

    # 分析总结
    lines_info = []

    # 趋势判断
    if uptrend_lines:
        best_up = uptrend_lines[0]
        lines_info.append(f"【上升趋势线】斜率+{best_up['slope']*100:.2f}%/天 | 触及{best_up['touch_count']}次波段低点 | 强度{best_up['strength']:.1f}")
        # 预测
        future_support = best_up['slope'] * (n + 5) + best_up['intercept']
        lines_info.append(f"  → 5天后支撑位: {future_support:.2f} | 10天后: {best_up['slope']*(n+10)+best_up['intercept']:.2f}")

    if downtrend_lines:
        best_down = downtrend_lines[0]
        lines_info.append(f"【下降趋势线】斜率{best_down['slope']*100:+.2f}%/天 | 触及{best_down['touch_count']}次波段高点")
        future_resist = best_down['slope'] * (n + 5) + best_down['intercept']
        lines_info.append(f"  → 5天后压力位: {future_resist:.2f} | 10天后: {best_down['slope']*(n+10)+best_down['intercept']:.2f}")

    # 通道
    if channels:
        ch = channels[0]
        lines_info.append(f"【{'上升' if ch['type']=='up' else '下降'}通道】宽度{ch['width']:.2f}元({ch['width']/closes[-1]*100:.1f}%)")

    # 关键技术位
    current = closes[-1]
    nearest_support = None
    nearest_resist = None
    for sr in sr_levels:
        if sr['strength'] >= 3:
            if sr['type'] == 'support' and sr['price'] < current:
                if nearest_support is None or sr['price'] > nearest_support:
                    nearest_support = sr['price']
            if sr['type'] == 'resistance' and sr['price'] > current:
                if nearest_resist is None or sr['price'] < nearest_resist:
                    nearest_resist = sr['price']

    if nearest_support:
        lines_info.append(f"【最近支撑】{nearest_support:.2f} (距现价{(nearest_support/current-1)*100:+.1f}%)")
    if nearest_resist:
        lines_info.append(f"【最近压力】{nearest_resist:.2f} (距现价{(nearest_resist/current-1)*100:+.1f}%)")

    # RSI/KDJ/MACD 状态
    rsi_now = rsi[-1]
    k_now, d_now, j_now = k_val[-1], d_val[-1], j_val[-1]
    macd_signal = "金叉" if dif[-1] > dea[-1] else "死叉"

    rsi_status = "超买" if rsi_now > 70 else "超卖" if rsi_now < 30 else "中性"
    kdj_status = "超买" if j_now > 80 else "超卖" if j_now < 20 else "中性"

    lines_info.append(f"RSI={rsi_now:.1f}({rsi_status}) | KDJ: K={k_now:.1f} D={d_now:.1f} J={j_now:.1f}({kdj_status})")
    lines_info.append(f"MACD: {macd_signal} | DIF={dif[-1]:.3f} DEA={dea[-1]:.3f} | 柱={macd_bar[-1]:.3f}")

    # 推演结论
    lines_info.append("")
    lines_info.append("━" * 40)
    lines_info.append("【走势推演】")

    # 综合判断
    bullish_signals = 0
    bearish_signals = 0

    if uptrend_lines and uptrend_lines[0]['strength'] > 3:
        bullish_signals += 1
    if rsi_now < 40:
        bullish_signals += 1
    if macd_bar[-1] > macd_bar[-2] and macd_bar[-2] < 0:
        bullish_signals += 1  # MACD柱收窄
    if ma5[-1] > ma5[-2] and ma5[-2] > ma5[-3]:
        bullish_signals += 1  # MA5拐头

    if downtrend_lines and downtrend_lines[0]['strength'] > 3:
        bearish_signals += 1
    if rsi_now > 65:
        bearish_signals += 1
    if closes[-1] < ma20[-1]:
        bearish_signals += 1
    if dif[-1] < dea[-1]:
        bearish_signals += 1

    if bullish_signals > bearish_signals:
        outlook = '偏多'
        outlook_color = '#00E676'
        if nearest_resist:
            lines_info.append(f"  短期看涨，目标位 {nearest_resist:.2f}（最近压力位）")
        lines_info.append(f"  沿着上升趋势线运行，支撑有效则有望突破")
    elif bearish_signals > bullish_signals:
        outlook = '偏空'
        outlook_color = '#FF5252'
        if nearest_support:
            lines_info.append(f"  短期承压，关注 {nearest_support:.2f} 支撑是否有效")
        lines_info.append(f"  若跌破上升趋势线支撑，需止损离场")
    else:
        outlook = '震荡'
        outlook_color = '#FFD740'
        lines_info.append(f"  短期区间震荡，等待方向选择")

    lines_info.append(f"  综合信号: 多头{bullish_signals} vs 空头{bearish_signals} | 走势{outlook}")

    # 操作建议
    lines_info.append("")
    lines_info.append("【操作参考】")
    if info.get('cost'):
        stop = info['cost'] * 0.98
        lines_info.append(f"  成本: {info['cost']:.2f} | 止损: {stop:.2f} (-2%)")
        if nearest_support:
            lines_info.append(f"  支撑位 {nearest_support:.2f} 不破可持有，破则止损")
        if nearest_resist:
            lines_info.append(f"  反弹到 {nearest_resist:.2f} 附近可减仓")

    import textwrap
    for i, line in enumerate(lines_info):
        y_pos = 0.95 - i * 0.04
        color = text_color
        if line.startswith('【'):
            color = '#FFF176'
        elif '偏多' in line:
            color = '#00E676'
        elif '偏空' in line:
            color = '#FF5252'
        elif '震荡' in line:
            color = '#FFD740'
        ax_info.text(0.02, y_pos, line, transform=ax_info.transAxes,
                    fontsize=8, color=color, va='top')

    # ============================================================
    #  X轴日期
    # ============================================================
    # 每20个交易日标一个日期
    tick_step = max(1, n // 8)
    tick_positions = list(range(0, n, tick_step))
    tick_labels = [dates_str[i][5:] for i in tick_positions]  # MM-DD 格式

    # 添加未来日期
    for i, fd in enumerate(future_dates):
        if i % 5 == 0:
            tick_positions.append(n + i)
            tick_labels.append(fd.strftime('%m-%d') + '?')

    for ax in [ax_main, ax_vol, ax_macd, ax_rsi, ax_kdj]:
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([])  # 只在最下面显示

    ax_kdj.set_xticks(tick_positions)
    ax_kdj.set_xticklabels(tick_labels, fontsize=7, color=text_color, rotation=30)

    # 共享X轴范围
    for ax in [ax_main, ax_vol, ax_macd, ax_rsi, ax_kdj]:
        ax.set_xlim(-2, n + FUTURE_BARS + 2)

    # ============================================================
    #  保存
    # ============================================================
    out_path = os.path.join(OUTPUT_DIR, f'trend_{code}_{name}.png')
    fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e', edgecolor='none')
    plt.close(fig)
    print(f"  ✓ 已保存: {out_path}")
    return out_path


# ---- 辅助函数 ----
def pd_ema(data, period):
    """EMA计算"""
    result = np.zeros(len(data))
    result[:period] = np.mean(data[:period])
    multiplier = 2 / (period + 1)
    for i in range(period, len(data)):
        result[i] = (data[i] - result[i-1]) * multiplier + result[i-1]
    return result


def compute_rsi(closes, period=14):
    """RSI"""
    n = len(closes)
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.zeros(n)
    avg_loss = np.zeros(n)
    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])
    for i in range(period + 1, n):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i-1]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i-1]) / period
    rsi = np.full(n, 50.0)
    for i in range(period, n):
        if avg_loss[i] == 0:
            rsi[i] = 100
        else:
            rsi[i] = 100 - 100 / (1 + avg_gain[i] / avg_loss[i])
    return rsi


def compute_kdj(highs, lows, closes, period=9):
    """KDJ指标"""
    n = len(closes)
    k = np.full(n, 50.0)
    d = np.full(n, 50.0)
    j = np.full(n, 50.0)

    for i in range(period - 1, n):
        high_n = np.max(highs[i - period + 1:i + 1])
        low_n = np.min(lows[i - period + 1:i + 1])
        if high_n != low_n:
            rsv = (closes[i] - low_n) / (high_n - low_n) * 100
        else:
            rsv = 50
        k[i] = 2/3 * k[i-1] + 1/3 * rsv if i >= period else rsv
        d[i] = 2/3 * d[i-1] + 1/3 * k[i] if i >= period else k[i]
        j[i] = 3 * k[i] - 2 * d[i]

    return k, d, j


# ---- 主函数 ----
def main():
    print("=" * 60)
    print(f"  专业趋势线+走势推演分析  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print(f"  算法: 波段点检测 → 趋势线拟合 → 通道识别 → 未来推演")
    print(f"  虚线延伸 = 未来15天预测区域")

    for code, info in STOCKS.items():
        try:
            draw_pro_chart(code, info)
        except Exception as e:
            print(f"  ✗ {info['name']} 失败: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n  完成. 图片在 {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
