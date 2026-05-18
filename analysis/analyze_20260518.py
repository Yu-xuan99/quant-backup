#!/usr/bin/env python3
"""
Quantitative Analysis — 2026-05-18
Portfolio: 大唐发电(601991) + 滨化股份(601678) (sold May 14?)
Plan:     BUY 上海电气(601727) 3手
Full re-evaluation with fresh K-line data + sector flow
"""
import requests
import json
import time
from datetime import datetime

CAPITAL = 3622.0
STOP_LOSS_PCT = 2.0

# ============================================================
# Data Fetch Layer
# ============================================================
def fetch_kline(code, period='day', count=60):
    """腾讯财经K线"""
    market = 'sz' if code.startswith(('0', '3')) else 'sh'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},{period},,,{count},qfq"
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if data.get('code') == 0:
            stock_key = f"{market}{code}"
            return data['data'][stock_key].get(f'qfq{period}', [])
    except Exception as e:
        print(f"  K线拉取失败 {code}: {e}")
    return None


def fetch_sector_flow():
    """东方财富板块资金流向"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 30, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2,
        "fid": "f62",  # 主力净流入
        "fs": "m:90+t:2",  # 行业板块
        "fields": "f2,f3,f4,f12,f14,f62,f184,f66,f69"
    }
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        data = r.json()
        items = data.get('data', {}).get('diff', [])
        sectors = []
        for item in items:
            sectors.append({
                'code': item.get('f12', ''),
                'name': item.get('f14', ''),
                'change_pct': item.get('f3', 0) or 0,
                'net_inflow': (item.get('f62', 0) or 0) / 1e8,
                'main_inflow': (item.get('f66', 0) or 0) / 1e8,
                'turnover': (item.get('f184', 0) or 0) / 1e8,
            })
        return sectors
    except Exception as e:
        print(f"  板块数据拉取失败: {e}")
    return []


def fetch_stock_realtime(code):
    """个股实时行情 东方财富"""
    market = '0' if code.startswith(('0', '3')) else '1'
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": f"{market}.{code}",
        "fields": "f43,f44,f45,f46,f47,f48,f50,f51,f52,f55,f57,f58,f60,f116,f117,f162,f167,f168,f169,f170",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281"
    }
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        data = r.json().get('data', {})
        return {
            'price': data.get('f43', 0) / 100 if data.get('f43') else 0,
            'high': data.get('f44', 0) / 100 if data.get('f44') else 0,
            'low': data.get('f45', 0) / 100 if data.get('f45') else 0,
            'open': data.get('f46', 0) / 100 if data.get('f46') else 0,
            'volume': data.get('f47', 0),
            'turnover': data.get('f48', 0),
            'change_pct': data.get('f170', 0) / 100 if data.get('f170') else 0,
            'change_amt': data.get('f169', 0) / 100 if data.get('f169') else 0,
            'pe': data.get('f162', 0) / 100 if data.get('f162') else 0,
            'market_cap': data.get('f116', 0) / 1e8 if data.get('f116') else 0,
        }
    except Exception as e:
        print(f"  实时行情拉取失败 {code}: {e}")
    return None


# ============================================================
# Technical Analysis Engine
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

    def ma(arr, period):
        if len(arr) < period: return arr[-1]
        return sum(arr[-period:]) / period

    def ema(arr, period):
        if len(arr) < period: return arr[-1]
        k = 2 / (period + 1)
        result = sum(arr[:period]) / period
        for v in arr[period:]:
            result = v * k + result * (1 - k)
        return result

    ma5 = ma(closes, 5)
    ma10 = ma(closes, 10)
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60) if n >= 60 else ma30

    vol5_avg = sum(volumes[-5:]) / 5
    vol20_avg = sum(volumes[-20:]) / 20
    vol_ratio = vol5_avg / vol20_avg if vol20_avg > 0 else 1

    ret_3d = (closes[-1] / closes[-3] - 1) * 100 if n >= 3 else 0
    ret_5d = (closes[-1] / closes[-5] - 1) * 100 if n >= 5 else 0
    ret_10d = (closes[-1] / closes[-10] - 1) * 100 if n >= 10 else 0

    resistance_20 = max(highs[-20:])
    support_20 = min(lows[-20:])

    h60 = max(highs[-60:]) if n >= 60 else max(highs)
    l60 = min(lows[-60:]) if n >= 60 else min(lows)
    pos_60 = (latest - l60) / (h60 - l60) * 100 if h60 != l60 else 50

    # MACD
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = ema12 - ema26
    dif_hist = []
    for i in range(13, len(closes) + 1):
        e12 = ema(closes[:i], 12)
        e26 = ema(closes[:i], 26)
        dif_hist.append(e12 - e26)
    dea = ema(dif_hist, 9) if len(dif_hist) >= 9 else dif
    prev_dea = ema(dif_hist[:-1], 9) if len(dif_hist) > 9 else dif
    prev_dif = dif_hist[-2] if len(dif_hist) > 1 else dif

    if prev_dif < prev_dea and dif > dea:
        macd_signal = "金叉↑"
    elif prev_dif > prev_dea and dif < dea:
        macd_signal = "死叉↓"
    elif dif > 0:
        macd_signal = "多头"
    else:
        macd_signal = "空头"

    # RSI14
    if n >= 15:
        gains, losses = [], []
        for i in range(n-14, n):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        rsi = 100 - 100 / (1 + avg_gain / avg_loss) if avg_loss > 0 else 100
    else:
        rsi = 50

    # Bollinger
    bb_mid = ma(closes, 20)
    bb_std = (sum((c - bb_mid)**2 for c in closes[-20:]) / 20) ** 0.5
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_pos = (latest - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

    # KDJ
    if n >= 9:
        h9 = max(highs[-9:])
        l9 = min(lows[-9:])
        rsv = (latest - l9) / (h9 - l9) * 100 if h9 != l9 else 50
        # simplified KDJ
        k = rsv * 1/3 + 50 * 2/3
        d = k * 1/3 + 50 * 2/3
        j = 3 * k - 2 * d
    else:
        k = d = j = 50

    # ATR
    trs = []
    for i in range(max(1, n-14), n):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.01

    pct_from_ma5 = (latest / ma5 - 1) * 100
    pct_from_resistance = (latest - resistance_20) / resistance_20 * 100

    # Consecutive up/down days
    up_days = 0
    for i in range(n-1, 0, -1):
        if closes[i] > closes[i-1]:
            up_days += 1
        else:
            break
    down_days = 0
    for i in range(n-1, 0, -1):
        if closes[i] < closes[i-1]:
            down_days += 1
        else:
            break

    return {
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'vol_ratio': vol_ratio,
        'ret_3d': ret_3d, 'ret_5d': ret_5d, 'ret_10d': ret_10d,
        'pos_60': pos_60, 'bb_pos': bb_pos,
        'bb_upper': bb_upper, 'bb_lower': bb_lower,
        'macd_signal': macd_signal, 'dif': dif, 'dea': dea,
        'rsi': rsi,
        'kdj_k': k, 'kdj_d': d, 'kdj_j': j,
        'atr': atr,
        'resistance_20': resistance_20, 'support_20': support_20,
        'pct_from_ma5': pct_from_ma5, 'pct_from_resistance': pct_from_resistance,
        'up_days': up_days, 'down_days': down_days,
        'latest': latest,
    }


# ============================================================
# Scoring Engine
# ============================================================
def score_stock(stock_info, ind):
    """Score a stock from 0-100 for short-term momentum trading"""
    if ind is None:
        return 0, ["数据不足"]

    score = 0
    reasons = []
    price = stock_info.get('price', ind['latest'])
    change = stock_info.get('change_pct', 0)

    # Trend (25 pts max)
    if ind['ret_5d'] > 0 and ind['ret_10d'] > 0:
        score += 12; reasons.append("短期上升趋势")
    elif ind['ret_5d'] > 0:
        score += 7; reasons.append("近5日上涨")

    if price > ind['ma5']:
        score += 8; reasons.append("站上MA5")
    if ind['ma5'] > ind['ma10']:
        score += 5; reasons.append("MA5>MA10")

    # Volume (20 pts max)
    if 1.5 <= ind['vol_ratio'] <= 3.0:
        score += 15; reasons.append(f"温和放量({ind['vol_ratio']:.1f}x)")
    elif 1.2 <= ind['vol_ratio'] < 1.5:
        score += 10; reasons.append(f"量能正常({ind['vol_ratio']:.1f}x)")
    elif ind['vol_ratio'] > 3.0:
        score += 5; reasons.append(f"异常放量({ind['vol_ratio']:.1f}x)")

    if ind['ret_3d'] > 0:
        score += 5; reasons.append("近3日正动量")

    # Technical (25 pts max)
    if ind['macd_signal'] == '金叉↑':
        score += 15; reasons.append("MACD金叉")
    elif ind['macd_signal'] == '多头':
        score += 10; reasons.append("MACD多头")
    elif ind['macd_signal'] == '空头':
        if ind['dif'] > -0.05:
            score += 3; reasons.append("MACD趋平")

    if 40 <= ind['rsi'] <= 70:
        score += 10; reasons.append(f"RSI健康({ind['rsi']:.0f})")
    elif 30 <= ind['rsi'] < 40:
        score += 5; reasons.append(f"RSI偏低({ind['rsi']:.0f})")

    # Position (20 pts max)
    if 20 <= ind['pos_60'] <= 65:
        score += 12; reasons.append(f"价格中枢({ind['pos_60']:.0f}%)")
    elif ind['pos_60'] < 20:
        score += 8; reasons.append(f"低位({ind['pos_60']:.0f}%)")
    else:
        score += 3; reasons.append(f"高位区({ind['pos_60']:.0f}%)")

    if ind['pct_from_resistance'] > -2:
        score += 5; reasons.append("逼近突破")
    if ind['pct_from_resistance'] > 0:
        score += 3; reasons.append("已突破20日高")

    # Capital fit (10 pts max)
    cost_100 = price * 100
    if cost_100 <= CAPITAL * 0.95:
        score += 8
        n_lots = int(CAPITAL // cost_100)
        reasons.append(f"可买{n_lots}手")
    elif cost_100 <= CAPITAL * 1.3:
        score += 4; reasons.append("勉强1手")

    # Day change
    if 2 <= change <= 6:
        score += 5; reasons.append(f"温和上涨{change:+.1f}%")
    elif 0 < change < 2:
        score += 3
    elif change > 8:
        score -= 5; reasons.append("追高风险")

    if ind['ret_5d'] > 15:
        score -= 8; reasons.append("5日涨幅过大")
    if ind['ret_5d'] > 20:
        score -= 10
    if change > 9.5:
        score -= 20; reasons.append("已涨停")

    return max(0, min(100, score)), reasons


# ============================================================
# Position Analysis
# ============================================================
def analyze_position(name, code, cost, shares, current_price, ind):
    """Analyze existing position and generate decision"""
    pnl_pct = (current_price / cost - 1) * 100
    pnl_amt = (current_price - cost) * shares
    stop_price = cost * (1 - STOP_LOSS_PCT / 100)
    trailing_stop = current_price * 0.98  # 2% trailing

    # Decision logic
    decision = "HOLD"
    action_detail = ""

    if pnl_pct <= -STOP_LOSS_PCT:
        decision = "SELL_STOP"
        action_detail = f"触发硬止损{STOP_LOSS_PCT}%"
    elif current_price <= stop_price * 1.005:
        decision = "SELL_STOP"
        action_detail = f"紧贴止损线"

    # Profit-taking logic
    if pnl_pct >= 8:
        decision = "SELL_TAKE_PROFIT"
        action_detail = f"盈利{pnl_pct:.0f}%达标止盈"
    elif pnl_pct >= 5:
        # Move stop to cost + 1%
        if current_price < cost * 1.03:
            decision = "SELL_TRAILING"
            action_detail = "浮动止盈:跌破成本+1%则离场"

    # Technical deterioration
    if ind and decision == "HOLD":
        if ind['macd_signal'] == '死叉↓' and pnl_pct > 0:
            decision = "SELL_SIGNAL"
            action_detail = "MACD死叉+有浮盈,先落袋"
        elif ind['rsi'] > 85:
            decision = "SELL_SIGNAL"
            action_detail = f"RSI极度超买({ind['rsi']:.0f})"
        elif ind['pct_from_ma5'] < -3:
            decision = "SELL_SIGNAL"
            action_detail = f"跌破MA5 {ind['pct_from_ma5']:+.1f}%"

    return {
        'name': name, 'code': code,
        'cost': cost, 'shares': shares,
        'current': current_price,
        'pnl_pct': pnl_pct, 'pnl_amt': pnl_amt,
        'stop_loss': round(stop_price, 2),
        'trailing_stop': round(trailing_stop, 2),
        'decision': decision,
        'action_detail': action_detail,
        'indicators': ind,
    }


# ============================================================
# Main Analysis
# ============================================================
def main():
    print("=" * 75)
    print("  📊 QUANTITATIVE FINANCIAL ANALYSIS — " + datetime.now().strftime('%Y-%m-%d %H:%M'))
    print("  策略: 动量追涨 + 严格止损2% + 板块资金轮动")
    print(f"  总资金: {CAPITAL:.0f}元")
    print("=" * 75)

    # ---- Step 1: Fetch Sector Flow ----
    print("\n[1/4] 拉取板块资金流向 (东方财富)...")
    sectors = fetch_sector_flow()
    time.sleep(0.5)

    if sectors:
        print(f"  板块资金流向 TOP10:")
        for i, s in enumerate(sectors[:10], 1):
            arrow = "↑" if s['net_inflow'] > 0 else "↓"
            print(f"    #{i:2d} {s['name']:12s} | {s['change_pct']:+6.2f}% | "
                  f"主力{arrow}{abs(s['net_inflow']):.1f}亿 | 成交{s['turnover']:.1f}亿")
    else:
        print("  ⚠ 板块数据获取失败，继续分析...")

    # ---- Step 2: Portfolio Stocks K-line ----
    print("\n[2/4] 拉取持仓+候选股 K线数据 (腾讯财经)...")

    portfolio = {
        '601991': {'name': '大唐发电', 'cost': 7.26, 'shares': 100},
        '601678': {'name': '滨化股份', 'cost': 5.07, 'shares': 100},
        '601727': {'name': '上海电气', 'cost': None, 'shares': 0},
    }
    watchlist = {
        '601669': '中国电建',
        '600480': '凌云股份',
        '600973': '宝胜股份',
        '002229': '鸿博股份',
    }

    all_stocks = {}
    for code, info in portfolio.items():
        kline = fetch_kline(code)
        if kline:
            ind = calc_indicators(kline)
            rt = fetch_stock_realtime(code)
            all_stocks[code] = {
                'name': info['name'],
                'kline': kline,
                'indicators': ind,
                'realtime': rt,
                'cost': info['cost'],
                'shares': info['shares'],
            }
            print(f"  ✓ {info['name']}({code})", end='')
            if rt:
                print(f" | {rt['price']:.2f} ({rt['change_pct']:+.2f}%)")
            else:
                if ind:
                    print(f" | {ind['latest']:.2f} (K线收盘)")
                else:
                    print()
        time.sleep(0.3)

    for code, name in watchlist.items():
        kline = fetch_kline(code)
        if kline:
            ind = calc_indicators(kline)
            rt = fetch_stock_realtime(code)
            all_stocks[code] = {
                'name': name,
                'kline': kline,
                'indicators': ind,
                'realtime': rt,
                'cost': None,
                'shares': 0,
            }
            print(f"  ✓ {name}({code})", end='')
            if rt:
                print(f" | {rt['price']:.2f} ({rt['change_pct']:+.2f}%)")
            else:
                if ind:
                    print(f" | {ind['latest']:.2f} (K线收盘)")
                else:
                    print()
        time.sleep(0.3)

    # ---- Step 3: Position Analysis ----
    print("\n[3/4] 持仓诊断...")
    positions = []
    for code, info in all_stocks.items():
        if info['cost'] is not None and info['shares'] > 0:
            price = info['realtime']['price'] if info['realtime'] else info['indicators']['latest']
            pos = analyze_position(info['name'], code, info['cost'], info['shares'], price, info['indicators'])
            positions.append(pos)

    for pos in positions:
        ind = pos['indicators']
        print(f"\n  {'='*65}")
        print(f"  {pos['name']}({pos['code']}) | 决策: {pos['decision']}")
        print(f"  {'='*65}")
        print(f"  成本:{pos['cost']:.2f} → 现价:{pos['current']:.2f} | "
              f"盈亏:{pos['pnl_pct']:+.2f}% ({pos['pnl_amt']:+.0f}元)")
        print(f"  止损:{pos['stop_loss']:.2f} | 移动止损:{pos['trailing_stop']:.2f}")
        if pos['action_detail']:
            print(f"  触发信号: {pos['action_detail']}")
        if ind:
            print(f"  ── 技术指标 ──")
            print(f"  MA5:{ind['ma5']:.2f} MA10:{ind['ma10']:.2f} MA20:{ind['ma20']:.2f} "
                  f"MA60:{ind['ma60']:.2f}")
            print(f"  MACD:{ind['macd_signal']} | RSI:{ind['rsi']:.0f} | "
                  f"KDJ-J:{ind['kdj_j']:.0f}")
            print(f"  量比:{ind['vol_ratio']:.1f}x | 60日位置:{ind['pos_60']:.0f}% | "
                  f"BB位置:{ind['bb_pos']*100:.0f}%")
            print(f"  5日动量:{ind['ret_5d']:+.1f}% | 10日:{ind['ret_10d']:+.1f}% | "
                  f"连阳:{ind['up_days']}天 连阴:{ind['down_days']}天")

    # ---- Step 4: Buy Candidates Scoring ----
    print(f"\n[4/4] 买入候选评分...")
    candidates = []
    for code, info in all_stocks.items():
        if info['cost'] is None:  # Not currently held
            ind = info['indicators']
            if ind is None:
                continue
            price = info['realtime']['price'] if info['realtime'] else ind['latest']
            change = info['realtime']['change_pct'] if info['realtime'] else 0
            stock_info = {'price': price, 'change_pct': change}
            sc, reasons = score_stock(stock_info, ind)

            # Calculate trade plan
            shares = max(1, int(CAPITAL // (price * 100)))
            stop_price = price * (1 - STOP_LOSS_PCT / 100)
            max_loss = (price - stop_price) * shares * 100
            target = ind['resistance_20'] if ind['resistance_20'] > price else price * 1.05
            rr = (target - price) / (price - stop_price) if price > stop_price else 0

            candidates.append({
                'name': info['name'],
                'code': code,
                'price': price,
                'change_pct': change,
                'indicators': ind,
                'score': sc,
                'reasons': reasons,
                'shares': shares,
                'cost_total': shares * price * 100,
                'stop_price': stop_price,
                'max_loss': max_loss,
                'target': target,
                'rr_ratio': rr,
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)

    for rank, c in enumerate(candidates, 1):
        ind = c['indicators']
        tag = "🟢买入" if c['score'] >= 70 else "🔵关注" if c['score'] >= 55 else "⚪观望" if c['score'] >= 40 else "🔴跳过"
        print(f"\n  #{rank} {tag} | {c['name']}({c['code']}) | 评分:{c['score']}/100")
        print(f"    现价:{c['price']:.2f} | 涨跌:{c['change_pct']:+.2f}%")
        print(f"    量比:{ind['vol_ratio']:.1f}x | 5日:{ind['ret_5d']:+.1f}% | "
              f"MACD:{ind['macd_signal']} | RSI:{ind['rsi']:.0f}")
        print(f"    60日位置:{ind['pos_60']:.0f}% | BB:{ind['bb_pos']*100:.0f}% | "
              f"阻力:{ind['resistance_20']:.2f}")
        print(f"    买入{c['shares']}手 = {c['cost_total']:.0f}元 | "
              f"止损:{c['stop_price']:.2f} (亏{c['max_loss']:.0f}元) | "
              f"目标:{c['target']:.2f} | 盈亏比:{c['rr_ratio']:.1f}")
        if c['reasons']:
            print(f"    信号: {' | '.join(c['reasons'][:6])}")

    # ---- Step 5: Generate Trading Plan ----
    print(f"\n{'=' * 75}")
    print(f"  📋 明日交易计划 (2026-05-19)")
    print(f"{'=' * 75}")

    # Summary of actions
    total_cash = CAPITAL
    for pos in positions:
        total_cash += pos['current'] * pos['shares']

    # Print sell actions first
    for pos in positions:
        if 'SELL' in pos['decision']:
            print(f"\n  🔴 卖出: {pos['name']}({pos['code']})")
            print(f"     理由: {pos['action_detail']}")
            print(f"     现价:{pos['current']:.2f} | 盈亏:{pos['pnl_pct']:+.2f}%")
            estimated_cash = pos['current'] * pos['shares']

    # Print hold actions
    for pos in positions:
        if pos['decision'] == 'HOLD':
            print(f"\n  🟡 持有: {pos['name']}({pos['code']})")
            print(f"     现价:{pos['current']:.2f} | 盈亏:{pos['pnl_pct']:+.2f}%")
            print(f"     止损: {pos['stop_loss']:.2f} | 移动止损: {pos['trailing_stop']:.2f}")

    # Best buy candidate
    if candidates and candidates[0]['score'] >= 55:
        best = candidates[0]
        print(f"\n  🟢 买入首选: {best['name']}({best['code']}) — 评分{best['score']}")
        print(f"     现价:{best['price']:.2f} | 买入{best['shares']}手 = {best['cost_total']:.0f}元")
        print(f"     止损:{best['stop_price']:.2f} | 目标:{best['target']:.2f} | 盈亏比:{best['rr_ratio']:.1f}")
        print(f"     理由: {' | '.join(best['reasons'][:4])}")

    if len(candidates) > 1 and candidates[1]['score'] >= 50:
        b2 = candidates[1]
        print(f"\n  🔵 备选: {b2['name']}({b2['code']}) — 评分{b2['score']}")
        print(f"     现价:{b2['price']:.2f} | 止损:{b2['stop_price']:.2f} | 盈亏比:{b2['rr_ratio']:.1f}")

    # Risk summary
    print(f"\n  {'='*65}")
    print(f"  ⚡ 风险控制")
    print(f"  {'='*65}")
    print(f"  总资产估值: {total_cash:.0f}元")
    print(f"  单日最大亏损上限: {total_cash * 0.02:.0f}元 (2%)")
    print(f"  策略纪律: 止损触发即执行, 不可移动止损位, 不追涨停板")

    # Save output
    output = {
        'timestamp': datetime.now().isoformat(),
        'total_capital': CAPITAL,
        'estimated_total_assets': total_cash,
        'positions': positions,
        'candidates': [{k: v for k, v in c.items() if k != 'indicators'} for c in candidates],
        'sector_flow': sectors[:15] if sectors else [],
    }

    output_file = f"C:/Users/34077/Desktop/quant-backup/data/snapshots/analysis_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        # Custom serializer for non-serializable types
        def convert(obj):
            if isinstance(obj, dict):
                return {k: convert(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert(v) for v in obj]
            elif isinstance(obj, float):
                return round(obj, 4)
            return obj
        json.dump(convert(output), f, ensure_ascii=False, indent=2)

    print(f"\n  💾 分析保存: {output_file}")
    print(f"\n  Done. {datetime.now().strftime('%H:%M:%S')}")
    return output


if __name__ == '__main__':
    main()
