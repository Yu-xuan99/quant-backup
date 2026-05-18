#!/usr/bin/env python3
"""
A股抄底扫描器 — 底部识别 + 反弹确认
核心理念: 买在无人问津处，卖在人声鼎沸时

抄底四维度:
  1. 超卖深度 (30分) — 跌够了没有？
  2. 止跌企稳 (25分) — 卖压在衰竭吗？
  3. 反转催化剂 (25分) — 反弹的导火索？
  4. 安全边际 (20分) — 万一错了能扛吗？

借入syf_quant-trading: RSI超卖, 布林下轨, 关键价位, MACD分析
"""

import requests
import json
import time
import os
import sys
from datetime import datetime

# ============================================================
# 配置
# ============================================================
MIN_PRICE = 1.5
MAX_PRICE = 16.0  # 抄底更偏好低价股
CAPITAL = 5000.0
STOP_LOSS_PCT = 2.0
MAX_POSITION_PCT = 0.40  # 抄底仓位更保守
MAX_TOTAL_POSITIONS = 3   # 可分批建仓
TOP_N = 20

# 超卖阈值
RSI_OVERSOLD = 30
KDJ_J_OVERSOLD = 0
BB_BELOW_LOWER = True    # 跌破布林下轨
POS_60_LOW = 20          # 60日位置 < 20%
FALL_FROM_HIGH = 15      # 距60日高点跌幅 > 15%

# 止跌阈值
VOL_COLLAPSE = 0.7       # 量缩到5日均量70%以下(卖压衰竭)
MA5_FLATTEN = 0.3        # MA5斜率绝对值 < 0.3%(走平)
TIGHT_RANGE = 2.0        # 日内振幅 < 2%(窄幅整理)

# 反转阈值
MACD_DIVERGENCE = True   # 底背离
VOL_SURGE_UP = 1.5       # 放量收阳
RSI_TURNING_UP = True    # RSI从超卖区拐头
GOLDEN_CROSS = True      # MACD/MA金叉

# 风控阈值
STOCK_CRASH_3D = -12     # 3日跌幅 > 12% = 飞刀, 不接
STOCK_CRASH_5D = -18     # 5日跌幅 > 18% = 飞刀

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# 1. 数据采集
# ============================================================
def fetch_kline(stock_code):
    """腾讯财经K线 (24/7可用)"""
    market = 'sz' if stock_code.startswith(('0', '3')) else 'sh'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{stock_code},day,,,120,qfq"
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if data.get('code') == 0:
            return data['data'][f'{market}{stock_code}'].get('qfqday', [])
    except:
        pass
    return []


def fetch_watchlist_kline(codes_dict):
    """批量拉取K线"""
    results = {}
    for code, name in codes_dict.items():
        kline = fetch_kline(code)
        if kline:
            results[code] = {'name': name, 'kline': kline}
        time.sleep(0.15)  # 避免被封
    return results


