# 2026-05-13 完整会话记录

## 账户状态
- 总资金: 3,622元
- 持仓: 大唐发电(601991) 100股 成本7.26 + 滨化股份(601678) 100股 成本5.07
- 未实现盈亏: +11元 (大唐+11, 滨化±0)
- 现金: 2,389元

## 今日已完成

### 文件恢复
- 从D盘迁回11股票分析全部文件到Desktop
- 修复4个Python脚本的硬编码路径(D: → C:)

### 环境搭建
- Python venv: C:\Users\34077\Desktop\11股票分析\.venv
- 依赖安装(pip): requests (清华镜像源)
- 克隆syf_quant-trading到Desktop学习策略

### 策略研究
- syf_quant-trading: 双均线交叉策略(MA5/20金叉买入,死叉卖出)
- syf_quant-trading: RSI均值回归策略(超卖30买入,超买70卖出)
- 回测引擎: 事件驱动, 万3手续费, Sharpe/MaxDD计算
- Strat-LLM论文: Free/Guided/Strict三种LLM交易Agent模式

### 板块资金分析
- 数据源: 东方财富 data.eastmoney.com
- 电子板块超越电力成为#1主力净流入
- 综合电力设备商(BK1323) +6.88% 换手16.21% 领涨子板块

### 全市场扫描 (18:09执行)
- 拉取3000只A股, 筛选75只候选(3-17元)
- 70只通过技术分析, 输出TOP25

### GitHub备份
- 仓库: https://github.com/Yu-xuan99/quant-backup
- 22个文件: README, 扫描结果, 策略代码, 分析脚本, 图表
- 2次commit: 初始备份 + 514交易计划

## 明日交易计划 (2026-05-14)

执行顺序:
1. 9:25 集合竞价 → SELL 滨化股份(601678) 100股 市价
2. 9:30 开盘 → BUY 上海电气(601727) 3手 @9.14 (2,742元)
3. 全天 → HOLD 大唐发电(601991) 止损7.20

首选: 上海电气(601727)
- 评分76 | ¥9.14 | RSI 69 | 盈亏比1.5
- 综合电力设备商板块领涨(+6.88%), 量比2.37x
- 与板块资金轮动信号共振

备选: 科信技术(300565)
- 评分80 | ¥14.00 | RSI 51 | MACD金叉 | 盈亏比1.5
- 纯技术面高分, 非领涨板块

风险参数:
- 最大单日亏损上限: 72元 (总资金2%)
- 大唐止损7.20: 亏损17元
- 上海电气止损8.96: 亏损55元
- 止损位不可移动, 触发即执行

## 数据源
- 腾讯财经K线: web.ifzq.gtimg.cn
- 东方财富实时行情: push2.eastmoney.com
- 东方财富板块资金: data.eastmoney.com

## 关键文件路径
- 扫描器: C:\Users\34077\Desktop\11股票分析\market_scanner.py
- 持仓监控: C:\Users\34077\Desktop\11股票分析\position_monitor.py
- 宝胜分析: C:\Users\34077\Desktop\11股票分析\宝胜股份_600973\analyze.py
- 每日快照: C:\Users\34077\Desktop\quant-backup\data\snapshots\
- 策略代码: C:\Users\34077\Desktop\quant-backup\strategies\
- Python venv: C:\Users\34077\Desktop\11股票分析\.venv\
- 项目记忆: C:\Users\34077\.claude\projects\C--Users-34077-Desktop\memory\project_trading_account.md

## 策略框架
1. 动量追涨: 涨幅2-6% + 量比1.5-3x + 站上MA5
2. 严格止损: 2%硬止损, 盈利>5%移动止盈到成本+1%
3. 板块轮动: 东方财富主力资金净流入排名驱动选股方向
4. 双均线交叉: MA5/MA20金叉确认趋势
5. RSI均值回归: 超卖30/超买70边界交易
