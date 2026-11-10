# LoL 电竞预测市场套利研究

JN 的研究项目：在订单簿预测市场（Polymarket、Kalshi、Predict.fun）上研究 League of Legends 电竞盘口的三类套利，目标是可回测、可重复、能放大的真实收益。

- **A 跨平台**：同一场比赛在不同平台的价差。
- **B 现场信息延迟**：JN 本人到 Worlds 2026 决赛现场（2026-11-14，Barclays Center）实测延迟。
- **C 同平台组合**：同一场 BO3/BO5 的多个盘口之间价格不一致。

研发顺序已定为 **C → A → B**。当前重点是 C 的扫描器 `scanner/lol_c_scan.py`，下一步是接真实历史数据回放。

## 硬约束（用户原话，必须遵守）

- “请不要直接开始编写交易机器人，也不要急于给出自动下单代码。”
  本仓库所有代码都是**只读**：不下单、不签名、不碰私钥或 API 密钥。没有用户明确要求，不写任何下单代码。
- “研究范围限定为 Polymarket 这类订单簿预测市场，不把传统博彩公司作为主要研究对象。”Stake 等平台可以作为赔率参考。
- “请严格区分已经验证的事实、供应商宣传、理论推演与个人判断。”文档和回复里用标签：
  - 【事实】原始文档、链上或数据商统计可核对
  - 【宣传】供应商或赞助内容
  - 【推演】由事实推出的结论
  - 【判断】主观判断
- “所有结论尽量使用真实案例、公开数据、API 文档或可靠研究支持。”能查的先查再答，不凭记忆给数字；查不到就直说。
- 用中文回复。

## 目录

| 路径 | 内容 |
| --- | --- |
| `scanner/lol_c_scan.py` | C 扫描器 v2：线性规划找跨盘口的无风险组合；实时扫描、回放录制、回放 CryptoStruct |
| `scanner/test_scan.py` | 扫描器测试（合成数据，不联网） |
| `scanner/c_monitor.py` | C 实时监控（决赛用）：WebSocket 增量维护订单簿、断线重连、REST 抽查与后备、单局结算后收窄情景、机会段日志 |
| `scanner/test_monitor.py` | 监控测试（本地模拟 Gamma / CLOB / WebSocket，不联网） |
| `recorder/pm_recorder.py` | 只读录制：Polymarket 盘口与比分推送、NBA 逐回合、时钟偏差 |
| `recorder/test_recorder.py` | 录制脚本测试（本地模拟服务器） |
| `taplog/index.html` | 现场打点页源码（线上版见下方链接） |
| `analysis/` | 第一阶段的小计算：手续费门槛（fees.py、c_fees.py）、BO5 恒等式枚举（bo5.py） |
| `docs/research_doc.md` | 研究文档快照（2026-11-10），结论、事实、来源都在里面 |
| `docs/conversation_log.md` | 这次对话的经过与各个决定 |
| `.claude/settings.json`、`scripts/install_pkgs.sh` | claude.ai/code 会话启动时自动装依赖 |

## 怎么跑

```bash
python3 -m pip install -r requirements.txt   # Python 3.9 以上，测试在 3.13 上通过
./run_tests.sh                                # 全部测试，不联网

# 扫描器
python3 scanner/lol_c_scan.py meta --event-slug lol-blg-gen-2026-11-14            # 导出盘口清单并打印识别结果
python3 scanner/lol_c_scan.py live --event-slug lol-blg-gen-2026-11-14 --show-map --once
python3 scanner/lol_c_scan.py replay rec_录制目录/                                  # 回放 pm_recorder 的录制
python3 scanner/lol_c_scan.py cs-inspect 文件.txt.zst --event-slug <赛事slug> --head 5
python3 scanner/lol_c_scan.py cs-replay 数据目录/ --event-slug <slug1> <slug2>      # 回放 CryptoStruct

# C 实时监控（只盯一场；决赛用法见“下一步”第 5 条）
python3 scanner/c_monitor.py --event-slug lol-blg-gen-2026-11-14 --check                     # 20 秒自检
caffeinate -i python3 scanner/c_monitor.py --event-slug lol-blg-gen-2026-11-14 --hours 8     # 正式监控
python3 scanner/lol_c_scan.py replay rec_c_lol-blg-gen-2026-11-14_<时间>/                     # 赛后复核监控录下的数据

# 录制
python3 recorder/pm_recorder.py --event-slug <slug> --check          # 15 秒自检
python3 recorder/pm_recorder.py --event-slug <slug> --hours 4        # 正式录制（Mac 上加 caffeinate -i）
```

## 扫描器 v2 的设计要点

