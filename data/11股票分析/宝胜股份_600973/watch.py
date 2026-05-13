#!/usr/bin/env python3
"""宝胜股份实时盯盘 - 每3秒刷新"""
import requests, time, json, os, sys
from datetime import datetime

COST = 7.94
SHARES = 300
STOP_PRICE = 7.78
TARGETS = [8.06, 8.30, 8.60]
LOG_FILE = r"C:\Users\34077\Desktop\11股票分析\宝胜股份_600973\monitor_log.txt"

last_price = None

print(f"🟢 盯盘启动 | 成本{COST} | 止损{STOP_PRICE} | {SHARES}股", flush=True)

while True:
    now = datetime.now()
    t = now.hour * 100 + now.minute
    is_trading = (930 <= t <= 1130) or (1300 <= t <= 1500)

    try:
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600973,day,,,2,qfq"
        r = requests.get(url, headers={'User-Agent':'Mozilla/5.0'}, timeout=8)
        data = r.json()
        kline = data['data']['sh600973']['qfqday']
        latest = kline[-1]
        price = float(latest[2])
        high = float(latest[3])
        low = float(latest[4])

        if price != last_price:
            pnl_pct = (price/COST - 1)*100
            pnl_amt = (price - COST)*SHARES
            dist_stop = (price/STOP_PRICE - 1)*100
            ts = now.strftime('%H:%M:%S')

            tag = ""
            alert = ""
            if pnl_pct <= -2:
                tag, alert = "🔴🔴🔴", "!!!止损触发!!!"
            elif pnl_pct >= 5:
                tag, alert = "🟢🟢🟢", "!!止盈考虑!!"
            elif price >= TARGETS[0]:
                tag, alert = "🟢", "突破第一阻力"
            elif pnl_pct < -1:
                tag, alert = "🟠", "接近止损"

            msg = f"[{ts}] {tag} {price:.2f} H:{high:.2f} L:{low:.2f} | PnL:{pnl_pct:+.2f}%({pnl_amt:+.0f}元) | 离止损:{dist_stop:+.1f}% {alert}"
            print(msg, flush=True)

            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')

            last_price = price

            # 报警
            if price <= STOP_PRICE * 1.005 or price >= TARGETS[0]:
                print(f"  ⚠ 关键价位触发: {price:.2f}", flush=True)

        if not is_trading:
            print(f"[{ts}] ⚫ 休市", flush=True)
            break

    except Exception as e:
        print(f"[{now.strftime('%H:%M:%S')}] ⚠ {str(e)[:40]}", flush=True)

    time.sleep(3)
