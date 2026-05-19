#!/usr/bin/env python3
"""
A股短线扫描器 v3 — 修复版
v2 致命缺陷修复:
  1. RSI 40-60中性区不再误判为"死钱" (滨化股份514惨案)
  2. 板块当日涨幅>5%自动降级 — 防追顶
  3. 加入大盘风控断路器
  4. 加入量价背离检测
  5. 多级筛选: MUST-PASS → 评分 → 排序
  6. 5日涨幅>15%强制降分
  7. 学习syf_quant-trading: MA斜率, 连阳天数, 成交额趋势

策略: 动量追涨 + 严格风控 + 反追顶过滤 + 板块轮动
"""
import requests
import json
import time
import os
from datetime import datetime

# ============================================================
# 配置
# ============================================================
MIN_PRICE = 3.0
MAX_PRICE = 17.0
CAPITAL = 5000.0  # 更新后的估计本金
STOP_LOSS_PCT = 2.0
MAX_POSITION_PCT = 0.80  # 单票最多占总资金80%(小资金放宽)
MAX_TOTAL_POSITIONS = 2
TOP_N = 20
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 风控断路器阈值
# ============================================================
SECTOR_CHASE_LIMIT = 5.0    # 板块当日涨幅>5% → 候选降级
STOCK_5D_LIMIT = 15.0       # 个股5日涨幅>15% → 强制扣分
STOCK_10D_LIMIT = 30.0      # 个股10日涨幅>30% → 严重扣分
RSI_OVERBOUGHT = 75         # RSI >75 → 轻扣分
RSI_EXTREME = 85            # RSI >85 → 重扣分(但不禁止!动量股可继续涨)
BB_OVERBOUGHT = 1.0         # BB位置 >100% (突破上轨) → 扣分
VOL_DIVERGENCE_RATIO = 0.7  # 价涨量缩比<0.7 → 量价背离

# 动量衰竭检测: RSI极端 + 量能萎缩 + MA5斜率下降 = 真顶
MOMENTUM_DECAY_RSI = 85     # RSI超此线才触发衰竭检测
MOMENTUM_DECAY_VOL_DROP = 0.7  # 量比相对5日均量下降到70%以下
MOMENTUM_DECAY_MA5_FLAT = 0.3  # MA5斜率<0.3%视为走平

# ============================================================
# 1. 数据采集层
# ============================================================
def fetch_market_data():
    """东方财富全A股行情"""
    all_stocks = []
    for page in range(1, 30):
        try:
            url = (
                "https://push2.eastmoney.com/api/qt/clist/get"
                f"?pn={page}&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
                "&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
                "&fields=f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18,f20,f21"
            )
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Referer': 'https://quote.eastmoney.com/',
            }
            r = requests.get(url, headers=headers, timeout=15)
            data = r.json()
            items = data.get('data', {}).get('diff', [])
            if not items:
                break

            for item in items:
                code = item.get('f12', '')
                name = item.get('f14', '')
                price = item.get('f2', 0) or 0
                change_pct = item.get('f3', 0) or 0
                high = item.get('f15', 0) or 0
                low = item.get('f16', 0) or 0
                open_p = item.get('f17', 0) or 0
                volume = item.get('f5', 0) or 0
                turnover = item.get('f6', 0) or 0
                pre_close = item.get('f18', 0) or 0
                market_cap = item.get('f20', 0) or 0

                if price < MIN_PRICE or price > MAX_PRICE:
                    continue
                if 'ST' in name or '退' in name:
                    continue
                if pre_close <= 0:
                    continue

                all_stocks.append({
                    'code': code, 'name': name,
                    'price': price, 'change_pct': change_pct,
                    'volume': volume, 'turnover': turnover,
                    'high': high, 'low': low, 'open': open_p,
                    'pre_close': pre_close, 'market_cap': market_cap,
                })
            time.sleep(0.3)
        except Exception as e:
            print(f"   第{page}页失败: {e}")
            break
    return all_stocks


def fetch_kline(code, period='day', count=60):
    """腾讯财经K线"""
    market = 'sz' if code.startswith(('0', '3')) else 'sh'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},{period},,,{count},qfq"
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if data.get('code') == 0:
            return data['data'][f'{market}{code}'].get(f'qfq{period}', [])
    except:
        pass
    return None


