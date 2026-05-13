#!/usr/bin/env python3
"""
A股全市场扫描器 v2 - 短线追涨模式
条件: 价格<17元, 资金~3600元, 追涨/强势突破, 止损2%
数据源: 东方财富 + 腾讯K线
"""
import requests
import json
import time
import os
from datetime import datetime

# ============================================================
# 配置
# ============================================================
MAX_PRICE = 17.0
MIN_PRICE = 3.0
CAPITAL = 3622
STOP_LOSS_PCT = 2.0
TOP_N = 25
OUTPUT_DIR = r"C:\Users\34077\Desktop\11股票分析"

# ============================================================
# 1. 从东方财富拉取全A股行情 (按成交额排序取活跃股)
# ============================================================
def fetch_market_data():
    """从东方财富拉取全A股行情数据"""
    all_stocks = []

    # 分页获取，按成交额排序
    for page in range(1, 30):
        try:
            url = (
                "https://push2.eastmoney.com/api/qt/clist/get"
                f"?pn={page}&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281"
                "&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
                "&fields=f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18,f20,f21"
            )
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
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

                # 排除ST/退市
                if 'ST' in name or '退' in name:
                    continue
                # 排除新股(没有pre_close或涨幅异常)
                if pre_close <= 0:
                    continue

                all_stocks.append({
                    'code': code,
                    'name': name,
                    'price': price,
                    'change_pct': change_pct,
                    'volume': volume,
                    'turnover': turnover,
                    'high': high,
                    'low': low,
                    'open': open_p,
                    'pre_close': pre_close,
                    'market_cap': market_cap,
                })

            # 如果这一页已经有价格低于我们的下限的，可以提前终止
            prices_on_page = [item.get('f2', 0) or 0 for item in items]
            if prices_on_page and min(prices_on_page) > MAX_PRICE:
                # 按涨幅排的，如果最低价都超过上限了继续往后可能还是超上限
                pass

            time.sleep(0.3)

            if page % 5 == 0:
                print(f"   已拉取 {page} 页, 候选 {len(all_stocks)} 只...")

        except Exception as e:
            print(f"   第{page}页失败: {e}")
            break

    return all_stocks


# ============================================================
# 2. K线 + 技术分析 (腾讯)
# ============================================================
def fetch_kline(code, period='day', count=60):
    market = 'sz' if code.startswith(('0', '3')) else 'sh'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},{period},,,{count},qfq"
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://gu.qq.com/',
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get('code') == 0:
            stock_key = f"{market}{code}"
            return data['data'][stock_key].get(f'qfq{period}', [])
    except:
        pass
    return None


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
        if len(arr) < period:
            return arr[-1]
        return sum(arr[-period:]) / period

    ma5 = ma(closes, 5)
    ma10 = ma(closes, 10)
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60) if n >= 60 else ma(closes, 30)

    vol5_avg = sum(volumes[-5:]) / 5
    vol20_avg = sum(volumes[-20:]) / 20
    vol_ratio = vol5_avg / vol20_avg if vol20_avg > 0 else 1

    ret_3d = (closes[-1] / closes[-3] - 1) * 100 if n >= 3 else 0
    ret_5d = (closes[-1] / closes[-5] - 1) * 100 if n >= 5 else 0
    ret_10d = (closes[-1] / closes[-10] - 1) * 100 if n >= 10 else 0

    resistance_20 = max(highs[-20:])
    support_20 = min(lows[-20:])

    if n >= 60:
        h60 = max(highs[-60:])
        l60 = min(lows[-60:])
        pos_60 = (latest - l60) / (h60 - l60) * 100 if h60 != l60 else 50
    else:
        h60 = max(highs)
        l60 = min(lows)
        pos_60 = (latest - l60) / (h60 - l60) * 100 if h60 != l60 else 50

    def ema(arr, period):
        if len(arr) < period:
            return arr[-1]
        k = 2 / (period + 1)
        result = sum(arr[:period]) / period
        for v in arr[period:]:
            result = v * k + result * (1 - k)
        return result

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = ema12 - ema26

    # DEA
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

    # 布林位置
    bb_mid = ma(closes, 20)
    bb_std = (sum((c - bb_mid)**2 for c in closes[-20:]) / 20) ** 0.5
    bb_pos = (latest - (bb_mid - 2*bb_std)) / (4*bb_std) if bb_std > 0 else 0.5

    # ATR
    trs = []
    for i in range(max(1, n-14), n):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.01

    pct_from_resistance = (latest - resistance_20) / resistance_20 * 100

    return {
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'vol_ratio': vol_ratio,
        'ret_3d': ret_3d, 'ret_5d': ret_5d, 'ret_10d': ret_10d,
        'pos_60': pos_60, 'bb_pos': bb_pos,
        'macd_signal': macd_signal, 'dif': dif, 'dea': dea,
        'rsi': rsi, 'atr': atr,
        'resistance_20': resistance_20, 'support_20': support_20,
        'pct_from_resistance': pct_from_resistance,
    }


