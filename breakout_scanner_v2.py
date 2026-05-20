#!/usr/bin/env python3
"""
爆发前夜扫描器 v2 - 使用Sina API获取股票列表 + 腾讯K线分析
复刻滨化股份 601678 5/12-13 爆发前模式
"""
import requests, json, time, numpy as np
from datetime import datetime

CAPITAL = 3800
MIN_PRICE, MAX_PRICE = 3, 20

def fetch_stock_list():
    """Sina API - 全A股列表"""
    url = 'http://money.finance.sina.com.cn/d/api/openapi_proxy.php/?__s=[[%22hq%22,%22hs_a%22,%22%22,0,50,5500]]'
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        data = r.json()
        items = data[0].get('items', [])
        stocks = []
        for item in items:
            code = item[0][2:]  # sh600973 -> 600973
            name = item[2]
            price = float(item[3])
            change_pct = float(item[5])
            volume = int(item[12])
            if MIN_PRICE <= price <= MAX_PRICE and 'ST' not in name and '*' not in name:
                stocks.append({'code': code, 'name': name, 'price': price,
                              'change_pct': change_pct, 'volume': volume})
        return stocks
    except Exception as e:
        print(f"  Sina API error: {e}")
        return []


def fetch_kline(code, count=120):
    """腾讯K线"""
    market = 'sz' if code.startswith(('0', '3')) else 'sh'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,{count},qfq"
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}, timeout=10)
        data = r.json()
        if data.get('code') == 0:
            return data['data'][f'{market}{code}'].get('qfqday', [])
    except:
        pass
    return None


