#!/usr/bin/env python3
"""
持仓实时监控 - 宝胜股份(600973)
成本: 7.94, 300股, 止损2% = 7.78
"""
import requests
import time
import json
import os
from datetime import datetime

CODE = "600973"
NAME = "宝胜股份"
COST = 7.94
SHARES = 300
STOP_LOSS_PCT = 2.0
STOP_LOSS_PRICE = round(COST * (1 - STOP_LOSS_PCT / 100), 2)
CAPITAL_USED = COST * SHARES

OUTPUT_DIR = r"C:\Users\34077\Desktop\11股票分析\宝胜股份_600973"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def fetch_realtime():
    """拉取实时行情(腾讯)"""
    market = 'sh'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{CODE},day,,,3,qfq"
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if data.get('code') == 0:
            kline = data['data'][f'{market}{CODE}']['qfqday']
            latest = kline[-1]
            return {
                'date': latest[0],
                'open': float(latest[1]),
                'close': float(latest[2]),
                'high': float(latest[3]),
                'low': float(latest[4]),
                'volume': float(latest[5]) * 100,
            }
    except Exception as e:
        print(f"拉取失败: {e}")
    return None

def main():
    print(f"  📊 {NAME}({CODE}) 实时持仓监控")
    print(f"  成本: {COST} | 持仓: {SHARES}股 | 资金: {CAPITAL_USED}元")
    print(f"  止损线: {STOP_LOSS_PRICE} (-{STOP_LOSS_PCT}%)")
    print(f"  {'='*50}")

    while True:
        now = datetime.now()
        # A股交易时间: 9:30-11:30, 13:00-15:00
        t = now.hour * 100 + now.minute
        is_trading = (930 <= t <= 1130) or (1300 <= t <= 1500)

        data = fetch_realtime()
        if data:
            price = data['close']
            pnl_pct = (price / COST - 1) * 100
            pnl_amt = (price - COST) * SHARES
            dist_to_stop = (price / STOP_LOSS_PRICE - 1) * 100

            status = ""
            if pnl_pct <= -STOP_LOSS_PCT:
                status = "🔴 触发止损!"
            elif pnl_pct >= 3:
                status = "🟢 盈利中"
            elif pnl_pct > 0:
                status = "🟡 微盈"
            elif pnl_pct >= -1:
                status = "⚪ 微亏"
            else:
                status = "🟠 接近止损"

            ts = now.strftime('%H:%M:%S')
            bar = "█" * min(20, int(abs(pnl_pct) * 4))
            direction = "+" if pnl_pct >= 0 else ""
            print(f"  [{ts}] {'🔴交易中' if is_trading else '⚫休市'} {price:.2f} | "
                  f"盈亏:{direction}{pnl_pct:+.2f}% ({pnl_amt:+.0f}元) | "
                  f"距止损:{dist_to_stop:+.1f}% | {status}")

            # 止损警告
            if price <= STOP_LOSS_PRICE * 1.005:
                print(f"  ⚠⚠⚠ 接近止损线! 当前{price:.2f} 止损{STOP_LOSS_PRICE}")

        if not is_trading:
            print(f"  [{now.strftime('%H:%M:%S')}] 休市中...")
            break

        time.sleep(5)

if __name__ == '__main__':
    main()