def fetch_sector_flow():
    """东方财富板块资金流向 — 用于防追顶过滤器"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 50, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f14,f62,f184"
    }
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        items = r.json().get('data', {}).get('diff', [])
        sectors = {}
        for item in items:
            sectors[item.get('f14', '')] = {
                'change_pct': item.get('f3', 0) or 0,
                'net_inflow': (item.get('f62', 0) or 0) / 1e8,
            }
        return sectors
    except:
        return {}


# ============================================================
# 2. 技术指标计算引擎 (融合syf_quant-trading技术)
# ============================================================
def calc_indicators(kline_data):
    if not kline_data or len(kline_data) < 20:
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
        for v in arr[p:]: r = v * k + r * (1 - k)
        return r

    ma5 = ma(closes, 5)
    ma10 = ma(closes, 10)
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60) if n >= 60 else ma(closes, 30)

    # === MA斜率 (syf_quant-trading技术) ===
    # MA5近5日的趋势: MA5 today vs MA5 5 days ago
    def ma_slope(arr, period):
        if len(arr) < period + 5: return 0
        recent = sum(arr[-5:]) / 5
        prior = sum(arr[-period-5:-period]) / 5
        return (recent / prior - 1) * 100 if prior > 0 else 0

    ma5_slope = ma_slope(closes, 5)
    ma20_slope = ma_slope(closes, 20)

    # === 量比 ===
    vol5_avg = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else sum(volumes[-5:]) / 5
    vol20_avg = sum(volumes[-20:]) / 20
    vol_ratio = volumes[-1] / vol5_avg if vol5_avg > 0 else 1
    vol_ratio_20 = volumes[-1] / vol20_avg if vol20_avg > 0 else 1

    # === 量价背离检测 ===
    # 当日涨幅 vs 量比: 价涨量缩 = 顶背离
    ret_today = (closes[-1] / closes[-2] - 1) * 100 if n >= 2 else 0
    vol_divergence = False
    if ret_today > 1 and vol_ratio < VOL_DIVERGENCE_RATIO:
        vol_divergence = True  # 涨了但量不够
    if ret_today > 3 and vol_ratio < 1.0:
        vol_divergence = True  # 大涨但缩量

    # === 连续放量天数 (syf_quant-trading技术) ===
    consec_vol_up = 0
    for i in range(n-1, 0, -1):
        if volumes[i] > volumes[i-1]:
            consec_vol_up += 1
        else:
            break

    # === 涨跌天数 ===
    up_days = 0
    for i in range(n-1, 0, -1):
        if closes[i] > closes[i-1]: up_days += 1
        else: break
    down_days = 0
    for i in range(n-1, 0, -1):
        if closes[i] < closes[i-1]: down_days += 1
        else: break

    # === 收益率 ===
    ret_3d = (closes[-1] / closes[-3] - 1) * 100 if n >= 3 else 0
    ret_5d = (closes[-1] / closes[-5] - 1) * 100 if n >= 5 else 0
    ret_10d = (closes[-1] / closes[-10] - 1) * 100 if n >= 10 else 0

    # === 60日位置 ===
    h60 = max(highs[-60:]) if n >= 60 else max(highs)
    l60 = min(lows[-60:]) if n >= 60 else min(lows)
    pos_60 = (latest - l60) / (h60 - l60) * 100 if h60 != l60 else 50

    # === 20日阻力/支撑 ===
    resistance_20 = max(highs[-20:])
    support_20 = min(lows[-20:])
    pct_from_resistance = (latest - resistance_20) / resistance_20 * 100

    # === MACD ===
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = ema12 - ema26
    dif_hist = [ema(closes[:i], 12) - ema(closes[:i], 26) for i in range(13, n+1)]
    dea = ema(dif_hist, 9) if len(dif_hist) >= 9 else dif
    prev_dea = ema(dif_hist[:-1], 9) if len(dif_hist) > 9 else dif
    prev_dif = dif_hist[-2] if len(dif_hist) > 1 else dif

    if prev_dif < prev_dea and dif > dea:
        macd_signal = "金叉↑"
        macd_cross_days = 0  # 刚刚金叉
    elif prev_dif > prev_dea and dif < dea:
        macd_signal = "死叉↓"
        macd_cross_days = 0
    elif dif > 0:
        macd_signal = "多头"
        macd_cross_days = 99
    else:
        macd_signal = "空头"
        macd_cross_days = -99

    # === RSI14 ===
    if n >= 15:
        gains, losses = [], []
        for i in range(n-14, n):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_g = sum(gains) / 14
        avg_l = sum(losses) / 14
        rsi = 100 - 100 / (1 + avg_g / avg_l) if avg_l > 0 else 100
    else:
        rsi = 50

    # === KDJ ===
    if n >= 9:
        h9 = max(highs[-9:])
        l9 = min(lows[-9:])
        rsv = (latest - l9) / (h9 - l9) * 100 if h9 != l9 else 50
        k_val = rsv * 1/3 + 50 * 2/3
        d_val = k_val * 1/3 + 50 * 2/3
        j_val = 3 * k_val - 2 * d_val
    else:
        k_val = d_val = j_val = 50

    # === 布林带 ===
    bb_mid = ma(closes, 20)
    bb_std = (sum((c - bb_mid)**2 for c in closes[-20:]) / 20) ** 0.5
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_pos = (latest - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

    # === ATR ===
    trs = []
    for i in range(max(1, n-14), n):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.01
    atr_pct = atr / latest * 100

    # === 成交额趋势 (syf_quant-trading技术) ===
    amounts = [volumes[i] * closes[i] for i in range(n)]
    amt_recent_5 = sum(amounts[-5:]) / 5
    amt_prior_5 = sum(amounts[-10:-5]) / 5
    amount_trend = (amt_recent_5 / amt_prior_5 - 1) * 100 if amt_prior_5 > 0 else 0

    return {
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'ma5_slope': ma5_slope, 'ma20_slope': ma20_slope,
        'vol_ratio': vol_ratio, 'vol_ratio_20': vol_ratio_20,
        'vol_divergence': vol_divergence,
        'consec_vol_up': consec_vol_up,
        'up_days': up_days, 'down_days': down_days,
        'ret_3d': ret_3d, 'ret_5d': ret_5d, 'ret_10d': ret_10d,
        'pos_60': pos_60,
        'resistance_20': resistance_20, 'support_20': support_20,
        'pct_from_resistance': pct_from_resistance,
        'macd_signal': macd_signal, 'macd_cross_days': macd_cross_days,
        'dif': dif, 'dea': dea,
        'rsi': rsi, 'kdj_k': k_val, 'kdj_d': d_val, 'kdj_j': j_val,
        'bb_upper': bb_upper, 'bb_lower': bb_lower, 'bb_pos': bb_pos,
        'atr': atr, 'atr_pct': atr_pct,
        'amount_trend': amount_trend,
        'latest': latest,
    }


# ============================================================
# 3. MUST-PASS 预筛选 (唐杰风格 — 不通过直接淘汰)
# ============================================================
def must_pass_filter(stock, ind):
    """
    必须全部通过才进入评分阶段。
    这是从v2最大的改进 — 不满足硬条件的股直接淘汰。
    """
    failures = []

    # 0. 数据不足 → 直接淘汰
    if ind is None:
        failures.append("K线数据不足")

    # 1. 剔除涨停股 (买不到)
    if stock['change_pct'] > 9.5:
        failures.append("已涨停")

    # 2. 剔除跌停股
    if stock['change_pct'] < -9.5:
        failures.append("已跌停")

    # 3. 动量衰竭检测(替代简单RSI极端禁止)
    # RSI极端超买不是硬禁止 — 动量股RSI可以持续>85
    # 真正的危险信号: RSI极端 + 量能萎缩 + MA5走平 = 动量衰竭
    if ind['rsi'] > MOMENTUM_DECAY_RSI:
        vol_collapse = ind['vol_ratio'] < MOMENTUM_DECAY_VOL_DROP
        ma5_flat = ind['ma5_slope'] < MOMENTUM_DECAY_MA5_FLAT
        if vol_collapse and ma5_flat:
            failures.append(f"动量衰竭(RSI{ind['rsi']:.0f}+量缩+MA5平)")

    # 4. 量比过低 → 无资金关注
    if ind['vol_ratio'] < 0.5:
        failures.append(f"极度缩量({ind['vol_ratio']:.1f}x)")

    return len(failures) == 0, failures


# ============================================================
# 4. 评分引擎 v3.2 — 动量质量评分
# ============================================================
def score_stock_v3(stock, ind, sector_map=None):
    """
    v3.2: 量能是动量燃料, MA斜率是方向盘
    核心洞察: 514回测中, 所有赢家(V↑) vs 所有输家(V↓)
    量能方向是最强单一信号, 不需要复杂化

    评分结构: 量能(30) + 趋势质量(25) + 位置安全(15) + 反转风险(-30) + 适配(20)
    """
    if ind is None:
        return 0, ["数据不足"], []

    score = 0
    reasons = []
    warnings = []
    price = stock['price']
    change = stock['change_pct']

    # ---- 布尔判断 ----
    vol_expanding = ind['vol_ratio'] >= 1.2      # 量能扩张
    vol_strong = ind['vol_ratio'] >= 1.5          # 量能充沛
    vol_collapsed = ind['vol_ratio'] < 0.7        # 量能枯竭
    ma5_rising = ind['ma5_slope'] > 0.3           # MA5在上升
    ma5_strong_rise = ind['ma5_slope'] > 1.0      # MA5加速
    ma20_rising = ind['ma20_slope'] > 0.2         # 中期趋势
    bull_align = (price > ind['ma5'] > ind['ma10'] > ind['ma20'])  # 完美多头
    mid_range = 25 <= ind['pos_60'] <= 75         # 中枢位置
    too_high = ind['pos_60'] > 88                 # 极端高位
    bb_ok = 0.1 <= ind['bb_pos'] <= 0.9           # BB带内
    bb_extreme = ind['bb_pos'] > 1.05             # BB突破上轨
    price_diverges = ind['vol_divergence']         # 量价背离

    # ============ 量能 (30分) — 最强单因子 ============
    vol_score = 0
    if vol_strong:
        vol_score += 20; reasons.append(f"量能充沛({ind['vol_ratio']:.1f}x)")
    elif vol_expanding:
        vol_score += 14; reasons.append(f"量能健康({ind['vol_ratio']:.1f}x)")
    elif vol_collapsed:
        vol_score += 2; warnings.append(f"量能枯竭({ind['vol_ratio']:.1f}x)")
    else:
        vol_score += 7  # 中性量能

    # 成交额趋势 (资金方向)
    if ind['amount_trend'] > 20:
        vol_score += 7; reasons.append("💰持续流入")
    elif ind['amount_trend'] > 5:
        vol_score += 4
    elif ind['amount_trend'] < -15:
        vol_score += 0; warnings.append("资金撤退")

    # 连续放量: 持续的量能比单日放量更有意义
    if ind['consec_vol_up'] >= 3:
        vol_score += 3; reasons.append(f"连{ind['consec_vol_up']}日放量")

    score += min(vol_score, 30)

    # ============ 趋势质量 (25分) ============
    trend_score = 0

    # MA5斜率是方向盘
    if ma5_strong_rise:
        trend_score += 12; reasons.append("MA5加速↑")
    elif ma5_rising:
        trend_score += 8; reasons.append("MA5上升")
    else:
        trend_score += 2

    # 价格与均线关系
    if bull_align:
        trend_score += 8; reasons.append("多头排列")
    elif price > ind['ma5']:
        trend_score += 5; reasons.append("站上MA5")
    elif price > ind['ma20']:
        trend_score += 3

    # 中期趋势确认
    if ma20_rising:
        trend_score += 5; reasons.append("中期趋势↑")

    score += min(trend_score, 25)

    # ============ 位置安全 (15分) ============
    pos_score = 0

    if mid_range:
        pos_score += 10; reasons.append(f"中枢安全({ind['pos_60']:.0f}%)")
    elif too_high:
        pos_score += 2; warnings.append(f"极高位({ind['pos_60']:.0f}%)")
    elif ind['pos_60'] < 25:
        pos_score += 5; reasons.append(f"底部区域({ind['pos_60']:.0f}%)")
    else:
        pos_score += 6

    if bb_ok:
        pos_score += 5
    elif bb_extreme:
        pos_score += 1; warnings.append("BB突破上轨")
    else:
        pos_score += 3

    score += min(pos_score, 15)

    # ============ 反转风险 (扣分, 最多-30) ============
    penalty = 0

    # 最强反转信号: 量价背离
    if price_diverges:
        penalty -= 12; warnings.append("量价背离!")
    elif not vol_expanding and ind['ret_5d'] > 5:
        # 涨了但没量 → 虚涨
        penalty -= 6; warnings.append("虚涨无量")

    # RSI极端 + 动量衰减
    if ind['rsi'] > RSI_EXTREME:
        if vol_collapsed and not ma5_rising:
            penalty -= 12; warnings.append("RSI极端+动量衰竭")
        elif vol_collapsed:
            penalty -= 6; warnings.append(f"RSI{ind['rsi']:.0f}高+量缩")
        elif not ma5_rising:
            penalty -= 5
        else:
            # RSI高但量+MA都OK → 动量健康, 微罚
            penalty -= 1
    elif ind['rsi'] > RSI_OVERBOUGHT:
        if not vol_expanding:
            penalty -= 5; warnings.append(f"RSI{ind['rsi']:.0f}超买+量不足")

    # BB极端+高位
    if bb_extreme and too_high:
        penalty -= 8; warnings.append("BB极值+高位")

    # 异常放量(>3.5x) → 可能是出货
    if ind['vol_ratio'] > 3.5:
        penalty -= 8; warnings.append("异常天量")

    score += max(penalty, -30)

    # ============ 适配性 (20分) — 小资金专属 ============
    fit_score = 0

    # 可买性
    cost_100 = price * 100
    if cost_100 <= CAPITAL * 0.8:
        n_lots = int(CAPITAL * 0.8 // cost_100)
        if n_lots >= 5:
            fit_score += 8; reasons.append(f"可买{n_lots}手")
        elif n_lots >= 3:
            fit_score += 6; reasons.append(f"可买{n_lots}手")
        else:
            fit_score += 4
    elif cost_100 <= CAPITAL * 1.2:
        fit_score += 2
    else:
        fit_score -= 3

    # 当日涨幅甜点
    if 2 <= change <= 6:
        fit_score += 7; reasons.append(f"涨幅甜点{change:+.1f}%")
    elif 0 < change <= 2:
        fit_score += 4
    elif 6 < change <= 8:
        fit_score += 3

    # 小市值弹性加分
    mkt_cap = stock.get('market_cap', 0) or 0
    if 10 < mkt_cap < 80:
        fit_score += 3
    elif 5 <= mkt_cap <= 10:
        fit_score += 5; reasons.append("极小盘弹性")

    # MACD金叉加分
    if ind['macd_signal'] == '金叉↑':
        fit_score += 2; reasons.append("MACD金叉")

    score += min(max(fit_score, 0), 20)

    return max(0, min(100, score)), reasons, warnings


# ============================================================
# 5. 板块追顶过滤器
# ============================================================
def sector_chase_filter(stock_name, sector_map):
    """
    检测该股所属板块是否当日暴涨(追顶风险)
    返回: (是否追顶风险, 板块名, 板块涨幅)

    策略: 从东方财富板块资金流数据中, 用股票名关键词直接匹配板块名
    板块名来自东财实时数据, 如"电信运营商"、"元件"、"自动化设备"等
    """
    if not sector_map:
        return False, None, 0

    # 股票名关键词 → 板块名关键词 (按优先级)
    stock_kw_to_sector_kw = [
        # 通信/5G/电信
        (['联通', '电信', '移动', '通信', '5G', '通讯', '光纤', '烽火', '长飞', '亨通', '中天'],
         ['电信', '通信', '5G', '通讯', '光纤']),
        # 电力/能源
        (['电力', '发电', '能源', '电网', '电气', '风电', '光伏', '太阳能', '核能', '水电', '火电', '新能', '大唐', '华能', '华电'],
         ['电力', '发电', '能源', '电网', '风电', '光伏']),
        # 电子/半导体/芯片
        (['电子', '芯片', '半导体', '电路', '晶圆', '封测', '集成', '海光', '中芯', '韦尔'],
         ['电子', '芯片', '半导体', '电路', '集成']),
        # 元件/PCB
        (['元件', '电路板', 'PCB', '印制', '东山', '景旺', '崇达', '胜宏'],
         ['元件', '电路板', 'PCB', '印制']),
        # 汽车
        (['汽车', '汽配', '轮胎', '电机', '方正', '凌云', '交运'],
         ['汽车', '汽配', '轮胎', '电机']),
        # 自动化/机械
        (['机械', '设备', '重工', '自动化', '华工', '汇川', '机器'],
         ['机械', '设备', '重工', '自动化']),
        # 化工/材料
        (['化工', '化学', '材料', '化纤', '石化', '油气', '石油', '炼化', '宝丰', '万华'],
         ['化工', '化学', '材料', '化纤', '油气', '石油', '炼化']),
        # 建筑/工程
        (['建筑', '建工', '工程', '电建', '能建', '建材', '水泥', '管业', '青龙'],
         ['建筑', '工程', '建材', '水泥', '专业工程']),
        # 煤炭/矿业
        (['煤炭', '煤业', '矿业', '神华', '中煤'],
         ['煤炭', '矿业']),
        # 广告/传媒/数字媒体
        (['传媒', '数字', '广告', '影视', '广电', '出版', '营销'],
         ['传媒', '数字', '广告', '影视', '广电', '出版', '营销']),
        # 医药
        (['医药', '药业', '生物', '制药', '医疗', '器械'],
         ['医药', '药业', '生物', '医疗', '器械']),
        # 环保/绿色
        (['环保', '绿色', '节能', '生态', '环境', '再生'],
         ['环保', '绿色', '节能']),
        # 食品
        (['食品', '乳业', '饮料', '啤酒', '白酒', '零食', '三只', '伊利', '蒙牛'],
         ['食品', '饮料', '乳业']),
    ]

    for name_kws, sector_kws in stock_kw_to_sector_kw:
        if any(kw in stock_name for kw in name_kws):
            # 在板块数据中查找匹配
            for sname, sdata in sector_map.items():
                if any(skw in sname for skw in sector_kws):
                    if sdata['change_pct'] > SECTOR_CHASE_LIMIT:
                        return True, sname, sdata['change_pct']
            break  # 找到匹配的行业类别后停止

    return False, None, 0


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 75)
    print("  A股短线扫描器 v3 — 修复版")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  条件: {MIN_PRICE}-{MAX_PRICE}元 | 资金{CAPITAL:.0f}元 | 止损{STOP_LOSS_PCT}%")
    print(f"  v3修复: RSI中性区 | 追顶过滤器 | 量价背离 | 多级筛选")
    print("=" * 75)

    # Step 0: 拉取板块资金(防追顶用)
    print("\n[0/4] 拉取板块资金流向...")
    sector_map = fetch_sector_flow()
    hot_sectors = [(k, v['change_pct']) for k, v in sector_map.items() if v['change_pct'] > 3]
    hot_sectors.sort(key=lambda x: x[1], reverse=True)
    if hot_sectors:
        print(f"  当日热门板块(涨幅>3%):")
        for name, chg in hot_sectors[:5]:
            print(f"    {name}: +{chg:.2f}% {'⚠追顶风险!' if chg > SECTOR_CHASE_LIMIT else ''}")

    # Step 1: 拉取全市场行情
    print("\n[1/4] 拉取全A股实时行情...")
    stocks = fetch_market_data()
    print(f"  -> 筛选出 {len(stocks)} 只候选股 ({MIN_PRICE}-{MAX_PRICE}元)")

    # Step 2: MUST-PASS 预筛选 + 技术分析
    print(f"\n[2/4] MUST-PASS预筛选 → 技术分析 → v3评分...")
    passed_must = []
    failed_must = 0

    # 排序: 活跃度优先
    active = [s for s in stocks if s['change_pct'] > -5]
    active.sort(key=lambda x: x['turnover'], reverse=True)
    candidates = active[:100]

    for i, s in enumerate(candidates):
        if (i + 1) % 20 == 0:
            print(f"   进度: {i+1}/{len(candidates)}")

        kline = fetch_kline(s['code'])
        ind = calc_indicators(kline)

        # MUST-PASS
        ok, failures = must_pass_filter(s, ind)
        if not ok:
            failed_must += 1
            continue

        # 板块追顶检查
        is_chase, sec_name, sec_chg = sector_chase_filter(s['name'], sector_map)
        if is_chase:
            ind['sector_chase_warning'] = f"{sec_name}+{sec_chg:.1f}%"

        # v3评分
        sc, reasons, warnings = score_stock_v3(s, ind, sector_map)
        passed_must.append({
            **s, 'indicators': ind,
            'score': sc, 'reasons': reasons, 'warnings': warnings,
        })
        time.sleep(0.25)

    print(f"  MUST-PASS通过: {len(passed_must)}, 淘汰: {failed_must}")

    # Step 3: 排序输出
    passed_must.sort(key=lambda x: x['score'], reverse=True)
    top = passed_must[:TOP_N]

    print(f"\n[3/4] v3评分完成! 输出前{TOP_N}只\n")

    # --- 输出 ---
    print("=" * 75)
    print("  🎯 v3 短线精选 TOP CANDIDATES")
    print("=" * 75)

    for rank, s in enumerate(top, 1):
        ind = s['indicators']
        price = s['price']
        shares = max(1, int(CAPITAL * MAX_POSITION_PCT // (price * 100)))

        stop_loss_price = price * (1 - STOP_LOSS_PCT / 100)
        max_loss = (price - stop_loss_price) * shares * 100
        target = ind['resistance_20'] if ind['resistance_20'] > price else price * 1.04
        rr = (target - price) / (price - stop_loss_price) if price > stop_loss_price else 0

        # 标签
        if s['score'] >= 70:
            tag = "🟢买入"
        elif s['score'] >= 55:
            tag = "🔵关注"
        elif s['score'] >= 40:
            tag = "⚪观望"
        else:
            tag = "🔴跳过"

        print(f"\n{'─' * 75}")
        print(f"  #{rank} {tag} | {s['name']}({s['code']}) | 评分:{s['score']:.0f}/100")
        print(f"    现价:{price:.2f} | 涨幅:{s['change_pct']:+.2f}% | "
              f"成交额:{s['turnover']/1e8:.1f}亿")
        print(f"    量比:{ind['vol_ratio']:.1f}x(5日) {ind['vol_ratio_20']:.1f}x(20日) | "
              f"资金趋势:{ind['amount_trend']:+.0f}%")
        print(f"    MA5斜率:{ind['ma5_slope']:+.1f}% | MA20斜率:{ind['ma20_slope']:+.1f}% | "
              f"RSI:{ind['rsi']:.0f} | {ind['macd_signal']}")
        print(f"    60日位置:{ind['pos_60']:.0f}% | BB:{ind['bb_pos']*100:.0f}% | "
              f"连阳:{ind['up_days']}天 | 连放量:{ind['consec_vol_up']}天")
        print(f"    5日:{ind['ret_5d']:+.1f}% | 10日:{ind['ret_10d']:+.1f}%")
        print(f"    ── 交易计划 ──")
        pos_pct = shares * price * 100 / CAPITAL * 100
        print(f"    买入: {shares}手 = {shares*price*100:.0f}元 (占{pos_pct:.0f}%)")
        print(f"    止损: {stop_loss_price:.2f} (亏损{max_loss:.0f}元)")
        print(f"    目标: {target:.2f} | 盈亏比: {rr:.1f}")
        if s['reasons']:
            print(f"    信号: {' | '.join(s['reasons'][:5])}")
        if s['warnings']:
            print(f"    ⚠ 警告: {' | '.join(s['warnings'][:4])}")
        if ind.get('vol_divergence'):
            print(f"    🔴 量价背离!")
        if ind.get('sector_chase_warning'):
            print(f"    🔴 板块追顶: {ind['sector_chase_warning']}")

    # Step 4: 自选股快照
    print(f"\n[4/4] 自选股 + 持仓股技术快照")
    print(f"{'=' * 75}")
    watchlist = {
        '601991': '大唐发电', '601678': '滨化股份', '601727': '上海电气',
        '601669': '中国电建', '600480': '凌云股份',
        '600973': '宝胜股份', '002229': '鸿博股份',
    }
    for code, name in watchlist.items():
        kline = fetch_kline(code)
        if kline:
            ind = calc_indicators(kline)
            if ind:
                print(f"  {name}({code}) | {ind['latest']:.2f} | "
                      f"Vr:{ind['vol_ratio']:.1f}x | {ind['macd_signal']} | "
                      f"RSI:{ind['rsi']:.0f} | J:{ind['kdj_j']:.0f} | "
                      f"Pos60:{ind['pos_60']:.0f}% | 5d:{ind['ret_5d']:+.1f}%")
        time.sleep(0.25)

    # 保存JSON
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    output_file = os.path.join(OUTPUT_DIR, f"scan_v3_{ts}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        serializable = []
        for s in top:
            sd = {k: v for k, v in s.items() if k != 'indicators'}
            sd['indicators'] = {k: (round(float(v), 4) if isinstance(v, (float, int)) else v)
                                for k, v in s['indicators'].items()}
            serializable.append(sd)
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"\n  💾 v3扫描结果: {output_file}")

    print(f"\n  Done. {datetime.now().strftime('%H:%M:%S')}")
    return top


if __name__ == '__main__':
    main()