- **结果空间**：BO5 正常打完的 20 种比分，加“整场取消、全部 50-50”，作为线性规划约束。
  “开赛后中途终止”（56 种）默认只报告最差盈亏；加 `--strict` 才作为约束。
- **结算值**：`Leg.value(scenario)` 给 token0 的回款，token1 = 1 − value。未打完的单局 50-50。
- **求解**：先只用各选项最优一档、不限数量判断“锁定 $1 的最低成本”是否小于 1；不小于 1 就没有套利，不解完整问题（更深的档只会更贵）。小于 1 再按真实深度解，得到总利润和每个选项的买入量。手续费 = 0.05 × p × (1 − p) × 股数，计入成本。
- **盘口识别**：题目正则与盘口 slug 后缀交叉核对，不一致就跳过。队名依次比完全相同、互相包含、简称字母顺序（BLG → Bilibili Gaming），有歧义就跳过，不猜。
- **订单簿**：某个选项没有自己的盘口数据时，用另一个选项的买单换算（买 token1 @ q ⇔ token0 买单 @ 1 − q）。
- **回放**：只在卖一价格变化、或当前仍有机会时重算。输出机会段 CSV：开始时间、持续秒数、最大利润、投入、中途终止最差盈亏、具体买入。
- **CryptoStruct**：按事件 ID 链检测断档，断档到下一次快照之间该盘口不参与计算；相邻两天文件重叠部分按事件 ID 去重；文件按 token id → condition id → 盘口 slug（可带选项后缀）对应到盘口。

## 已核实的关键事实（出处见 docs/research_doc.md）

