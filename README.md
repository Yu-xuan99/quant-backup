# QuantAgent Backup — 2026-05-13

A股量化交易系统数据备份。纯量化Agent模式，无情绪决策。

## 账户概要

| 项目 | 数值 |
|------|------|
| 总资金 | 3,622元 |
| 当前持仓 | 大唐发电(601991) 100股 + 滨化股份(601678) 100股 |
| 未实现盈亏 | +11元 |
| 策略模式 | 动量追涨 + 严格止损 + 板块资金轮动 |

## 文件结构

```
quant-backup/
├── README.md                          # 本文件
├── data/
│   ├── snapshots/                     # 每日状态快照
│   └── 11股票分析/                     # 原始分析脚本和数据
│       ├── market_scanner.py          # 全市场扫描器
│       ├── position_monitor.py        # 持仓实时监控
│       ├── 宝胜股份_600973/           # 宝胜股份分析
│       └── 鸿博股份_002229/           # 鸿博股份分析
├── strategies/                        # 学习参考策略
│   ├── syf_strategies/               # syf_quant-trading策略
│   └── backtest_engine/              # 回测引擎
└── analysis/                          # 走势图存档
```

## 数据源

- 腾讯财经K线 (web.ifzq.gtimg.cn)
- 东方财富API (push2.eastmoney.com)
- 东方财富板块资金流向 (data.eastmoney.com)

## 策略框架

1. **双均线交叉** (syf_quant-trading): 金叉买入/死叉卖出
2. **RSI均值回归**: 超卖30买入/超买70卖出
3. **Strat-LLM Strict Mode**: 严格风控锚
4. **板块轮动**: 主力资金净流入排名驱动选股

## 更新频率

每日盘后自动快照 + 盘前市场扫描。