def analyze_breakout(code, name, price, change_pct, klines):
    """
    复刻滨化股份爆发前模式评分
    滨化5/12特征: 距60高-30%+ / 缩量至60日均量50% / 止跌企稳 / 均线粘合1.5% / 价格4.96
    """
    if not klines or len(klines) < 60:
        return 0, [], []

    c = np.array([float(k[2]) for k in klines])
    h = np.array([float(k[3]) for k in klines])
    l = np.array([float(k[4]) for k in klines])
    v = np.array([float(k[5]) * 100 for k in klines])
    n = len(c)
    latest = c[-1]

    score, signals, risks = 0, [], []

    # ---- 1. 深度洗盘 (30分) ----
    h60 = np.max(h[-60:])
    dd60 = (latest - h60) / h60 * 100
    if dd60 < -25:    score += 30; signals.append(f"深度洗盘{dd60:.0f}%")
    elif dd60 < -18:  score += 25; signals.append(f"中度洗盘{dd60:.0f}%")
    elif dd60 < -12:  score += 18; signals.append(f"轻度洗盘{dd60:.0f}%")
    elif dd60 < -8:   score += 10
    else:             score += 2;  risks.append(f"未洗盘{dd60:.0f}%")

    # ---- 2. 缩量止跌 (25分) ----
    v5_avg = np.mean(v[-5:])
    v60_avg = np.mean(v[-60:])
    vr = v5_avg / max(v60_avg, 1)
    if vr < 0.40:     score += 25; signals.append(f"极缩量{vr:.1f}x")
    elif vr < 0.55:   score += 20; signals.append(f"缩量{vr:.1f}x")
    elif vr < 0.70:   score += 12; signals.append(f"偏缩量{vr:.1f}x")
    elif vr < 0.90:   score += 5
    else:             risks.append(f"未缩量{vr:.1f}x")

    # ---- 3. 止跌企稳 (20分) ----
    l3_min = min(l[-3:])
    l10_min = min(l[-10:-3]) if n >= 10 else l3_min
    r3 = (c[-1] / c[-3] - 1) * 100 if n >= 3 else 0

    if l3_min >= l10_min * 0.99 and r3 > 1:
        score += 20; signals.append(f"企稳回升{r3:+.1f}%")
    elif l3_min >= l10_min * 0.99:
        score += 14; signals.append("止跌企稳")
    elif l3_min > l10_min * 0.97:
        score += 8; signals.append("横盘筑底")
    else:
        risks.append("仍创新低")

    # ---- 4. 均线粘合 (15分) ----
    ma5 = np.mean(c[-5:])
    ma10 = np.mean(c[-10:])
    ma20 = np.mean(c[-20:])
    ma_spread = (max(ma5, ma10, ma20) / min(ma5, ma10, ma20) - 1) * 100

    if ma_spread < 2:     score += 15; signals.append(f"均线粘合{ma_spread:.1f}%")
    elif ma_spread < 4:   score += 10; signals.append(f"均线收敛{ma_spread:.1f}%")
    elif ma_spread < 6:   score += 5
    else:                 risks.append(f"均线发散{ma_spread:.1f}%")

    # ---- 5. 今日动向 (10分) ----
    vr_today = v[-1] / max(np.mean(v[-6:-1]), 1) if n >= 6 else 1
    if 1.2 <= vr_today <= 2.5 and 1 <= change_pct <= 4:
        score += 10; signals.append(f"放量试探{vr_today:.1f}x")
    elif vr_today > 1.0 and change_pct > 0:
        score += 5
    elif change_pct < -3:
        score -= 5; risks.append("今日大跌")

    # ---- 6. MACD拐头加分 ----
    def ema(arr, p):
        k = 2 / (p + 1)
        result = np.zeros(len(arr))
        result[:p] = np.mean(arr[:p])
        for i in range(p, len(arr)):
            result[i] = arr[i] * k + result[i-1] * (1 - k)
        return result

    dif = ema(c, 12) - ema(c, 26)
    if len(dif) >= 5:
        if dif[-1] > dif[-2] and dif[-2] <= dif[-3]:
            score += 5; signals.append("DIF拐头")

    # ---- 7. 低价加分 (适配资金) ----
    lots = int(CAPITAL // (price * 100))
    if lots >= 3:  score += 5; signals.append(f"可买{lots}手")
    elif lots >= 2: score += 3

    return max(0, min(100, score)), signals, risks


def main():
    print("=" * 60)
    print(f"  爆发前夜扫描 v2   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  模式: 滨化股份 5/12 → 5/13-15 涨停(+37%)")
    print("=" * 60)

    print("\n[1/3] Sina API 获取全A股列表...")
    stocks = fetch_stock_list()
    print(f"  {len(stocks)}只 (3-20元, 非ST)")

    if not stocks:
        print("  失败!")
        return

    print(f"\n[2/3] K线扫描 ({len(stocks)}只)...")
    candidates = []

    for i, s in enumerate(stocks):
        if i % 200 == 0:
            print(f"  进度: {i}/{len(stocks)} (已找到{len(candidates)}候选)")

        klines = fetch_kline(s['code'], 120)
        if not klines:
            continue

        sc, sigs, ris = analyze_breakout(
            s['code'], s['name'], s['price'], s['change_pct'], klines
        )

        if sc >= 55:
            # 计算更多细节
            cl = [float(k[2]) for k in klines]
            hi = [float(k[3]) for k in klines]
            lo = [float(k[4]) for k in klines]
            vo = [float(k[5])*100 for k in klines]

            candidates.append({
                **s,
                'score': sc, 'signals': sigs, 'risks': ris,
                'dd60': (s['price'] / max(hi[-60:]) - 1) * 100,
                'vr_5vs60': np.mean(vo[-5:]) / max(np.mean(vo[-60:]), 1),
                'ma5': np.mean(cl[-5:]),
                'ma20': np.mean(cl[-20:]),
                'l20': min(lo[-20:]),
                'r5': (cl[-1] / cl[-5] - 1) * 100 if len(cl) >= 5 else 0,
            })

        time.sleep(0.06)

    print(f"\n  完成! {len(stocks)}只 → {len(candidates)}只入围 (≥55分)")

    candidates.sort(key=lambda x: x['score'], reverse=True)
    top = candidates[:30]

    print(f"\n{'=' * 60}")
    print(f"  🎯 爆发前夜候选 TOP {min(30, len(top))}")
    print(f"{'=' * 60}")
    print(f"  {'#':<3} {'股票':<10} {'现价':>6} {'涨幅':>7} {'评分':>4} {'量比':>5} {'距60高':>7} {'可买':>4}")
    print(f"  {'-' * 57}")

    for i, c in enumerate(top, 1):
        lots = int(CAPITAL // (c['price'] * 100))
        tag = "🔥" if c['score'] >= 75 else "🟢" if c['score'] >= 65 else "🔵"
        print(f"  {tag}{i:<2} {c['name']:<10} {c['price']:>5.2f} {c['change_pct']:>+6.2f}% "
              f"{c['score']:>4} {c['vr_5vs60']:>4.1f}x {c['dd60']:>+6.1f}% {lots:>4}手")
        if c['signals']:
            print(f"       ✅ {' | '.join(c['signals'][:5])}")
        if c['risks']:
            print(f"       ⚠ {' | '.join(c['risks'][:3])}")

    # TOP10 详细
    if top:
        print(f"\n{'=' * 60}")
        print(f"  📊 TOP10 详细 + 滨化模式匹配度")
        print(f"{'=' * 60}")

        for i, c in enumerate(top[:10], 1):
            print(f"\n  #{i} {c['name']}({c['code']})  [{c['price']:.2f}元] 评分{c['score']}/100")
            print(f"    MA5:{c['ma5']:.2f} MA20:{c['ma20']:.2f} | 20低:{c['l20']:.2f}")
            print(f"    5日涨:{c['r5']:+.1f}% | 距60高:{c['dd60']:.1f}% | 量比vs60:{c['vr_5vs60']:.2f}x")
            print(f"    ✅ {', '.join(c['signals'])}")
            if c['risks']:
                print(f"    ⚠ {', '.join(c['risks'])}")

            # 滨化模式对比
            bin_match = 0
            if c['dd60'] < -15: bin_match += 1
            if c['vr_5vs60'] < 0.6: bin_match += 1
            if c['r5'] > -1: bin_match += 1
            if c['change_pct'] > 0 and c['change_pct'] < 5: bin_match += 1

            if bin_match >= 3:
                print(f"    🎯 高度匹配滨化5/12模式! ({bin_match}/4项吻合)")
                print(f"       滨化: 距60高-30%+缩量0.5x+止跌+温和放量 → 次日启动涨停")
            elif bin_match >= 2:
                print(f"    🔵 部分匹配滨化模式 ({bin_match}/4项吻合)")

    # 保存
    out = f"C:\\Users\\34077\\Desktop\\11股票分析\\breakout_v2_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(top, f, ensure_ascii=False, indent=2)
    print(f"\n  结果: {out}")


if __name__ == '__main__':
    main()