- 【事实】Polymarket 吃单费 = 股数 × 费率 × p × (1 − p)，体育类费率 0.05，挂单 0。[fees](https://docs.polymarket.com/trading/fees)
- 【事实】体育类挂单方可分得吃单费的 15% 作为返佣；电竞盘算不算体育类，文档没写。[maker rebates](https://docs.polymarket.com/programs/maker-rebates)
- 【事实】买 Yes @0.60 与买 No @0.40 可直接撮合（铸造一套）。[prices-orderbook](https://docs.polymarket.com/concepts/prices-orderbook)
- 【事实】LoL 盘口结算（已结束赛事的规则原文）：
  - 单局：打完按结果；没打完 50-50。
  - 系列赛胜负：开赛后因弃权、取消资格、不战而胜结束，判给获胜方；整场没打、平局、延期超过 7 天仍无胜者，50-50。
  - 让局、总局数：开赛后中途因弃权等结束，50-50；比赛打完时弃权的局照常计入。结算来源 gol.gg。
  - Worlds 决赛页写的延期期限是 14 天。
- 【推演】所以 BO5 的等式类关系大多只在正常打完时成立；在整场取消和中途终止时仍成立的只有：同盘口两边相加 = 1、让 2.5 ≤ 让 1.5、O4.5 ≤ O3.5。
- 【事实】Worlds 决赛 BLG 对 Gen.G。镜像页列出：系列赛胜负、第 1–4 局胜负、总局数 3.5 / 4.5、Gen.G 让 1.5 / 2.5、每局道具；没有第 5 局胜负。slug 按镜像页网址是 `lol-blg-gen-2026-11-14`。[lines.com](https://www.lines.com/prediction-markets/sports/lol/lol-blg-gen-2026-11-14)
- 【事实】Polymarket WebSocket：
  - 盘口频道 `wss://ws-subscriptions-clob.polymarket.com/ws/market`，每 10 秒发 `PING`。
  - 比分频道 `wss://sports-api.polymarket.com/ws`，服务器每 5 秒发 `ping`，10 秒内回 `pong`。
  - 盘口消息带 13 位时间戳，按示例是毫秒，文档没写单位。
- 【事实】体育盘口开赛时撤掉全部挂单；按市场设有撮合延迟 `seconds_delay`。
- 【事实】CryptoStruct：
  - 每个盘口每个 UTC 日一个 zstd JSON lines 文件，第 1 行头部。
  - 事件 `[类型, 品种ID, 上一事件ID, 事件ID, 接收ns, 交易所ns, 数据]`：类型 0 快照、1 增量（数量为绝对值，"0" 撤档）、2 成交、5 状态。
  - 价格 0..1，Polymarket 最小变动 0.001。每个系列每天 €1。
  - 免费样本 `lol-tl2-los-2026-10-30-game2`。
- 【事实】Barclays 场馆禁止笔记本、平板，手机可个人录制，禁止未授权直播。
- 【事实】决赛盘口（11/10 Gamma/CLOB 实测）：系列赛胜负 `seconds_delay` = 1，`game_start_time` = 2026-11-14T19:00:00Z，最小变动 0.01，最小下单 5 股；赛果盘口 9 个。
- 【事实】已结束的 iG 对 Gen.G（0:3）在 Gamma 上：第 4 局胜负按 `["0.5","0.5"]` 结算，印证“没打的单局 50-50”；Gen.G 让 1.5/2.5（`-game-handicap-home-*`）结算为 `["1","0"]`。赛事对象另有 `score`（如 `000-000|0-3|Bo5`）和 `period`（`3/5`）字段。
- 【事实】market WebSocket 加 `custom_feature_enabled` 后会收到全平台的 `new_market` 广播（11/10 实测 5 分钟 190 条），与订阅无关；监控只保留本场的。
- 【事实】JN 说明：三个平台的交易主体合规已确认、都能直接用（11/09）；11/14 在纽约通过 Bagel（走 Polymarket API）交易（11/10）。

## 尚未核实的假设（改代码前先看）

1. ~~CryptoStruct 文件里的价格属于盘口的哪个选项，`native_code` 存的是什么。~~ **已核实（11/10，免费样本 `lol-tl2-los-2026-10-30-game2`）**：`native_code` 是字典 `{referenceOutcome: 选项名, 各选项名: token id, marketId, marketSlug}`，价格对应 `referenceOutcome`（样本里是第一个选项 Team Liquid；与 CLOB `prices-history` 走势一致，赛后升到约 1，与结算 `["1","0"]` 相符）；交叉占比 0.00%（32 万次检查），断点 0。扫描器现在按 `referenceOutcome` 的 token id 精确对应，不再假设第一个选项。
2. ~~Polymarket `price_change` 的 `size` 是该档新的总量而非增量，`side=SELL` 是卖单档。~~ **已核实（11/10，决赛盘口实测）**：每条 `price_change` 自带该选项的 `best_bid`/`best_ask`，按“size 为新总量、SELL 为卖单档”重建后，6 分钟 2,140 条全部一致；另 72 次 REST `/book` 抽查全部一致。文档仍没写定义，`c_monitor.py` 持续核对，对不上会报警并用 REST 修复。
3. 买入手续费从股数扣还是从资金扣，文档没写；按资金计入成本。
4. ~~Worlds 决赛的真实题目和选项写法。~~ **已核实（11/10，`meta` 导出 42 个盘口）**：题目、选项、slug 后缀与测试构造一致，9 个赛果盘口全部识别（系列赛胜负、第 1–4 局、总局数 3.5/4.5、Gen.G 让 1.5/2.5，让局 slug 为 `-game-handicap-home-*`、选项顺序 Gen.G 在前）；没有第 5 局胜负（第 5 局只有道具盘）；33 个道具盘跳过。
5. `live --discover` 用的 Gamma 标签 `league-of-legends` 没实测。
6. ~~已结束赛事能否用 `events?slug=` 直接取到。~~ **已核实（11/10）**：`lol-ig1-gen-2026-11-07` 直接取到；扫描器仍保留 `&closed=true` 的备用请求。
7. ~~BLG 对 T1 半决赛的 slug 未知。~~ **已核实（11/10，Gamma）**：`lol-blg-t1-2026-11-08`，开赛 2026-11-08T22:10Z，BLG 3:1；iG 对 Gen.G 是 `lol-ig1-gen-2026-11-07`，开赛 2026-11-07T22:05Z，0:3。两场都跨 UTC 午夜，回放需要 11/07–11/09 三天日包。
8. `price_change` 在某选项卖单被撤空时 `best_ask` 给什么值（0 还是 1）没见到实例；监控把两者都当“无卖单”。
9. 单局盘口在比赛中多快结算（Gamma `closed` + `outcomePrices`）未知：监控只在正式结算后收窄情景，结算慢则这期间按全部情景算（只会漏报，不会误报）。

## 运行环境

### claude.ai/code（网页版）

- 会话开始时，`.claude/settings.json` 的 SessionStart hook 运行 `scripts/install_pkgs.sh` 装依赖。它只在云端执行（`CLAUDE_CODE_REMOTE=true`），本地直接跳过。
- 环境设置入口：新会话页面，输入框下面一排的第一个按钮 → 环境右侧的设置图标。
  - Network access 选 **Custom**，Allowed domains 每行一个：
    ```
    gamma-api.polymarket.com
    clob.polymarket.com
    ws-subscriptions-clob.polymarket.com
    sports-api.polymarket.com
    cryptostruct.com
    *.cryptostruct.com
    cdn.nba.com
    ```
  - 勾选 **Also include default list of common package managers**，否则装不了依赖。
  - Setup script、Environment variables 都不用填。不放任何交易或钱包密钥：本仓库只读。
- 网页版可以直接做：
  - `meta` 导出盘口；
  - 下载 CryptoStruct 免费样本，跑 `cs-inspect`、`cs-replay`；
  - 改代码、跑测试。
- 不放在网页版做：长时间录制。
  - 前台命令最长 10 分钟，超时转后台最多再跑 30 分钟。
  - 闲置几分钟后 VM 会暂停。
  - 所以 `pm_recorder.py` 的正式录制在自己一直开着的机器上跑。
- 录制文件和数据不进 git（见 `.gitignore`）。要在网页版回放本机的录制，先把录制目录压缩，再用以下任一方式放进仓库：
  - 在 GitHub 网页上传到仓库里单独的目录；
  - 在本机 `git add -f` 后推送。
- 【待验证】以下两点都没实测：云端代理是否放行两个 WebSocket，Polymarket 是否限制云端 IP。新会话先跑 `meta` 和 `pm_recorder.py --check`（15 秒自检）确认。
- 【待验证】CryptoStruct 的下载地址如果跳到别的域名（比如对象存储），把那个域名也加进 Allowed domains。

### 其他

- claude.ai 聊天（不是 Code）里的工作区连不上 gamma-api.polymarket.com、clob.polymarket.com、cryptostruct.com（代理 403）。
- 录制需要一台一直开着的机器。不要带进场馆：Barclays 禁止笔记本。
- 打点页的数据库只在 claude.ai 的页面里可用：[线上打点页](https://claude.ai/artifact/GAcuu2okikTFXbesm3HJy9)。本地打开 `taplog/index.html` 只存在手机浏览器里，用“复制 CSV”导出。
- 研究文档的在线可编辑版：<https://claude.ai/artifact/6ksV3nRTDkRtwZoJ8D3VJK>（本地快照在 docs/，不会自动同步）。

## 下一步（按时间）

1. **11/10 晚**：76ers 对 Celtics 的 NBA 彩排（B）。录制脚本加打点页，场内只打点、不录像（Xfinity Mobile Arena 禁止录像录音设备）。11/11 对齐三方时间戳，出彩排报告。
2. ~~**11/13 前**：`meta --event-slug lol-blg-gen-2026-11-14`，核对决赛盘口识别。~~ 11/10 已完成，见上方假设 4。11/14 赛前再跑一次 `meta`，看有没有新上架的赛果盘口（监控也会每 60 秒自动检查）。
3. 下载 CryptoStruct 免费样本，`cs-inspect` 确认价格方向和交叉占比。网页版同样可以直接下载和运行。
4. 买 11/07–11/09 三天的日包（约 €3；两场半决赛都是美东 17:00 开打、跨 UTC 午夜），`cs-replay` 两场半决赛，出第一份真实的 C 统计。
5. **11/14**：决赛按研究文档第四节协议实测 B；同时用 `pm_recorder.py` 录决赛全部盘口，赛后用 `replay` 跑 C。可用 Bagel 下 1–2 笔最小额单，测“按下到成交”的耗时。
   - C 实时监控：美东 13:00 前在家里常开的 Mac 上先 `c_monitor.py ... --check`，看到“可以正式开跑”再 `caffeinate -i python3 scanner/c_monitor.py --event-slug lol-blg-gen-2026-11-14 --hours 8`。与 `pm_recorder.py` 可同时跑（各自一条连接）。系列赛胜负结算 5 分钟后自动停止。
   - 报出的机会只是候选：多腿不能同时成交、吃单延迟（`seconds_delay` = 1）都没建模；“若开赛后中途终止”一行为负时，那是靠等式锁定、有弃权风险的组合。单局正式结算后，已成定局却仍低于 1 的选项（如 BLG +2.5 @0.99）也会被报出，加 `--strict` 可只报中途终止也不亏的组合。
6. 用样本统计 BO5 关系的偏离：可成交价、含费、存续时间、可成交量；再决定是否买全量数据。
7. 之后：A 的事件匹配与录制；以挂单为主的 C（带对冲的做市）单独评估库存与腿风险。

## 工作约定

- 投入上限：`--max-cost 2000`（live / replay / cs-replay / c_monitor 都支持）按 JN 的单笔规模（几百到 2000u）求利润；不加则吃满可见深度。
- 改扫描器或录制脚本后跑 `./run_tests.sh`。测试只用本地模拟服务器和合成数据，不联网。
- 新的结算规则或接口字段，先找到原文出处再改代码，并在注释或文档里写明出处。
- 扫描器报出的机会默认只是候选：多个选项不能同时成交的风险、吃单延迟都还没建模。
- 写进文档的数字与结论保持四种标签。