# ============================================================
# 2. 技术指标计算
# ============================================================
def calc_indicators(kline_data):
    """抄底专用指标"""
    if not kline_data or len(kline_data) < 60:
        return None

    closes = [float(x[2]) for x in kline_data]
    highs = [float(x[3]) for x in kline_data]
    lows = [float(x[4]) for x in kline_data]
    volumes = [float(x[5]) * 100 for x in kline_data]
    n = len(closes)
    latest = closes[-1]

    def ma(arr, p):
        return sum(arr[-p:]) / p if len(arr) >= p else arr[-1]

    def ema(arr, p):
        if len(arr) < p: return arr[-1]
        k = 2 / (p + 1)
        r = sum(arr[:p]) / p
        for v in arr[p:]:
            r = v * k + r * (1 - k)
        return r

    # 均线
    ma5 = ma(closes, 5)
    ma10 = ma(closes, 10)
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60) if n >= 60 else ma(closes, 30)

    # 60日位置
    low_60 = min(lows[-60:]) if n >= 60 else min(lows)
    high_60 = max(highs[-60:]) if n >= 60 else max(highs)
    pos_60 = (latest - low_60) / (high_60 - low_60) * 100 if high_60 > low_60 else 50

    # 距高点跌幅
    fall_from_high = (1 - latest / high_60) * 100 if high_60 > 0 else 0

    # MA5斜率
    def ma_slope(arr, period):
        if len(arr) < period + 5: return 0
        recent = sum(arr[-5:]) / 5
        prior = sum(arr[-period - 5:-period]) / 5
        return (recent / prior - 1) * 100 if prior > 0 else 0

    ma5_slope = ma_slope(closes, 5)
    ma20_slope = ma_slope(closes, 20)

    # RSI(14)
    def calc_rsi(period=14):
        if len(closes) < period + 1: return 50
        gains = []
        losses = []
        for i in range(-period, 0):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0: return 100
        return 100 - 100 / (1 + avg_gain / avg_loss)

    rsi = calc_rsi(14)

    # RSI拐头检测 (当前 vs 3天前)
    rsi_3d_ago = 50
    if n > 17:
        closes_3d = closes[:-3]
        gains_3d = []
        losses_3d = []
        for i in range(-14, 0):
            if i + len(closes_3d) < 0: continue
            idx = i
            diff = closes_3d[idx] - closes_3d[idx - 1]
            gains_3d.append(max(diff, 0))
            losses_3d.append(max(-diff, 0))
        if gains_3d and losses_3d:
            avg_g = sum(gains_3d) / 14
            avg_l = sum(losses_3d) / 14
            rsi_3d_ago = 100 - 100 / (1 + avg_g / avg_l) if avg_l > 0 else 100
    rsi_turning = rsi > rsi_3d_ago and rsi < 40

    # KDJ (简化计算, 迭代最近30天)
    def calc_kdj():
        if n < 9: return 50, 50, 50
        period = 9
        k_val, d_val = 50.0, 50.0
        calc_start = max(0, n - 30 - period)
        for idx in range(calc_start + period - 1, n):
            hh = max(highs[idx - period + 1:idx + 1])
            ll = min(lows[idx - period + 1:idx + 1])
            rsv = (closes[idx] - ll) / (hh - ll) * 100 if hh > ll else 50
            k_val = 2 / 3 * k_val + 1 / 3 * rsv
            d_val = 2 / 3 * d_val + 1 / 3 * k_val
        j_val = 3 * k_val - 2 * d_val
        return k_val, d_val, j_val

    kdj_k, kdj_d, kdj_j = calc_kdj()

    # MACD
    dif = ema(closes, 12) - ema(closes, 26)
    dea = ema([dif], 9) if isinstance(dif, (int, float)) else \
        sum([ema(closes[:i + 1], 12) - ema(closes[:i + 1], 26) for i in range(len(closes))]) / len(closes)
    # Actually compute proper DEA
    difs = []
    for i in range(26, n + 1):
        d = ema(closes[:i], 12) - ema(closes[:i], 26)
        difs.append(d)
    if difs:
        dif = difs[-1]
        dea = ema(difs, 9) if len(difs) >= 9 else sum(difs) / len(difs)
        macd_bar = 2 * (dif - dea)
    else:
        dif, dea, macd_bar = 0, 0, 0

    # MACD底背离: 价格新低但MACD DIF未新低
    macd_divergence = False
    if n >= 40:
        # 找最近20天的价格低点和对应的DIF
        recent_low_idx = closes[-20:].index(min(closes[-20:]))
        recent_low = min(closes[-20:])
        # 找20-40天前的价格低点
        prev_low = min(closes[-40:-20]) if len(closes) >= 40 else recent_low
        if recent_low < prev_low and len(difs) >= 40:
            prev_dif_low = min(difs[-40:-20]) if len(difs) >= 40 else 0
            recent_dif_low = difs[-20 - recent_low_idx] if -20 - recent_low_idx < len(difs) else difs[-1]
            if recent_dif_low > prev_dif_low:
                macd_divergence = True

    macd_signal = "金叉↑" if dif > dea else "死叉↓"

    # MACD金叉(刚形成)
    macd_golden_cross = False
    if n >= 28:
        dif_prev = difs[-2] if len(difs) >= 2 else dif
        dea_prev = ema(difs[:-1], 9) if len(difs) >= 10 else dea
        macd_golden_cross = dif > dea and dif_prev <= dea_prev

    # 布林带 (20,2)
    bb_mid = ma(closes, 20)
    if n >= 20:
        std_20 = (sum((c - bb_mid) ** 2 for c in closes[-20:]) / 20) ** 0.5
    else:
        std_20 = 0
    bb_upper = bb_mid + 2 * std_20
    bb_lower = bb_mid - 2 * std_20
    bb_pos = (latest - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5

    # 量比 (今日/5日均量)
    vol_5d_avg = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else volumes[-1]
    vol_ratio = volumes[-1] / vol_5d_avg if vol_5d_avg > 0 else 1.0

    # 成交额趋势
    amounts = [float(x[6]) for x in kline_data] if len(kline_data[0]) > 6 else [v * latest for v in volumes]
    amt_5d = sum(amounts[-5:]) / 5 if len(amounts) >= 5 else amounts[-1]
    amt_20d = sum(amounts[-20:]) / 20 if len(amounts) >= 20 else amounts[-1]
    amount_trend = ((amt_5d / amt_20d) - 1) * 100 if amt_20d > 0 else 0

    # 连阳天数
    up_days = 0
    for i in range(-1, -min(10, n) - 1, -1):
        if closes[i] > closes[i - 1]:
            up_days += 1
        else:
            break

    # 连续缩量天数
    consec_vol_down = 0
    for i in range(-1, -min(10, n) - 1, -1):
        if volumes[i] < volumes[i - 1]:
            consec_vol_down += 1
        else:
            break

    # 日内振幅
    amplitude = (highs[-1] - lows[-1]) / closes[-1] * 100 if closes[-1] > 0 else 0

    # 近期跌幅
    if n >= 3:
        ret_3d = (closes[-1] / closes[-4] - 1) * 100
    else:
        ret_3d = 0
    if n >= 5:
        ret_5d = (closes[-1] / closes[-6] - 1) * 100
    else:
        ret_5d = 0

    # 今日涨跌
    change_pct = (closes[-1] / closes[-2] - 1) * 100 if n >= 2 else 0

    # 下影线检测
    body = abs(closes[-1] - highs[-1] if closes[-1] < (highs[-1] + lows[-1]) / 2 else closes[-1] - lows[-1])
    lower_shadow = min(highs[-1], closes[-1] if closes[-1] > (highs[-1] + lows[-1]) / 2
                       else (highs[-1] if closes[-1] < (highs[-1] + lows[-1]) / 2 else 0))
    # Simplified: lower shadow = min(open, close) - low
    open_p = float(kline_data[-1][1])
    lower_shadow = min(open_p, closes[-1]) - lows[-1]
    lower_shadow_pct = lower_shadow / closes[-1] * 100 if closes[-1] > 0 else 0

    return {
        'close': latest,
        'open': open_p,
        'high': highs[-1],
        'low': lows[-1],
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'ma5_slope': ma5_slope,
        'ma20_slope': ma20_slope,
        'rsi': rsi,
        'rsi_turning': rsi_turning,
        'kdj_k': kdj_k, 'kdj_d': kdj_d, 'kdj_j': kdj_j,
        'dif': dif, 'dea': dea, 'macd_bar': macd_bar,
        'macd_signal': macd_signal,
        'macd_golden_cross': macd_golden_cross,
        'macd_divergence': macd_divergence,
        'bb_upper': bb_upper, 'bb_mid': bb_mid, 'bb_lower': bb_lower,
        'bb_pos': bb_pos,
        'pos_60': pos_60,
        'fall_from_high': fall_from_high,
        'vol_ratio': vol_ratio,
        'amount_trend': amount_trend,
        'up_days': up_days,
        'consec_vol_down': consec_vol_down,
        'amplitude': amplitude,
        'change_pct': change_pct,
        'ret_3d': ret_3d, 'ret_5d': ret_5d,
        'lower_shadow_pct': lower_shadow_pct,
    }


# ============================================================
# 3. 抄底评分引擎
# ============================================================
def score_bottom(stock_name, stock_code, ind):
    """
    抄底评分: 0-100
    越高 = 底部越确认, 反弹概率越大

    四个维度:
      超卖深度 (30) — 跌得够不够深
      止跌企稳 (25) — 卖压有没有衰竭
      反转催化剂 (25) — 有没有反弹信号
      安全边际 (20) — 错了扛不扛得住
    """
    if ind is None:
        return 0, ["数据不足"], []

    score = 0
    reasons = []
    warnings = []
    price = ind['close']

    # ============ 一、超卖深度 (30分) ============
    os_score = 0

    # RSI
    if ind['rsi'] <= 20:
        os_score += 12; reasons.append(f"RSI极低({ind['rsi']:.0f})")
    elif ind['rsi'] <= 25:
        os_score += 10; reasons.append(f"RSI深度超卖({ind['rsi']:.0f})")
    elif ind['rsi'] <= 30:
        os_score += 8; reasons.append(f"RSI超卖({ind['rsi']:.0f})")
    elif ind['rsi'] <= 35:
        os_score += 5; reasons.append(f"RSI偏弱({ind['rsi']:.0f})")
    elif ind['rsi'] <= 40:
        os_score += 3

    # KDJ J值 (比RSI更敏感)
    if ind['kdj_j'] < -10:
        os_score += 8; reasons.append(f"KDJ极低(J={ind['kdj_j']:.0f})")
    elif ind['kdj_j'] < 0:
        os_score += 6; reasons.append(f"KDJ超卖(J={ind['kdj_j']:.0f})")
    elif ind['kdj_j'] < 5:
        os_score += 4

    # 60日位置
    if ind['pos_60'] <= 5:
        os_score += 6; reasons.append(f"60日底部({ind['pos_60']:.0f}%)")
    elif ind['pos_60'] <= 15:
        os_score += 4; reasons.append(f"60日低位({ind['pos_60']:.0f}%)")
    elif ind['pos_60'] <= 25:
        os_score += 2

    # BB位置
    if ind['bb_pos'] < -0.1:
        os_score += 4; reasons.append("跌破布林下轨")
    elif ind['bb_pos'] < 0:
        os_score += 2

    score += min(os_score, 30)

    # ============ 二、止跌企稳 (25分) ============
    stab_score = 0

    # 量能萎缩 (卖压衰竭)
    if ind['vol_ratio'] < 0.5:
        stab_score += 8; reasons.append(f"极度缩量({ind['vol_ratio']:.1f}x)")
    elif ind['vol_ratio'] < 0.7:
        stab_score += 6; reasons.append(f"缩量止跌({ind['vol_ratio']:.1f}x)")
    elif ind['vol_ratio'] < 0.85:
        stab_score += 3; reasons.append("量能收缩")

    # 连续缩量
    if ind['consec_vol_down'] >= 4:
        stab_score += 5; reasons.append(f"连{ind['consec_vol_down']}日缩量")
    elif ind['consec_vol_down'] >= 2:
        stab_score += 3

    # MA5走平 (不再加速下跌)
    if abs(ind['ma5_slope']) < 0.3:
        stab_score += 5; reasons.append("MA5走平")
    elif abs(ind['ma5_slope']) < 0.5:
        stab_score += 3
    elif ind['ma5_slope'] < -1.5:
        stab_score -= 5; warnings.append("MA5仍在加速下跌")

    # 窄幅整理
    if ind['amplitude'] < 2.0:
        stab_score += 4; reasons.append(f"窄幅整理({ind['amplitude']:.1f}%)")
    elif ind['amplitude'] < 3.0:
        stab_score += 2

    # 下影线 (多方反击)
    if ind['lower_shadow_pct'] > 3:
        stab_score += 3; reasons.append("长下影线")
    elif ind['lower_shadow_pct'] > 1.5:
        stab_score += 1

    score += max(min(stab_score, 25), -10)

    # ============ 三、反转催化剂 (25分) ============
    rev_score = 0

    # MACD底背离 (最强反转信号)
    if ind['macd_divergence']:
        rev_score += 15; reasons.append("MACD底背离!")
    elif ind['macd_golden_cross'] and ind['rsi'] < 40:
        rev_score += 8; reasons.append("低位金叉")
    elif ind['macd_signal'] == '金叉↑':
        rev_score += 2

    # RSI拐头
    if ind['rsi_turning']:
        rev_score += 6; reasons.append("RSI拐头↑")

    # 放量收阳 (抄底资金进场)
    if ind['vol_ratio'] > 1.3 and ind['change_pct'] > 0:
        rev_score += 6; reasons.append("放量收阳")
    elif ind['vol_ratio'] > 1.0 and ind['change_pct'] > 0:
        rev_score += 3

    # 连阳
    if ind['up_days'] >= 3:
        rev_score += 4; reasons.append(f"连{ind['up_days']}日收阳")
    elif ind['up_days'] >= 1:
        rev_score += 2

    # 今日收阳
    if ind['change_pct'] > 0:
        rev_score += 2

    score += min(rev_score, 25)

    # ============ 四、安全边际 (20分) ============
    safe_score = 0

    # 资金适配
    cost_100 = price * 100
    if cost_100 <= CAPITAL * 0.4:
        n_lots = int(CAPITAL * 0.4 // cost_100)
        if n_lots >= 3:
            safe_score += 6; reasons.append(f"可买{n_lots}手")
        else:
            safe_score += 4
    elif cost_100 <= CAPITAL * 0.8:
        safe_score += 2

    # 低价安全垫
    if price < 6:
        safe_score += 4; reasons.append(f"低价{price:.2f}")
    elif price < 10:
        safe_score += 2

    # 距高点跌幅 (跌得越多越安全)
    if ind['fall_from_high'] > 35:
        safe_score += 4; reasons.append(f"距高点-{ind['fall_from_high']:.0f}%")
    elif ind['fall_from_high'] > 25:
        safe_score += 3
    elif ind['fall_from_high'] > 15:
        safe_score += 2

    # 中期趋势
    if ind['ma20_slope'] < -3:
        safe_score -= 5; warnings.append("中期仍下行")
    elif ind['ma20_slope'] < -1.5:
        safe_score -= 2

    score += max(min(safe_score, 20), -10)

    # ============ 风控罚分 ============
    penalty = 0

    # 连续暴跌 (飞刀)
    if ind['ret_3d'] < STOCK_CRASH_3D:
        penalty -= 20; warnings.append(f"3日暴跌{ind['ret_3d']:.0f}% — 飞刀!")
    if ind['ret_5d'] < STOCK_CRASH_5D:
        penalty -= 15; warnings.append(f"5日暴跌{ind['ret_5d']:.0f}%")

    # 今日跌停
    if ind['change_pct'] < -9.5:
        penalty -= 20; warnings.append("跌停板 — 不抄")

    # 放量大跌 (不是抄底时机)
    if ind['vol_ratio'] > 2.0 and ind['change_pct'] < -3:
        penalty -= 15; warnings.append("放量暴跌 — 恐慌未完")

    # 极度缩量阴跌 (无人问津, 可能继续阴跌)
    if ind['vol_ratio'] < 0.3 and ind['change_pct'] < 0:
        penalty -= 3; warnings.append("无量阴跌")

    score += penalty

    return max(0, min(100, score)), reasons, warnings


# ============================================================
# 4. 主流程
# ============================================================
def analyze_batch(stock_list, label=""):
    """批量分析"""
    results = []
    total = len(stock_list)

    for i, (code, name) in enumerate(stock_list):
        if i % 10 == 0:
            print(f"   进度: {i}/{total}")
        kline = fetch_kline(code)
        if not kline:
            continue
        ind = calc_indicators(kline)
        if not ind:
            continue
        sc, reasons, warnings = score_bottom(name, code, ind)

        results.append({
            'code': code,
            'name': name,
            'score': sc,
            'price': ind['close'],
            'change_pct': ind['change_pct'],
            'rsi': ind['rsi'],
            'kdj_j': ind['kdj_j'],
            'pos_60': ind['pos_60'],
            'fall_from_high': ind['fall_from_high'],
            'bb_pos': ind['bb_pos'],
            'vol_ratio': ind['vol_ratio'],
            'consec_vol_down': ind['consec_vol_down'],
            'ma5_slope': ind['ma5_slope'],
            'amplitude': ind['amplitude'],
            'up_days': ind['up_days'],
            'macd_divergence': ind['macd_divergence'],
            'macd_golden_cross': ind['macd_golden_cross'],
            'ret_3d': ind['ret_3d'],
            'ret_5d': ind['ret_5d'],
            'lower_shadow_pct': ind['lower_shadow_pct'],
            'reasons': reasons,
            'warnings': warnings,
            'ind': ind,
        })
        time.sleep(0.12)

    # 排序
    results.sort(key=lambda x: x['score'], reverse=True)
    return results


def print_results(results, top_n=20):
    """输出结果"""
    print(f"\n{'=' * 75}")
    print(f"  🎯 抄底扫描 — 底部识别 + 反弹确认")
    print(f"  评分维度: 超卖深度(30) + 止跌企稳(25) + 反转催化剂(25) + 安全边际(20)")
    print(f"{'=' * 75}")

    # 评分等级
    grade_map = {
        (80, 100): "🟢 强烈抄底信号",
        (70, 80): "🟡 底部确认中",
        (60, 70): "🟠 关注区域",
        (0, 60): "⚪ 信号不足",
    }

    for rank, r in enumerate(results[:top_n], 1):
        sc = r['score']
        grade = next(v for (lo, hi), v in grade_map.items() if lo <= sc < hi)

        print(f"\n{'─' * 75}")
        print(f"  #{rank} {grade} | {r['name']}({r['code']}) | 评分:{sc}/100")
        print(f"    现价:{r['price']:.2f} | 今日:{r['change_pct']:+.2f}% | "
              f"距60日高:-{r['fall_from_high']:.0f}% | 60日位:{r['pos_60']:.0f}%")
        print(f"    RSI:{r['rsi']:.0f} | KDJ J:{r['kdj_j']:.0f} | BB位:{r['bb_pos']*100:.0f}% | "
              f"量比:{r['vol_ratio']:.1f}x")
        print(f"    连缩量:{r['consec_vol_down']}天 | 振幅:{r['amplitude']:.1f}% | "
              f"MA5斜率:{r['ma5_slope']:+.2f}% | 下影:{r['lower_shadow_pct']:.1f}%")
        print(f"    3日:{r['ret_3d']:+.1f}% | 5日:{r['ret_5d']:+.1f}% | "
              f"连阳:{r['up_days']}天")

        # 关键信号
        signals = []
        if r['macd_divergence']: signals.append("🔑MACD底背离!")
        if r['macd_golden_cross']: signals.append("🔑MACD金叉")
        if r['reasons']:
            print(f"    +{' | +'.join(r['reasons'][:6])}")

        if r['warnings']:
            print(f"    ⚠ {' | ⚠ '.join(r['warnings'][:4])}")

        # 交易计划
        price = r['price']
        if sc >= 60:
            pos_pct = min(MAX_POSITION_PCT, 0.25 + (sc - 60) * 0.005)
            shares = max(1, int(CAPITAL * pos_pct // (price * 100)))
            stop_loss = price * (1 - STOP_LOSS_PCT / 100)
            target = price * 1.05 + (sc - 60) * 0.01  # 分数越高目标越远
            max_loss = shares * (price - stop_loss) * 100
            pos_pct_actual = shares * price * 100 / CAPITAL * 100
            rr = (target - price) / (price - stop_loss) if price > stop_loss else 0
            print(f"    ── 试探建仓 ──")
            print(f"    买入: {shares}手 = {shares*price*100:.0f}元 (占{pos_pct_actual:.0f}%)")
            print(f"    止损: {stop_loss:.2f} (亏损{max_loss:.0f}元)")
            print(f"    目标: {target:.2f} | 盈亏比: {rr:.1f}")
            if r['macd_divergence']:
                print(f"    📌 底背离信号强烈, 可确认后加仓")


def main():
    print("=" * 75)
    print("  A股抄底扫描器 — 底部识别 + 反弹确认")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  参数: {MIN_PRICE}-{MAX_PRICE}元 | 资金{CAPITAL:.0f}元 | 止损{STOP_LOSS_PCT}%")
    print(f"  单票上限{MAX_POSITION_PCT*100:.0f}% | 最多{MAX_TOTAL_POSITIONS}只")
    print("=" * 75)

    # ============ 构建待分析股票池 ============
    # 策略: 用板块成分股 + 已知弱势股

    # 1. 从之前的扫描数据中获取被淘汰的股票（它们可能超卖）
    # 2. 自定义弱势板块候选池

    # 抄底候选池 — 按行业分类, 排除电力(刚爆炒完)
    bottom_pool = {
        # === 化工 (周期反转+超跌常客) ===
        '600409': '三友化工',
        '600230': '沧州大化',
        '600727': '鲁北化工',
        '600078': '澄星股份',
        '002601': '龙佰集团',
        '600352': '浙江龙盛',
        '002092': '中泰化学',
        '000830': '鲁西化工',
        '600309': '万华化学',

        # === 医药生物 (防御+超跌反弹) ===
        '600276': '恒瑞医药',
        '000963': '华东医药',
        '002001': '新和成',
        '600196': '复星医药',
        '600085': '同仁堂',
        '002422': '科伦药业',
        '000538': '云南白药',
        '300003': '乐普医疗',

        # === 食品饮料 (防御+回调) ===
        '600887': '伊利股份',
        '002557': '洽洽食品',
        '603288': '海天味业',
        '600519': '贵州茅台',
        '000895': '双汇发展',
        '600872': '中炬高新',
        '002568': '百润股份',

        # === 地产/基建链 (深度超卖区域) ===
        '000002': '万科A',
        '600048': '保利发展',
        '601800': '中国交建',
        '600585': '海螺水泥',
        '000401': '冀东水泥',
        '002271': '东方雨虹',

        # === 汽车零部件 (今日-0.43%弱势) ===
        '600741': '华域汽车',
        '601689': '拓普集团',
        '000338': '潍柴动力',
        '600104': '上汽集团',
        '002085': '万丰奥威',

        # === 电子/半导体 (回调中的机会) ===
        '002396': '星网锐捷',
        '002456': '欧菲光',
        '600703': '三安光电',
        '002475': '立讯精密',
        '000725': '京东方A',

        # === 银行 (高股息防守) ===
        '601398': '工商银行',
        '601939': '建设银行',
        '601288': '农业银行',
        '600036': '招商银行',

        # === 环保 ===
        '300070': '碧水源',
        '601330': '绿色动力',
        '300055': '万邦达',
        '300137': '先河环保',

        # === 传媒娱乐 ===
        '002027': '分众传媒',
        '600637': '东方明珠',
        '002555': '三七互娱',

        # === 纺织服装 (低价+弹性) ===
        '002563': '森马服饰',
        '603116': '红蜻蜓',

        # === 农林牧渔 (周期底) ===
        '002714': '牧原股份',
        '300498': '温氏股份',
        '002311': '海大集团',

        # === 商贸零售 (超跌) ===
        '002024': '苏宁易购',
        '601933': '永辉超市',

        # === 交通运输 (高股息+抗跌) ===
        '601006': '大秦铁路',
        '600029': '南方航空',

        # === 有色/矿业 ===
        '603993': '洛阳钼业',
        '601899': '紫金矿业',

        # === 机械/制造 ===
        '600480': '凌云股份',
        '002229': '鸿博股份',
        '600031': '三一重工',

        # === 其他 ===
        '600857': '宁波中百',
        '603616': '韩建河山',
        '002457': '青龙管业',
        '002196': '方正电机',
        '300615': '欣天科技',
        '600050': '中国联通',
        '002630': '华西能源',
    }

    # 去重
    seen = set()
    stock_list = []
    for code, name in bottom_pool.items():
        if code not in seen:
            seen.add(code)
            stock_list.append((code, name))

    print(f"\n[1/3] 拉取K线数据 ({len(stock_list)}只)...")
    print(f"   注: 腾讯财经K线API, 24/7可用")

    results = analyze_batch(stock_list)

    if not results:
        print("\n  ❌ 无有效数据, 请检查网络")
        return

    print(f"\n[2/3] 抄底评分完成! 共{len(results)}只有效分析")

    # 统计
    strong = [r for r in results if r['score'] >= 70]
    watch = [r for r in results if 60 <= r['score'] < 70]
    weak = [r for r in results if r['score'] < 60]

    print(f"   ≥70分(底部确认): {len(strong)}只")
    print(f"   60-69分(关注区域): {len(watch)}只")
    print(f"   <60分(信号不足): {len(weak)}只")

    print_results(results, TOP_N)

    # ============ 保存结果 ============
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    out_file = os.path.join(OUTPUT_DIR, f"bottom_scan_{ts}.json")
    save_data = []
    for r in results:
        save_data.append({
            'code': r['code'], 'name': r['name'], 'score': r['score'],
            'price': r['price'], 'change_pct': r['change_pct'],
            'rsi': round(r['rsi'], 1), 'kdj_j': round(r['kdj_j'], 1),
            'pos_60': round(r['pos_60'], 1), 'fall_from_high': round(r['fall_from_high'], 1),
            'bb_pos': round(r['bb_pos'], 3), 'vol_ratio': round(r['vol_ratio'], 2),
            'consec_vol_down': r['consec_vol_down'], 'amplitude': round(r['amplitude'], 2),
            'up_days': r['up_days'], 'macd_divergence': r['macd_divergence'],
            'macd_golden_cross': r['macd_golden_cross'],
            'ret_3d': round(r['ret_3d'], 1), 'ret_5d': round(r['ret_5d'], 1),
            'lower_shadow_pct': round(r['lower_shadow_pct'], 2),
            'reasons': r['reasons'][:8],
            'warnings': r['warnings'][:4],
        })
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 结果保存: {out_file}")
    print(f"  Done. {datetime.now().strftime('%H:%M:%S')}")


if __name__ == '__main__':
    main()
