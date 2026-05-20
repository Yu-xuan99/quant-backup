#!/usr/bin/env python3
"""
为爆发前夜TOP3候选画趋势线图
调用 trend_chart.py 的 draw_pro_chart, 不重复造轮子
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 直接复用 trend_chart.py 的所有算法，只替换 STOCKS 数据
import importlib.util
spec = importlib.util.spec_from_file_location("trend_chart",
    os.path.join(os.path.dirname(__file__), "trend_chart.py"))
tc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tc)

from datetime import datetime

# 覆盖 STOCKS，加入TOP3候选
tc.STOCKS = {
    '000928': {
        'name': '中钢国际',
        'cost': 6.56,
        'capital': 3800,
        'events': {
            datetime.now().strftime('%Y-%m-%d'): '🎯3/4滨化模式\n洗盘-12%缩量0.5x\nDIF拐头均线收敛2.5%',
            '2026-05-19': '止跌企稳\n缩量极致',
            '2026-05-16': '洗盘低点',
        }
    },
    '000917': {
        'name': '电广传媒',
        'cost': 8.32,
        'capital': 3800,
        'events': {
            datetime.now().strftime('%Y-%m-%d'): '🎯3/4滨化模式\n洗盘-34%止跌企稳\n偏缩量0.6x',
            '2026-05-19': '地量止跌',
        }
    },
    '000852': {
        'name': '石化机械',
        'cost': 6.91,
        'capital': 3800,
        'events': {
            datetime.now().strftime('%Y-%m-%d'): '🏆评分78/100\n深度洗盘-28%缩量0.5x\n均线粘合1.8%',
            '2026-05-19': '缩量横盘',
            '2026-05-16': '洗盘筑底',
        }
    },
}

if __name__ == '__main__':
    tc.main()