def score_stock(stock, ind):
    if ind is None:
        return 0, []

    score = 0
    reasons = []
    price = stock['price']
    change = stock['change_pct']

    # --- 趋势 (25分) ---
    if ind['ret_5d'] > 0 and ind['ret_10d'] > 0:
        score += 12
        reasons.append("短期上升趋势")
    elif ind['ret_5d'] > 0:
        score += 7
        reasons.append("近5日上涨")

    if price > ind['ma5']:
        score += 8
        reasons.append("站上MA5")
    if ind['ma5'] > ind['ma10']:
        score += 5
        reasons.append("MA5>MA10")

    # --- 量能 (20分) ---
    if 1.5 <= ind['vol_ratio'] <= 3.0:
        score += 15
        reasons.append(f"温和放量({ind['vol_ratio']:.1f}x)")
    elif 1.2 <= ind['vol_ratio'] < 1.5:
        score += 10
        reasons.append(f"量能正常({ind['vol_ratio']:.1f}x)")
    elif ind['vol_ratio'] > 3.0:
        score += 5
        reasons.append(f"异常放量({ind['vol_ratio']:.1f}x)")

    if ind['ret_3d'] > 0:
        score += 5
        reasons.append("近3日正动量")

    # --- 技术 (25分) ---
    if ind['macd_signal'] == '金叉↑':
        score += 15
        reasons.append("MACD金叉")
    elif ind['macd_signal'] == '多头':
        score += 10
        reasons.append("MACD多头")
    elif ind['macd_signal'] == '空头':
        if ind['dif'] > ind.get('prev_dif', ind['dif']) if 'prev_dif' in ind else False:
            score += 3
        if ind['dif'] > -0.1:
            score += 3
            reasons.append("MACD趋平可能反转")

    if 40 <= ind['rsi'] <= 70:
        score += 10
        reasons.append(f"RSI健康({ind['rsi']:.0f})")
    elif 30 <= ind['rsi'] < 40:
        score += 5
        reasons.append(f"RSI偏低({ind['rsi']:.0f})")

    # --- 位置 (20分) ---
    if 20 <= ind['pos_60'] <= 65:
        score += 12
        reasons.append(f"价格中枢({ind['pos_60']:.0f}%)")
    elif ind['pos_60'] < 20:
        score += 8
        reasons.append(f"低位({ind['pos_60']:.0f}%)")
    else:
        score += 3
        reasons.append(f"高位区({ind['pos_60']:.0f}%)")

    if ind['pct_from_resistance'] > -2:
        score += 5
        reasons.append("逼近突破")
    if ind['pct_from_resistance'] > 0:
        score += 3
        reasons.append("已突破20日高")

    # --- 资金适配 (10分) ---
    cost_100 = price * 100
    if cost_100 <= CAPITAL * 0.95:
        score += 8
        n_lots = int(CAPITAL // cost_100)
        reasons.append(f"可买{n_lots}手")
    elif cost_100 <= CAPITAL * 1.3:
        score += 4
        reasons.append("勉强1手")
    else:
        score -= 5

    # 当日涨幅加分(温和上涨)
    if 2 <= change <= 6:
        score += 5
        reasons.append(f"温和上涨{change:+.1f}%")
    elif 0 < change < 2:
        score += 3
    elif change > 8:
        score -= 5
        reasons.append("⚠追高风险")

    if ind['ret_5d'] > 15:
        score -= 8
        reasons.append("⚠5日涨幅过大")
    if ind['ret_5d'] > 20:
        score -= 10

    if change > 9.5:
        score -= 20
        reasons.append("⚠已涨停")

    # 市值加分(小盘股弹性大)
    mkt_cap = stock.get('market_cap', 0) or 0
    if 10 < mkt_cap < 100:
        score += 5
        reasons.append(f"小市值({mkt_cap:.0f}亿)")

    return max(0, min(100, score)), reasons


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 70)
    print(f"  A股全市场扫描器 v2 - 短线追涨模式")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  条件: {MIN_PRICE}-{MAX_PRICE}元 | 资金{CAPITAL}元 | 止损{STOP_LOSS_PCT}%")
    print("=" * 70)

    # Step 1: 拉取行情
    print("\n[1/3] 拉取全A股实时行情 (东方财富)...")
    stocks = fetch_market_data()
    print(f"  -> 筛选出 {len(stocks)} 只候选股 ({MIN_PRICE}-{MAX_PRICE}元)")

    if not stocks:
        print("  ⚠ 无候选股! 检查API或价格范围")
        return []

    # Step 2: 智能初筛 - 涨幅>0 + 放量的优先
    # 按：涨幅30% + 成交额40% + 当日涨幅30%排序的复合排名
    active = [s for s in stocks if s['change_pct'] > -3]
    active.sort(key=lambda x: (
        max(0, x['change_pct']) * 0.3 +
        (x['turnover'] / 1e8) * 0.3 +
        (1 if x['change_pct'] > 2 else 0) * 0.4
    ), reverse=True)
    candidates = active[:80]  # 取前80做详细分析

    print(f"\n[2/3] 对前{len(candidates)}只活跃股进行技术分析...")
    detailed = []
    for i, s in enumerate(candidates):
        if (i + 1) % 15 == 0:
            print(f"   进度: {i+1}/{len(candidates)}")
        kline = fetch_kline(s['code'])
        ind = calc_indicators(kline)
        if ind and ind['vol_ratio'] >= 0.8:  # 量比不过低
            sc, reasons = score_stock(s, ind)
            detailed.append({**s, 'indicators': ind, 'score': sc, 'reasons': reasons})
        time.sleep(0.2)

    detailed.sort(key=lambda x: x['score'], reverse=True)
    top = detailed[:TOP_N]

    print(f"\n[3/3] 分析完成! 共分析{len(detailed)}只, 输出前{TOP_N}只\n")

    # --- 输出 ---
    print("=" * 70)
    print("  🎯 短线追涨 TOP CANDIDATES")
    print("=" * 70)

    for rank, s in enumerate(top, 1):
        ind = s['indicators']
        price = s['price']
        shares = max(1, int(CAPITAL // (price * 100)))

        stop_loss_price = price * (1 - STOP_LOSS_PCT / 100)
        max_loss = (price - stop_loss_price) * shares * 100
        target_pct_1 = min(3, abs(ind['pct_from_resistance']) + 1 if ind['pct_from_resistance'] < 0 else 3)
        target_1 = price * (1 + target_pct_1 / 100)
        target_2 = ind['resistance_20'] if ind['resistance_20'] > price else price * 1.05

        tag = "🟢买入" if s['score'] >= 70 else "🔵关注" if s['score'] >= 55 else "⚪观望" if s['score'] >= 40 else "🔴跳过"

        print(f"\n{'─' * 70}")
        print(f"  #{rank} {tag} | {s['name']}({s['code']}) | 评分:{s['score']}/100")
        print(f"     现价:{price:.2f} | 涨幅:{s['change_pct']:+.2f}% | 成交额:{s['turnover']/1e8:.1f}亿")
        print(f"     O:{s['open']:.2f} H:{s['high']:.2f} L:{s['low']:.2f}")
        print(f"     量比:{ind['vol_ratio']:.2f}x | 5日:{ind['ret_5d']:+.1f}% | MACD:{ind['macd_signal']} | RSI:{ind['rsi']:.0f}")
        print(f"     60日位置:{ind['pos_60']:.0f}% | 阻力:{ind['resistance_20']:.2f} | 支撑:{ind['support_20']:.2f}")
        print(f"     ── 交易计划 ──")
        print(f"     买入: {shares}手 = {shares*price*100:.0f}元")
        print(f"     止损: {stop_loss_price:.2f} (亏损{max_loss:.0f}元)")
        print(f"     目标: {target_1:.2f}~{target_2:.2f}")
        rr = (target_1 - price) / (price - stop_loss_price) if price > stop_loss_price else 0
        print(f"     盈亏比: {rr:.1f}")
        if s['reasons']:
            print(f"     信号: {' | '.join(s['reasons'][:6])}")

    # --- 保存 ---
    output_file = os.path.join(OUTPUT_DIR, f"scan_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        serializable = []
        for s in top:
            sd = {k: v for k, v in s.items() if k != 'indicators'}
            sd['indicators'] = {k: (float(v) if isinstance(v, (float, int)) else v) for k, v in s['indicators'].items()}
            serializable.append(sd)
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"\n💾 保存: {output_file}")

    # --- 自选股快照 ---
    print(f"\n{'=' * 70}")
    print("  ⭐ 自选股快照")
    print(f"{'=' * 70}")
    watchlist = {
        '601991': '大唐发电', '601669': '中国电建', '600480': '凌云股份',
        '600973': '宝胜股份', '002229': '鸿博股份'
    }
    for code, name in watchlist.items():
        kline = fetch_kline(code)
        if kline:
            closes = [float(x[2]) for x in kline]
            latest = closes[-1]
            ind = calc_indicators(kline)
            if ind:
                change_today = (latest / float(kline[-1][1]) - 1) * 100
                print(f"  {name}({code}) | {latest:.2f} ({change_today:+.1f}%) | "
                      f"Vr:{ind['vol_ratio']:.1f}x | {ind['macd_signal']} | RSI:{ind['rsi']:.0f} | "
                      f"Pos60:{ind['pos_60']:.0f}%")
        time.sleep(0.3)

    print(f"\nDone. {datetime.now().strftime('%H:%M:%S')}")
    return top


if __name__ == '__main__':
    main()
