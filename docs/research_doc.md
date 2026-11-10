<!-- 研究文档快照：从 Claude Docs 导出（rev 28，2026-11-10）。在线可编辑版本：https://claude.ai/artifact/6ksV3nRTDkRtwZoJ8D3VJK 。两张图未导出。 -->

# LoL 电竞预测市场套利研究 · 第一阶段：市场结构、数据与竞争环境

Nov 9, 2026 · @JN

## 核心结论：研发顺序建议改为 C → A → B

按目前证据，应先做 C 的回测；A 先建事件匹配与录制基础设施，并先解决准入；B 只在 11 月 14 日做一次测量。三者共用一套数据与规则底座，调整的是投入顺序，不是放弃 A。

| 方向 | 原优先级 | 建议 | 决定性证据 | 预期容量（判断） |
| --- | --- | --- | --- | --- |
| C 同平台组合 | 第二 | 第一：先做离线回测 | Polymarket LoL 合约最全；BO5 内有可严格证明的等式；同一平台同一套结算规则 | 散户级：NBA 类比中 76.9% 的组合机会放不下 $100 |
| A 跨平台 | 第一 | 第二：先建匹配与录制，准入解决后再评估 | 你的 0.97 例子两腿吃单净利约为 0；延期与弃权规则不同；Kalshi 受限名单含中国 | 一线赛事价差小于费用，二三线深度薄 |
| B 现场延迟 | 第三 | 第三：只做 11/14 测量 | 做市方用 GRID 服务器数据；吃单有体育延迟窗口；在美国只能平仓 | 接近 0 |

- 【判断】在 2026 年的费率与做市结构下，纯吃单的无风险套利大多只剩散户级容量。能做大的版本几乎都以挂单为主，即向“带对冲的做市”靠拢，需要单独评估库存风险。
- 【判断】你初步表里 C 的技术难度 2/5 略偏低：未进行局 50-50、延期、弃权、重开都要编码进结果空间，否则扫描器会报假机会。
- 本周三件事：11/10 用 NBA 比赛彩排录制与打点；部署录制程序并在 11/14 实测；买 2026 赛季样本扫一遍 BO5 等式偏离。三家平台的交易主体合规已确认，可直接使用（JN，11/09）。

## 一、市场结构：有真实流动性的 LoL 订单簿主要是三家

截至 2026-11-08，同时具备 LoL 盘口、公开订单簿 API 和真实成交的独立订单簿只有 Polymarket 国际版、Kalshi、Predict.fun 三家；Polymarket US 另有一本只面向美国用户的订单簿。Polymarket 的 LoL 成交规模和盘口种类都明显领先。

标注约定：【事实】= 原始文档、链上或数据商统计可核对；【宣传】= 供应商或赞助内容；【推演】= 由事实推出的结论；【判断】= 我的主观判断。

| 平台 | 结构 | LoL 盘口 | 近 30 天 LoL 成交 | 加权价差 / 一档深度 | 手续费 | 对你的准入 |
| --- | --- | --- | --- | --- | --- | --- |
| [Polymarket 国际版](https://docs.polymarket.com/trading/fees?via=xp) | 离链撮合、Polygon 结算；CLOB V2 自 2026-04-28 上线 | 系列胜负、G1–G5 单局胜者、总局数、让局、单局道具 | $191.0M，78.4 万笔（全 LoL 系列） | 1.75¢ / $71.2K | taker 费 = 0.05×p×(1−p)；maker 0，并返还 15% taker 费 | 屏蔽表未列中国；美国仅可平仓 |
| [Kalshi](https://cryptostruct.com/prediction-markets/kalshi-kxlolgame) | CFTC 持牌交易所 | KXLOLGAME 胜负、KXLOLMAP 单图、KXLOLTOTALMAPS 总图数，另有让分与选手数据合约 | $38.9M，58.0 万笔（仅胜负系列） | 1.75¢ / $67.7K | taker 费 = 0.07×P×(1−P) 向上取整；多数系列 maker 0 | 第三方整理的受限名单含中国 |
| [Predict.fun](https://cryptostruct.com/prediction-markets/predictfun-lol) | BNB Chain，Polymarket 风格的订单簿 | 冠军、系列与单局胜负、总数、道具；总数类占 45% | $32.8M，36.8 万笔（全 LoL 系列） | 1.59¢ / $48.9K | 未查到公开费率 | 未核实 |
| [Polymarket US](https://www.rivermarkets.com/insights/polymarket-us-fees.html) | CFTC 持牌，独立账户与订单簿 | 胜负、让分、总数、道具、冠军 | 未找到独立统计 | — | 体育 taker 5% 系数，maker 0 | 面向美国用户，需 KYC |

成交、价差、深度来自 [CryptoStruct](https://cryptostruct.com/prediction-markets/polymarket-lol) 30 天统计（截至 2026-11-08），属数据商自报。三行口径不同：Kalshi 只含胜负系列，另两家含全部 LoL 合约。

- 【事实】成交几乎全部发生在比赛当天：结算日成交占比 Polymarket 97%、Kalshi 88%、Predict.fun 89%。可交易窗口集中在赛前数小时和滚球期间。
- 【事实】Polymarket 在截至 2026-07-30 的一年里上架 442 场 LoL 比赛，胜负盘平均约 $1.2M/场；2025 世界赛决赛 T1 vs KT 胜负盘 $28.2M。[Doc's Sports](https://www.docsports.com/2026/esports-matches-drawing-major-leauge-level-betting-action-polymarket.html)
- 【事实】Polymarket 的 LoL 全系列累计 92,300 个合约：总数类 40%、单局胜者 32%、道具 20%、让局 5%、系列胜负 4%。C 方向只能在 Polymarket 上做，另两家盘口太少。
- 【事实】Polymarket 有指定的电竞做市方：Sportstensor（Bittensor 子网）被多家媒体称为 Polymarket 官方做市商，自 2025-11-07 起由 GRID 供应官方赛事数据。[Esports Advocate](https://esportsadvocate.net/2025/11/grid-partners-with-sportstensor/)
- 【宣传】Polymarket 为 Worlds 2026 投放 $500,000 流动性奖励（来源为 Polymarket 赞助的 Sheep Esports 文章，原文未能打开，仅见搜索摘要）。Predict.fun 也在做 Worlds 活动（分档 USDT 宝箱，金额未披露），并已嵌入 Binance 主站与 Binance Wallet。[Odaily](https://www.odaily.news/en/post/5213395)
- 【事实】成交量口径不统一：Paradigm 指出多数第三方仪表盘把链上成交事件按买卖双方各算一次，体量被放大约一倍。跨平台比较只能用同一数据商、同一口径。[Paradigm](https://cn.paradigm.xyz/2025/12/polymarket-volume-is-being-double-counted)
- 【事实】ProphetX 也列出 LoL；Crypto.com 与 Robinhood 有电竞专区，Robinhood 的品种取决于其合作交易所，这些平台主要面向美国用户。[LSR](https://www.legalsportsreport.com/prediction-markets/esports/) Gate 的 Worlds 活动市场含单局与系列胜负、BO3/BO5 比分、让局与总局数，但只在 App 内交易，未见公开订单簿 API。[Gate 公告](https://www.gate.com/announcements/article/102232)
- 【判断】准入是 A 的第一道硬约束。若你的账户主体在中国大陆，Kalshi 这条腿大概率不成立，需要先确认主体与合规路径再投入研发（我不是律师）。[Kalshi 受限名单整理](https://www.coinperps.com/learn/kalshi-restricted-countries)

## 二、数据可得性：官方只给“现在”，历史订单簿只能买或自己录

三家平台的官方 API 都只提供当前订单簿，没有历史 L2。第三方实时录制的历史订单簿最早约从 2025 年 9–11 月（Polymarket）和 2026 年 2–3 月（Kalshi）开始，所以可回测样本基本等于 2026 赛季。

| 数据层 | Polymarket | Kalshi | Predict.fun |
| --- | --- | --- | --- |
| 当前订单簿 | CLOB REST + 市场 WebSocket | REST orderbook + WebSocket `orderbook_delta`（先快照后增量，需 API key 签名） | REST orderbook + WebSocket |
| 历史成交 | Data API trades；链上成交事件 | `/markets/trades`；超过归档线后用 `/historical/trades` | BSC 链上成交（据 Telonex，官方无链下成交流） |
| 历史价格 | `/v2/prices-history`（2026-09-04 起，游标分页） | 1 分钟 / 1 小时 / 1 天 K 线；归档市场用 `/historical` 端点 | timeseries 端点 |
| 历史订单簿 | 无 | 无 | 无 |
| 赛事状态 | Sports WebSocket，含电竞状态；官方提示可能延迟或有误 | 无 | 无 |

来源：[Polymarket 更新日志](https://docs.polymarket.com/changelog.md)、[Polymarket Sports WS](https://docs.polymarket.com/market-data/websocket/sports.md)、[Kalshi 历史数据](https://docs.kalshi.com/getting_started/historical_data)、[Kalshi WebSocket](https://docs.kalshi.com/getting_started/quick_start_websockets)、[Predict.fun SDK](https://docs.rs/predict-fun-sdk)。

| 数据商 | 覆盖 | 起始 | 形式与价格 |
| --- | --- | --- | --- |
| [CryptoStruct](https://cryptostruct.com/prediction-markets/polymarket-lol) | Polymarket LoL、Kalshi KXLOLGAME、Predict.fun LoL | 2025-09 / 2026-02 / 2026-10 | 按日打包 tick 成交 + L2，€1/天/系列 |
| [Telonex](https://telonex.io/datasets) | Polymarket、Predict.fun | Polymarket 自 2025-10-11；Predict.fun 订单簿自 2026-04-22 | tick 成交、BBO、5/25/全深度快照，日度 Parquet |
| [PredictionData.dev](https://predictiondata-dev.pages.dev/faq) | Polymarket；Kalshi 等需定制 | WebSocket 数据自 2025-11 | Polymarket 全量 $1,250/月 |
| [PMXT Archive](https://www.pmxt.dev/docs/api-reference/fetch-order-book.md) | Polymarket、Kalshi、Limitless、Opinion | 未注明 | tick 级 Parquet + API 查询 |
| [Oddpool](https://docs.oddpool.com/kalshi/overview.md) | Kalshi | 2026-03-19 | 快照、BBO、成交，约 1 小时后可用，有免费档 |

- 【事实】官方文档里没有历史订单簿端点：Kalshi 历史数据页只列市场、K 线、成交、订单与持仓。历史 L2 只能来自当时的实时录制，数据商的覆盖可能不连续，用前要逐场检查滚球时段有无缺口。[Kalshi 历史数据](https://docs.kalshi.com/getting_started/historical_data)
- 【推演】可用样本约为 2026 年 2 月起的一个赛季，含各赛区常规赛与季后赛、MSI、EWC、Worlds 2026。足够评估 A 与 C 的频率和容量，不足以覆盖多个版本周期。
- 【事实】跨平台事件需要自己匹配：Polymarket 用 slug 与 condition\_id，Kalshi 用 KXLOLGAME / KXLOLMAP / KXLOLTOTALMAPS 系列代码，队名写法不同。第三方聚合站（如 Prediction Hunt）已在做跨平台事件匹配，可作冷启动参考。
- 【事实】比赛事件时间轴的免费来源：lolesports 网站使用的非官方 livestats 接口返回按 10 秒为一段的比赛状态帧，带时间戳，可按起始时间参数回溯已结束的对局。它相对游戏服务器的延迟未知。[接口封装说明](https://cdn.jsdelivr.net/npm/@viriato/lol-esports-api@0.6.0/README.md)
- 【宣传】GRID 的官方 LoL 数据直接取自游戏服务器，宣称端到端延迟低于 200ms，并出售实时胜率产品（Prediction Feed）。这是 B2B 产品，散户拿不到同等数据。[GRID LoL](https://grid.gg/data/games/league-of-legends/)
- 【事实】Kalshi 的 WebSocket 需要 API key 签名认证，开户与 KYC 是拿到 Kalshi 实时增量数据的前提；Polymarket 与 Predict.fun 的公开行情无需下单权限。[Kalshi WebSocket](https://docs.kalshi.com/getting_started/websocket_connection)
- 【判断】最省钱的第一步：先买 CryptoStruct 的按日包，对 2026 赛季若干场大赛做可行性检查；确认有信号再买全量。同时从现在起自录三家 WebSocket，同时保存交易所时间戳与本地接收时间戳。
- 【事实】CryptoStruct 文件格式：每个盘口每个 UTC 日一个 zstd 压缩的 JSON lines 文件。第 1 行是品种头部（id、code、native\_code、ticksize 等），之后每行一个事件：类型、品种 ID、上一事件 ID、事件 ID、接收时间与交易所时间（纳秒）、数据。类型 0 是快照，1 是增量（数量为绝对值，"0" 表示撤掉该档），2 是成交。断档靠事件 ID 链发现；相邻两天的文件有几分钟重叠，要按事件 ID 去重。[格式说明](https://cryptostruct.com/skills/cryptostruct-market-data/references/day-file-format.md)、[Polymarket LoL 系列页](https://cryptostruct.com/prediction-markets/polymarket-lol)
- 【事实】CryptoStruct 的说明没写文件里的价格对应盘口的哪个选项，也没写 native\_code 存的是什么。免费样本 lol-tl2-los-2026-10-30-game2 可以用来核实。[Polymarket 数据页](https://cryptostruct.com/exchanges/polymarket)
- 【事实】Polymarket 上买 Yes @0.60 与买 No @0.40 可以直接撮合，系统用 1 pUSD 铸造一套 Yes+No。[价格与订单簿](https://docs.polymarket.com/concepts/prices-orderbook)
- 【推演】所以一边的买单就是另一边能买到的卖单，只有一边的盘口数据也能还原两边的卖价，扫描器就是这样用 CryptoStruct 数据的。这也意味着同一盘口两边卖价相加通常不会低于 1，C 的机会只会出现在跨盘口的关系上。

## 三、A 跨平台套利：信号很多，扣费后能成交的很少

你举的例子（Polymarket GEN YES 0.46 + Kalshi GEN NO 0.51 = 0.97）在两腿都吃单时，手续费合计 2.99¢，净利约为 0。A 的真实门槛是“扣费、滑点和结算错配后仍为正”，不是显示价差。

| YES 腿价格 / NO 腿价格 | 两腿吃单 | Polymarket 吃单 + Kalshi 挂单 | Polymarket 挂单 + Kalshi 吃单 |
| --- | --- | --- | --- |
| 0.10 / 0.90 | 1.08¢ | 0.45¢ | 0.63¢ |
| 0.20 / 0.80 | 1.92¢ | 0.80¢ | 1.12¢ |
| 0.30 / 0.70 | 2.52¢ | 1.05¢ | 1.47¢ |
| 0.40 / 0.60 | 2.88¢ | 1.20¢ | 1.68¢ |
| 0.50 / 0.50 | 3.00¢ | 1.25¢ | 1.75¢ |

表中是每 $1 结算额的盈亏平衡毛价差，用官方公式计算：Polymarket 体育类 0.05×p×(1−p)，Kalshi 0.07×P×(1−P) 按 100 张向上取整到分。假设 Kalshi LoL 系列 maker 费为 0，需对 Kalshi 非标准费率表核实。挂单省费，但另一腿未成交时会变成裸头寸。

**显示价差不等于可成交机会**

- 【事实】Prediction Hunt 的 LoL 页面对一线赛事显示的两家价格接近，例如 TES vs LGD 为 Kalshi 80¢ 对 Polymarket 81¢。[TES vs LGD](https://www.predictionhunt.com/odds/lol/top-esports-vs-lgd-gaming-2026-08-13/31206)
- 【事实】同类页面里，1TAP Dino vs CyberCore 的 Kalshi 两队价格分别为 77¢ 和 50¢，合计 127¢，说明展示价不是一致的可成交买卖价。两例均为搜索引擎索引时的页面文本，原页现已跳转，无法复核。[1TAP Dino vs CyberCore](https://www.predictionhunt.com/odds/lol/1tap-dino-vs-cybercore-esports-2026-09-13/39969)
- 【推演】在我看到的样本里，显示价差大的几乎都是二三线赛事（欧洲地区联赛、学院与次级联赛），它们恰好是深度最薄的市场。
- 【推演】你提到的第三方“价差信号数量”很可能就是这类展示价差的计数。我没能找到那份报告本身；重算时必须用两侧可成交的 ask 与深度，而不是中间价或最新成交价。

**结算规则错配：“对冲”可能变成单边仓位**

| 情形 | Polymarket | Kalshi |
| --- | --- | --- |
| 比赛延期 | 超过 7 天仍未开打则 50-50，否则按实际结果 | 48 小时内未开打按“公允市价”结算 |
| 开赛前弃权 | 未进行的局按 50-50 | 无任何对局时按交易所判定的最后公允价 |
| 未进行的单局 | 该局市场 50-50 | 规则未直接覆盖，兜底为公允价 |
| 重开局 | 只算重开后的那局 | 只算官方认可的重赛 |
| 裁决来源 | gol.gg、官方信息，UMA 提案流程 | 赛事方、官方数据商、官方转播、Liquipedia、op.gg/gol.gg 等分级源 |

来源：[Polymarket LoL 单局规则镜像](https://orrery.me/markets/lol-tsw-dcg-2026-05-31-game4)、[Kalshi ESPORTSWIN 备案](https://www.cftc.gov/filings/orgrules/rules07202610832.pdf)。Polymarket 一栏以单局市场的规则文本为例，系列胜负盘需逐个核对。

- 【推演】一场比赛延期 3 天：Kalshi 那腿按公允价（比如 0.49）结算，Polymarket 那腿继续开放并按实际结果结算为 0 或 1。原本 0.97 成本的对冲会变成 ±0.5 的方向性敞口。
- 【事实】Kalshi 电竞合约的持仓问责线为每个行权价、每个会员 $25,000。这不是硬上限，但会触发交易所审查。[Kalshi ESPORTSMAPS 备案](https://www.cftc.gov/filings/orgrules/rules07202610823.pdf)

**竞争与市场分割**

- 【事实】跨平台比价与数据已经商品化：Prediction Hunt 等聚合站在每场比赛页面直接标注“跨平台价差”，PMXT、Oddpool、CryptoStruct 等出售两家的 tick 级订单簿。[PMXT](https://www.pmxt.dev/docs/api-reference/fetch-order-book.md)
- 【宣传】Odds Reference 2026-04-01 的快照：108 个多平台市场中 22 个存在 5¢ 以上分歧，其中 14 个在 24 小时内收敛。它认为 5¢ 以下的分歧通常落在买卖价差之内，不能可靠执行（全品类，非电竞）。[Odds Reference](https://oddsreference.pages.dev/predictions/learn/same-market-different-price-week-1)
- 【事实】直播体育里价差确实会长时间存在：2026 年 NCAA 四强赛中，Kalshi 与 Polymarket 在比赛进行中持续相差 10–15 个百分点，最高 25 个。作者用 15–30 秒轮询的显示价，结论是直播体育的跨平台套利仍然有限。[Yicheng Yang 案例](https://yichengyang-ethan.github.io/final-four)
- 【推演】价差能持续，主要是因为能合规同时使用两本订单簿的人很少：美国用户不能在 Polymarket 国际版开仓，受限名单国家的用户不能用 Kalshi。这道壁垒同样挡住你。
- 【推演】Polymarket 的官方做市方使用 GRID 服务器数据，Kalshi 的 LoL 做市方未知。若滚球时 Polymarket 领先，所谓 A 类机会大多是去吃 Kalshi 的陈旧报价，实质是延迟交易，而不是无风险套利。
- 【事实】资金无法在交易窗口内转移：Polymarket CLOB V2 以 pUSD 作抵押，Kalshi 用美元。两边都要预存，结算后仓位向赢的一侧倾斜，需要周期性再平衡。[Polymarket 更新日志](https://docs.polymarket.com/changelog.md)

**对你的结论**

- 【判断】如果 Kalshi 账户无法合规解决，A 对你只剩 Polymarket ↔ Predict.fun 这一对。Predict.fun 正在用奖励拉流量，奖励驱动的订单会制造价差，也会在活动结束后消失。
- 【判断】A 最有价值的产出是基础设施：事件匹配、规则对齐、三家订单簿录制。作为独立盈利来源，它不应排第一。

## 四、B 线下信息延迟：对手是拿官方数据的做市方，不是其他观众

Polymarket 的电竞做市方用的是 GRID 直接取自游戏服务器的数据，Polymarket 还给体育吃单设了延迟窗口；而你在纽约时，Polymarket 国际版只允许平仓。B 在 11 月 14 日的价值是一次测量，不是一次交易。

> （此处原为图：LoL 赛事信息链路 · 延迟数字为供应商或行业文章说法，非实测。导出时未包含，见在线文档。）

现场大屏是整条链路上唯一没有公开数字的一环，也是这次实验要测的量。

**已知事实**

- 【事实】GRID 自 2023-11-30 起是 LoL 电竞的全球官方数据合作方，也是实时官方数据的唯一分发方。Riot 在 2025-06-26 开放美洲与 EMEA 一线战队的博彩赞助，要求合作必须使用 GRID 的官方数据。[GRID 公告](https://grid.gg/riot-games-and-grid-announce-exclusive-global-esports-data-partnership/)、[GoSuGamers](https://www.gosugamers.net/news/75838-riot-opens-betting-sponsorships-for-league-of-legends-and-valorant-teams-in-the-americas-and-emea)
- 【事实】GRID 自 2025-11-07 起为 Sportstensor 提供官方数据；Polymarket 自 2026-06-21 与 GRID 直接合作，在电竞专区接入实时数据、直播和组件。[GRID 公告](https://grid.gg/polymarket-partners-with-grid/)
- 【宣传】GRID 宣称官方数据端到端延迟低于 200ms。GRID Stream 有与直播同步（约落后 30 秒）和快于直播（约落后 5 秒）两档，但其 FAQ 称 LoL 与 VALORANT 目前不提供快于直播档。[GRID LoL](https://grid.gg/data/games/league-of-legends/)、[GRID Stream](https://grid.gg/products/stream/)
- 【事实】Bayes 的说法：赛事方为完整性加的直播延迟通常是 20 秒（线下）到 5 分钟（线上），公开直播通常落后实况 25 秒到 5 分钟。[Bayes](https://sc.bayesesports.com/portal/en/kb/articles/essential-esports-betting-knowledge-the-relativity-of-game-time)
- 【事实】Bayes 向内华达博彩监管提交的材料主张：公开直播与场馆内视频都应按行业最佳实践加延迟。所以现场大屏未必是实时的。[Bayes 简报](https://gaming.nv.gov/uploadedFiles/gamingnvgov/content/about/committees/Bayes-Presentation.pdf)
- 【事实】Polymarket 体育市场开赛时自动撤销全部挂单；配置了延迟的市场，吃单要等延迟窗口结束才撮合，期间不可撤单。市场对象带有整数字段 seconds\_delay。[订单生命周期](https://docs.polymarket.com/concepts/order-lifecycle)、[开赛撤单](https://docs.polymarket.com/concepts/markets-events.md)、[市场字段](https://docs.polymarket.com/api-reference/markets/get-sampling-markets.md)
- 【事实】延迟按市场设置：第三方 2026-10-27 实测英超为 1 秒、NBA 为 0。LoL 市场的值我没能查到，该接口不在本研究环境可访问范围内。[Start Polymarket](https://startpolymarket.com/strategies/in-play-trading/)
- 【事实】滚球延迟交易已有机器人在做：2025 年 Q4，Polymarket 账户 TeemuTeemuTeemu 被报道主要交易 LoL 与 Dota 2 滚球盘，约 $208,521 利润，据称靠更快解析比赛数据。自动化与数据源均未独立核实。[Esports.net](https://www.esports.net/news/polymarket-bot-makes-over-200k-in-3-months-with-lol-dota-2-esports/)
- 【推演】那个账户的时间点早于 Polymarket 与 GRID 直接合作。之后做市方接入官方数据、吃单延迟等机制都在压缩这类窗口。现场肉眼加手机下单，在大事件上几乎不可能快过做市方撤单。
- 【事实】LoL 规则允许 Chronobreak，把比赛回溯到 bug 前的状态，现场看到的事件可能被撤销。[EWC 2026 LoL 规则书](https://cdn.esportsworldcup.com/resources/uploads/EWC_26_League_of_Legends_Rulebook_a31ae07a83.pdf)

**各项目的延迟差异**

不同项目的直播延迟确实不一样，但主因不是数据商不同。直播和公开观战源的延迟由赛事方按完整性需要设定：线上赛常为几分钟，线下赛只有几秒到几十秒。数据商之间的差别，在于数据取自比赛服务器还是解析直播流，后者会继承整段直播延迟。

| 项目 | 实时官方数据 | 官方直播落后实况 | 公开观战源或数据源落后实况 | 来源 |
| --- | --- | --- | --- | --- |
| LoL | Riot 独家授权 GRID，取自比赛服务器 | 线下（LEC，2022）：观战画面约 3–5 秒，编码推流再加 30–45 秒；远程赛：观战延迟至少 3 分钟，常用 10 分钟 | lolesports livestats 帧：未见公开数字，待测 | [LEC 制作人](https://devtrackers.gg/leagueoflegends/p/57ae37b5-what-is-the-delay-between-live-games-and-their-broadcasts-on-youtube-twitch-etc) |
| VALORANT | GRID 独家分发，取自 Riot 赛事服务器 | 未见公开数字 | 未见公开数字 | [Riot 电竞数据](https://riotesportsdata.com/en-us/valorant/) |
| CS2 | 数据权在赛事方；GRID 称与 70 多家 CS2、Dota 2 赛事方签约【宣传】 | IEM Beijing 2026：直播延后两个回合，ESL 称为限制用直播信息下注 | CSTV 中继：IEM Cologne Major 2026 为 180 秒；FACEIT 中继 = CSTV 延迟 + 24 秒；IEM Beijing 期间 HLTV 延后三个回合 | [esports.ru](https://esports.ru/counter-strike-2/news/esl-vveli-zaderzhku-v-dva-raunda-na-iem-beijing-2026/)、[ESL](https://pro.eslgaming.com/tour/?p=102796)、[FACEIT](https://support.faceit.com/hc/en-us/articles/17050697184668)、[GRID](https://grid.gg/products/live-data/) |
| Dota 2 | 同 CS2，数据权在赛事方 | 未见公开数字 | DotaTV 延迟由赛事方设，Valve 允许其要求社区直播最多延迟 15 分钟；DreamLeague S22 社区直播合计约 20 分钟 | [Valve](https://www.dota2.com/dotatv)、[Hawk Live](https://hawk.live/posts/dreamleague-s22-streaming-impossible-due-to-updated-rules-from-esl-ns) |

表中除标【宣传】者外均为【事实】，即所列来源的说法。GRID 帮助中心也写明：线上赛直播通常故意延后约 2–5 分钟，线下赛很小或没有，实际延迟因项目、赛事和转播方而异（[GRID 帮助中心](https://grid.helpjuice.com/3759126)）。

- 【推演】几分钟级的延迟都出在线上赛，而线上赛没有“现场”；线下赛恰好是直播延迟最小的场景。所以项目间的差异主要影响“官方数据对公开直播”的竞争，对现场策略 B 影响不大。
- 【推演】Worlds 决赛的场馆大屏若用观战画面，它本身就比服务器晚 3–5 秒，而 GRID 数据取自服务器、宣称 P95 低于 200ms。现场只领先看网络直播的人约半分钟，相对拿官方数据的做市方是落后的。
- 【推演】看数据商要看数据从哪来。PandaScore 自己写明，解析直播流的供应商会继承整段直播延迟；它在 LoL 与 CS2 上宣称的 300ms 也是相对已延迟的公开直播而言【宣传】（[PandaScore](https://www.pandascore.co/blog/low-latency-esports-data-feed-prediction-bot)）。

**谁拿走了利润**

- 【事实】Kalshi 约 7,210 万笔成交（至 2025-11）：吃单方平均超额收益 −1.12%，挂单方 +1.12%。但 2023 年前挂单的多为业余玩家，吃单方反而 +2.0%；差距在专业做市商进场后才翻转。[Becker 2026](https://www.jbecker.dev/research/prediction-market-microstructure)
- 【事实】Polymarket 政治盘（2025-12 至 2026-02）约 $16M 利润：一半归 0.55% 的盈利挂单钱包，另一半归 0.26% 的盈利吃单钱包。报告方 Solidus 卖监控产品，并非中立。[Yellow](https://yellow.com/news/polymarket-1-percent-wallets-half-politics-profits)
- 【事实】Polymarket 2025 年 210 个已结算大盘：超过 82% 的钱包亏钱；体育盘当年零手续费，体育钱包整体约打平，但 94% 的体育钱包净亏。[Motley Fool](https://www.fool.com/research/prediction-markets-vs-stock-market-returns/)
- 【事实】TI 2026 的 Dota 2 盘：5,004 个以买卖为主的账户合计赚约 $7.58M，16,932 个持有到结算的账户合计亏约 $7.61M（不含手续费）。[Finance Magnates](https://financemagnates.com/fintech/on-polymarket-being-right-about-dota-2-paid-less-than-trading-the-odds)
- 【事实】体育盘挂单方可拿 taker 手续费的 15% 作为返佣；电竞盘是否算体育类，文档未写明。[Polymarket 挂单返佣](https://docs.polymarket.com/programs/maker-rebates)
- 【推演】赚钱的不是“做市商”这个身份，而是更专业、更快的那一小撮人，挂单和吃单里都有。比反应速度的钱归拿官方数据的人；散户能做的是不比速度的生意：组合定价（C）、跨平台（A）、赛前判断，或赛前挂单。

**11 月 14 日实测协议（只观测，不下单）**

决赛在 Barclays Center，美东时间 14:00 开播。[lolesports 场馆政策](https://lolesports.com/en-US/news/worlds-2026-venue-event-policies)

1. 赛前（11/10–11/13）：在云主机上部署录制程序，先测到各平台接口的往返延迟。录制决赛事件下全部 Polymarket 市场的 WebSocket、Polymarket Sports WebSocket、Kalshi 与 Predict.fun 公开行情、lolesports livestats 帧和一路公开直播。每条消息同时记交易所时间戳与本机接收时间戳。
2. 赛前一小时：对决赛每个市场拉一次 CLOB 市场信息，存下 seconds\_delay、开赛时间、最小变动价位。
3. 场内：手机对时到 NTP，用带毫秒水印的录像 App 拍大屏（场馆允许个人录制），同时用打点 App 记事件：一血、每条龙、大龙、远古龙、高地塔、团灭、基地爆炸。数据只存本地，不实时外传。
4. 赛后对齐：以基地爆炸和大龙为锚点，算 Δ市场 = Polymarket 中间价跳变时刻 − 现场时刻，并同样算直播、livestats 与 Kalshi 相对现场的差。再看跳变前 2 秒内一档挂单是否先被撤，先撤说明做市方更早知道。
5. 判定：重大事件的 Δ市场 中位数 ≤ 0，B 关闭。只有 Δ市场 稳定大于 seconds\_delay 加你自己实测的下单耗时，才值得继续研究。

**11 月 10 日 NBA 彩排**

费城这场（76 人主场对凯尔特人，美东 20:00，Xfinity Mobile Arena）适合做 11/14 的全流程彩排：NBA 有带时间戳的官方逐回合数据，可以当第三把尺子。只测量，不交易。

- 【事实】NBA 于 2026-10-26 指定 Kalshi 与 Polymarket 为首选预测市场交易所，两家经 Sportradar 获得官方数据，用于运营和结算 NBA 市场。[NBA 公告](https://www.nba.com/news/nba-establishes-integrity-framework-and-commercial-partnerships-for-prediction-markets)
- 【事实】NBA 逐回合数据每条动作带 timeActual（事件发生的 UTC 时间），事后修改或补录另记 edited、inserted 时间。公开的 cdn.nba.com 逐回合 JSON 是否带同样字段，赛后验证。[Genius Sports 文档](https://developer.geniussports.com/nbangss/stream/)
- 【事实】Xfinity Mobile Arena 不允许携带录像和录音设备，这点与 Barclays 不同：彩排只打点，不拍大屏。[场馆安检政策](https://www.xfinitymobilearena.com/plan-your-visit/security-policy)

1. 19:30 前：在家里常开的电脑上启动只读记录脚本，录该场 Polymarket 全部盘口、Polymarket 比分推送和 NBA 公开逐回合数据，并顺带记下各盘口的 seconds\_delay。确认文件在增长再出门。
2. 进场前：手机打开打点页，选 NBA 预设；用 time.is 读一次手机时钟偏差，记为“赛前”；关掉自动锁屏，带充电宝。
3. 场内：球进网的瞬间按对应得分键，另记暂停和每节结束。第四节最后 5 分钟最重要，盘口此时对每球反应最大。
4. 赛后：再对一次 time.is 记为“赛后”，停脚本。打点自动存进打点页的数据库，我直接读取。
5. 对齐，产出四个分布：官方数据（timeActual 与公开 JSON 首次出现时刻）、Polymarket 比分推送、Polymarket 盘口首次变动，各自相对现场的差；以及你按键相对 timeActual 的偏差。

【推演】能迁移到 11/14 的是流程、你的按键偏差、脚本稳定性和对齐代码。数据链路（NBA→Sportradar 对 Riot→GRID）和撮合延迟设置都不同，NBA 的 Δ市场 不能直接当作 LoL 的估计。

**合规与执行约束**

- 【事实】Barclays 场馆禁止笔记本、平板和电脑；手机可个人录制；禁止未授权直播。现场只能靠手机，录制程序必须跑在场外。
- 【事实】Polymarket 国际版对美国为只可平仓，在纽约无法开新仓。[Polymarket 地理限制](https://docs.polymarket.com/api-reference/geoblock)
- 【事实】其他赛事已把“场内下注”和“为博彩采集或传输比赛数据”写进入场条款，如 EWC。Worlds 场馆政策页未提及，若将来想在场内交易，先读票务条款。[EWC 入场条款](https://esportsworldcup.com/en/ewcf-ticket-and-entry-conditions)
- 【判断】B 的预期套利收益接近 0，但实验成本很低，产出的延迟数据还能直接用来校准 C 的滚球回测。

【事实】JN 说明（11/10）：11/14 在纽约可通过 Bagel 交易，它走 Polymarket API。第三方目录把 Bagel 描述为基于 Polymarket 的移动端应用；在美国能否下单未经独立核实，赛前先用小额单验证。

## 五、C 同平台组合套利：盘口够多、关系可严格证明，但容量是散户级

Polymarket 的一场 LoL BO5 有 10 个以上相关合约，它们之间存在可以严格证明的等式和不等式。但做市方看起来用同一个单局模型定价，可做的偏离预计集中在薄盘口和滚球局面突变后的几秒到十几秒。

**盘口与结算规则**

- 【事实】典型 BO5 事件包括：系列胜负、G1–G5 单局胜者、总局数 O/U 3.5 与 4.5、让局 −1.5 与 −2.5，以及每局道具（击杀大小与单双、一血、双方都拿大龙或小龙、四杀五杀）。[事件镜像](https://orrery.me/markets/lol-tsw-dcg-2026-05-31-game4)
- 【事实】未进行的单局按 50-50 结算；重开的局只算重开后那一局。这条规则让 G4、G5 不是“条件概率”，而是带 0.5 兜底的合约，忽略它的扫描器会报出假机会。
- 【事实】开赛后没打完的结算：系列赛胜负中途因弃权、取消资格或不战而胜结束，判给获胜方；整场没打、平局或延期超过 7 天仍无胜者，50-50。让局与总局数中途因弃权等结束，50-50；比赛打完时弃权的局照常计入。单局没打完就 50-50。以上取自已结束赛事的规则原文；Worlds 决赛页面写的延期期限是 14 天。[系列赛胜负](https://polymarket.com/esports/league-of-legends/lck/lol-t1-gen-2026-06-14)、[总局数](https://explorer.struct.to/markets/lol-t1-gen-2026-06-14-total-games-4pt5)、[让局](https://orrery.me/markets/lol-mvk-cfo-2026-05-23-game-handicap-away-1pt5)、[单局](https://orrery.me/markets/lol-al-we-2026-06-01-game1)
- 【推演】所以下表的关系大多只在比赛正常打完时成立。整场取消和开赛后中途终止时仍成立的只有三条：同一盘口两边相加等于 1、让局 −2.5 ≤ 让局 −1.5、O4.5 ≤ O3.5。
- 【事实】Worlds 决赛是 BLG 对 Gen.G（slug lol-blg-gen-2026-11-14）。镜像页目前列出系列赛胜负、第 1–4 局胜负、总局数 3.5 与 4.5、Gen.G 让 1.5 与 2.5，以及每局道具；没有第 5 局胜负。[lines.com](https://www.lines.com/prediction-markets/sports/lol/lol-blg-gen-2026-11-14)
- 【事实】第三方指南和我查到的事件里都没有“准确比分”合约。你例子里的 GEN 3:0 在 Polymarket 上对应让局 −2.5；Kalshi 已备案电竞让分合约 ESPORTSPREAD，但 LoL 是否上线未核实。[Kalshi ESPORTSPREAD 备案](https://www.cftc.gov/filings/orgrules/rules08142617265.pdf)

**可以直接写进扫描器的关系（A 队视角）**

| 关系 | 类型 | 说明 |
| --- | --- | --- |
| 胜负 + 0.5×U4.5 = G5 + 让局(−1.5) | 等式 | 对 BO5 全部 20 条比分路径成立；BO3 对应胜负 + 0.5×U2.5 = G3 + 让局(−1.5) |
| U3.5 = A 让局(−2.5) + B 让局(−2.5) | 等式 | 需要双方的 −2.5 都挂牌 |
| 让局(−2.5) ≤ min(G1, G2, G3) | 不等式 | 3:0 必然赢下前三局 |
| 让局(−2.5) ≤ 让局(−1.5) ≤ 胜负；O4.5 ≤ O3.5 | 不等式 | 单调性 |
| 0.5×U3.5 ≤ G4 ≤ O3.5 + 0.5×U3.5 | 不等式 | 由第 4 局 50-50 规则推出，违反时可组出超复制组合 |

以上关系均用脚本枚举 BO3/BO5 全部正常打完的比分验证。被可成交价格违反时，能构造在所有比分下都不亏的组合；整场取消和开赛后中途终止要另外检查，见上方结算规则。在 Polymarket 上“卖出”等于买入对侧代币。

**费用门槛与定价一致性**

- 【推演】以示例价格计，第一条等式的 4 腿组合全部吃单时手续费约 3.76¢/单位；两腿单调套利（约 0.30 与 0.66）约 2.17¢。偏离小于这个量级就不值得做。
- 【推演】一场 LCP 季后赛 BO5（TSW vs DCG）的展示价：胜负 78¢、G1–G3 各 66¢、O3.5 67¢、O4.5 29¢。单局胜率 0.66 的独立模型给出 0.780、0.673、0.302，几乎完全吻合，说明主盘口来自同一模型。
- 【推演】同一场的让局展示价（−1.5 为 64¢、−2.5 为 33¢）高于模型值（0.581、0.287）。不一致更可能出现在薄盘口。这些是时间点未知的镜像展示价，不是可成交报价。

**已有实证**

- 【事实】NBA 样本（2026-02-04 至 03-04，173 场，每 3.6–5.5 秒轮询一档报价）：单市场 YES+NO 套利仅 7 次，中位持续 3.6 秒；胜负与让分组合套利 290 次，滚球中位持续 16 秒、中位收益 101bps。[Cheng, Yang, Zou 2026](https://arxiv.org/html/2605.00864v1)
- 【事实】同一研究中 76.9% 的组合机会放不下 $100，平均可成交量约 14.79 股；当时 NBA 市场零手续费。作者结论是深度把无风险收益限制在散户规模。
- 【事实】全平台层面，Saguillo 等用链上历史订单簿数据估算：2024-04 至 2025-04 套利者已实现约 $40M 利润，分为单市场再平衡与跨市场组合两类。[arXiv 2508.03474](https://arxiv.org/abs/2508.03474)
- 【推演】以上实证都在零费率时期。体育 taker 费率 2026-07-10 起为 0.05，101bps 一级的组合机会若全部吃单，多数已不覆盖费用。

**对你的结论**

- 【判断】C 是最适合先做的方向：只用一个平台、一套结算规则，关系能离线证明，历史 L2 可以买到，而且 Polymarket 屏蔽表未列中国。
- 【判断】纯吃单的 C 大概率只是散户级收入。要把它做大，执行应以挂单为主（maker 0 费、另有 15% 返还和流动性奖励），这实际上是带对冲的做市，风险变成腿风险和库存风险。

**扫描器 v2（11/10）**

- 脚本 lol\_c\_scan.py：只读，只做 Polymarket LoL。把系列赛胜负、单局胜负、总局数、让局放进同一个线性规划，算出当前卖单深度下可锁定的总利润和每个选项的买入量，含吃单费。
- 子命令：live 实时扫描；replay 回放 pm\_recorder.py 的录制；meta 导出一场比赛的盘口清单；cs-inspect 检查 CryptoStruct 文件；cs-replay 回放 CryptoStruct 历史数据。
- 约束情景：BO5 正常打完的 20 种比分，加上整场取消（全部 50-50）。开赛后中途终止的 56 种情形默认单独报告最差盈亏，加 --strict 才作为约束。
- 盘口识别：题目与盘口 slug 交叉核对，不一致就跳过。队名先比完全相同，再比包含关系，再比简称（BLG → Bilibili Gaming），有歧义就跳过，不猜。
- 未建模：多个选项不能同时成交的执行风险；吃单延迟；买入时手续费从股数还是从资金里扣（文档未写，按资金计）。
- 状态：合成数据测试全部通过，包括按 Worlds 决赛盘口清单构造的识别测试；尚未在真实接口和真实历史数据上跑过。

## 六、技术瓶颈：A 卡在准入与规则，B 卡在数据源，C 卡在深度与费用

三个方向的主瓶颈不同，但都能用同一套录制数据量化。最先要量化的是“机会存续时间 × 可成交深度”的联合分布，它直接决定资金容量和是否值得自动化。

| 瓶颈 | A 跨平台 | B 现场延迟 | C 同平台组合 | 怎么量化 |
| --- | --- | --- | --- | --- |
| 准入与合规 | 高：Kalshi 受限名单含中国 | 高：在美国只能平仓 | 低：屏蔽表未列中国 | 法务确认主体与交易地点 |
| 手续费 | 两腿吃单 1.1–3.0¢/单位 | 单腿最高 1.25¢/股 | 两腿约 2.2¢，四腿约 3.8¢ | 按官方公式逐笔计入 |
| 数据延迟 | 中：两边实时簿、时间戳对齐 | 决定性：对手用 GRID 服务器数据 | 中：滚球中几秒级窗口 | 交易所时间戳对本地接收时间戳 |
| 执行延迟 | 两腿不同步，留下单边风险 | 体育延迟窗口内不可撤单 | 多腿不同步 | 下单到成交回报的时间分布 |
| 流动性与容量 | 一线价差小于费用，二三线深度薄 | 事件发生时挂单先被撤 | 让局与道具盘最薄 | 按一至五档深度算可成交量 |
| 结算规则 | 高：延期、弃权、裁决来源不同 | 低 | 低：同一平台同一规则 | 逐条规则对照表 |
| 竞争 | 比价与数据工具已商品化 | 官方数据做市方与机器人 | 做市方按同一单局模型定价 | 机会存续时间分布 |

手续费一行的数字来自第三节与第五节的计算。三个方向共用同一套采集与规则底座，研发上不是三选一：底座先建，策略按证据排序。

## 七、研究框架：先回测，再纸面监控，最后小额自动化

建议按四个阶段推进，每过一道门槛才进入下一阶段。A、B、C 共用同一套采集层、合约本体和约束引擎，只是输入不同。

> （此处原为图：研发路线 · 4 个阶段、3 道门槛（门槛为建议，非实测）。导出时未包含，见在线文档。）

门槛是定性的建议，具体数值应在阶段 1 结束时按你的资金成本和时间成本定。

| 组件 | 作用 | 实现要点 |
| --- | --- | --- |
| 采集层 | 录下三家订单簿、成交、赛事状态 | WebSocket 为主、REST 快照校验；每条消息存交易所与本地两个时间戳；按日 Parquet |
| 合约本体 | 把每个合约映射到比赛结果空间 | 枚举 BO3/BO5 全部比分路径；把 50-50、延期、弃权、重开规则编码成每条路径上的支付 |
| 事件匹配 | 跨平台配对同一场比赛与同一结果 | 队名别名表、开赛时间容差、人工复核队列 |
| 约束引擎 | 找出被违反的无套利条件 | 线性规划，输入为可成交价与各档深度（见下式） |
| 成本模型 | 计算扣费净值 | 官方费率公式、tick、最小下单量、Kalshi 取整、资金占用时间 |
| 回测器 | 按 L2 回放成交 | 吃单按当时深度成交；挂单按排队位置保守估计；体育延迟窗口内价格可能已变 |
| 监控与风控 | 实时提醒与纸面成交 | 单场与单日敞口上限、单腿未成交时的处理规则、结算争议跟踪 |

约束引擎的核心是一个超复制问题：

```latex
\min_{x \ge 0} \; \sum_j x_j \,(\mathrm{ask}_j + \mathrm{fee}_j) \quad \text{s.t.} \quad \sum_j x_j \, a_j(\omega) \ge 1 \;\; \forall \omega \in \Omega
```

Ω 是一场比赛的全部比分路径（含未进行的局、延期与弃权情形），a\_j(ω) 是买入 1 份合约 j 在路径 ω 下的支付，YES 与 NO 代币各算一个合约。最优值低于 1 即存在无风险组合，再按最薄一腿的可成交量缩放。

- 【判断】A 与 C 共用这个引擎：跨平台只是把另一家的合约并入同一结果空间，并把规则差异（如 Kalshi 的公允价结算）编码成额外路径。
- 【判断】B 不需要独立系统：11 月 14 日的数据进入同一采集层，用来校准回测器里的延迟假设。
- 【判断】这份文档不包含下单代码。采集层可以复用你已有的 Mac mini 监控工程骨架，但延迟实验应放在离撮合服务器更近的云主机上。

## 八、待验证清单与下一步

前四项决定 A 是否留在路线上；中间三项是 11 月 14 日实测；最后三项是阶段 1 的第一批回测。

- [x] 确认交易主体与所在地对 Polymarket、Kalshi、Predict.fun 是否合规可用（找律师确认）
- [ ] 查 Kalshi 费率表：KXLOLGAME、KXLOLMAP、KXLOLTOTALMAPS 是否收 maker 费或适用非标准费率
- [ ] 查 Predict.fun 的费率、地域限制和 API key 申请流程
- [ ] 找到你提到的第三方电竞套利扫描报告，核对它用的是展示价还是可成交价
- [ ] Nov 10, 2026 19:30 前：启动只读记录脚本（Polymarket 盘口与比分推送、NBA 逐回合），确认在写文件
- [ ] Nov 10, 2026 场内：打点页选 NBA 预设，开赛前与结束后各对一次 time.is，不录像
- [ ] Nov 11, 2026 前：对齐三方时间戳，出 NBA 彩排报告，据此修改 11/14 协议
- [ ] Nov 13, 2026 前：用任意一场有 Polymarket 市场的电竞比赛（CS2 也可）演练录制程序，测出到各平台接口的往返延迟
- [ ] Nov 14, 2026 赛前一小时：拉取决赛全部市场的 seconds\_delay 与开赛时间，然后按第四节协议采集
- [ ] Nov 16, 2026 前：出延迟报告，包括 Δ市场、Δ直播、Δlivestats，以及跳变前挂单是否先被撤
- [ ] Nov 13, 2026 前：导出决赛盘口清单（python3 lol\_c\_scan.py meta --event-slug lol-blg-gen-2026-11-14），把输出发给 Claude 核对识别
- [ ] 下载 CryptoStruct 免费样本 lol-tl2-los-2026-10-30-game2，跑 cs-inspect：确认价格对应哪个选项，交叉占比接近 0
- [ ] 买 Worlds 两场半决赛的日包跑 cs-replay：两场都在美东下午 5 点开打、跨 UTC 午夜，需要 11/07–11/09 三天，约 €3
- [ ] 购买 CryptoStruct 2026 赛季样本日包，先做 Worlds 2026 淘汰赛与 LCK、LPL 季后赛
- [ ] 用样本统计 BO5 等式与不等式的偏离：可成交价、含费，并记录存续时间与可成交量
- [ ] 以可成交 ask 重算 Polymarket–Kalshi 与 Polymarket–Predict.fun 的价差分布和存续时间

## 来源

以下为本研究实际打开并引用的页面，按章节归类。

**市场结构与费率**

- [CryptoStruct · Polymarket LoL](https://cryptostruct.com/prediction-markets/polymarket-lol)、[Kalshi KXLOLGAME](https://cryptostruct.com/prediction-markets/kalshi-kxlolgame)、[Predict.fun LoL](https://cryptostruct.com/prediction-markets/predictfun-lol)
- [Doc's Sports · Polymarket 电竞成交分析](https://www.docsports.com/2026/esports-matches-drawing-major-leauge-level-betting-action-polymarket.html)
- Polymarket 文档：[手续费](https://docs.polymarket.com/trading/fees?via=xp)、[更新日志](https://docs.polymarket.com/changelog.md)、[地理限制](https://docs.polymarket.com/api-reference/geoblock)、[订单生命周期](https://docs.polymarket.com/concepts/order-lifecycle)、[市场与事件](https://docs.polymarket.com/concepts/markets-events.md)、[Sports WebSocket](https://docs.polymarket.com/market-data/websocket/sports.md)、[市场字段](https://docs.polymarket.com/api-reference/markets/get-sampling-markets.md)
- [Start Polymarket · 电竞指南](https://startpolymarket.com/guides/polymarket-esports/)、[滚球交易](https://startpolymarket.com/strategies/in-play-trading/)
- [River Markets · Polymarket US 费率](https://www.rivermarkets.com/insights/polymarket-us-fees.html)
- Kalshi：[历史数据文档](https://docs.kalshi.com/getting_started/historical_data)、[WebSocket 文档](https://docs.kalshi.com/getting_started/websocket_connection)、[ESPORTSMAPS 备案](https://www.cftc.gov/filings/orgrules/rules07202610823.pdf)、[ESPORTSWIN 备案](https://www.cftc.gov/filings/orgrules/rules07202610832.pdf)、[ESPORTSPREAD 备案](https://www.cftc.gov/filings/orgrules/rules08142617265.pdf)
- [Coinperps · Kalshi 受限名单整理](https://www.coinperps.com/learn/kalshi-restricted-countries)
- [Predict.fun SDK](https://docs.rs/predict-fun-sdk)、[Odaily · Predict.fun Worlds 活动](https://www.odaily.news/en/post/5213395)、[Gate · Worlds 预测活动](https://www.gate.com/announcements/article/102232)、[Legal Sports Report · 电竞预测市场](https://www.legalsportsreport.com/prediction-markets/esports/)
- [Paradigm · 成交量重复计算](https://cn.paradigm.xyz/2025/12/polymarket-volume-is-being-double-counted)

**数据**

- [Telonex · Polymarket](https://telonex.io/datasets)、[Telonex · Predict.fun](https://telonex.io/data/predict-fun)、[PredictionData.dev 定价](https://predictiondata-dev.pages.dev/)、[PredictionData.dev FAQ](https://predictiondata-dev.pages.dev/faq)、[PMXT](https://www.pmxt.dev/docs/api-reference/fetch-order-book.md)、[Oddpool · Kalshi](https://docs.oddpool.com/kalshi/overview.md)
- [lolesports 非官方接口封装说明](https://cdn.jsdelivr.net/npm/@viriato/lol-esports-api@0.6.0/README.md)

**A 跨平台**

- [Yicheng Yang · NCAA 四强赛案例](https://yichengyang-ethan.github.io/final-four)、[Odds Reference · 跨平台分歧](https://oddsreference.pages.dev/predictions/learn/same-market-different-price-week-1)

**B 现场延迟**

- [GRID × Riot 官方数据公告（2023）](https://grid.gg/riot-games-and-grid-announce-exclusive-global-esports-data-partnership/)、[GoSuGamers · Riot 博彩赞助](https://www.gosugamers.net/news/75838-riot-opens-betting-sponsorships-for-league-of-legends-and-valorant-teams-in-the-americas-and-emea)
- [Esports Advocate · GRID × Sportstensor](https://esportsadvocate.net/2025/11/grid-partners-with-sportstensor/)、[GRID × Polymarket](https://grid.gg/polymarket-partners-with-grid/)、[GRID · LoL 数据](https://grid.gg/data/games/league-of-legends/)、[GRID Stream](https://grid.gg/products/stream/)
- [Bayes · 比赛时间的相对性](https://sc.bayesesports.com/portal/en/kb/articles/essential-esports-betting-knowledge-the-relativity-of-game-time)、[Bayes · 内华达简报](https://gaming.nv.gov/uploadedFiles/gamingnvgov/content/about/committees/Bayes-Presentation.pdf)
- [lolesports · Worlds 2026 场馆政策](https://lolesports.com/en-US/news/worlds-2026-venue-event-policies)、[EWC · 入场条款](https://esportsworldcup.com/en/ewcf-ticket-and-entry-conditions)、[EWC 2026 LoL 规则书](https://cdn.esportsworldcup.com/resources/uploads/EWC_26_League_of_Legends_Rulebook_a31ae07a83.pdf)
- [Esports.net · TeemuTeemuTeemu](https://www.esports.net/news/polymarket-bot-makes-over-200k-in-3-months-with-lol-dota-2-esports/)
- [LEC 制作人谈观战延迟](https://devtrackers.gg/leagueoflegends/p/57ae37b5-what-is-the-delay-between-live-games-and-their-broadcasts-on-youtube-twitch-etc)、[GRID 帮助中心 · 数据与直播延迟](https://grid.helpjuice.com/3759126)、[GRID · Live Data](https://grid.gg/products/live-data/)、[Riot 电竞数据 · VALORANT](https://riotesportsdata.com/en-us/valorant/)、[PandaScore · 低延迟数据](https://www.pandascore.co/blog/low-latency-esports-data-feed-prediction-bot)
- [esports.ru · IEM Beijing 两回合延迟](https://esports.ru/counter-strike-2/news/esl-vveli-zaderzhku-v-dva-raunda-na-iem-beijing-2026/)、[ESL · IEM Cologne Major 社区直播规则](https://pro.eslgaming.com/tour/?p=102796)、[FACEIT · CSTV 中继延迟](https://support.faceit.com/hc/en-us/articles/17050697184668)、[Valve · DotaTV 社区直播政策](https://www.dota2.com/dotatv)、[Hawk Live · DreamLeague S22](https://hawk.live/posts/dreamleague-s22-streaming-impossible-due-to-updated-rules-from-esl-ns)
- [NBA · 预测市场合作公告](https://www.nba.com/news/nba-establishes-integrity-framework-and-commercial-partnerships-for-prediction-markets)、[Genius Sports · NBA 数据流文档](https://developer.geniussports.com/nbangss/stream/)、[Xfinity Mobile Arena · 安检政策](https://www.xfinitymobilearena.com/plan-your-visit/security-policy)、[Polymarket · WebSocket 频道](https://docs.polymarket.com/market-data/websocket/overview)

**C 同平台组合**

- [Polymarket LoL 单局规则镜像](https://orrery.me/markets/lol-tsw-dcg-2026-05-31-game4)
- [Cheng, Yang, Zou (2026) · Polymarket NBA 套利](https://arxiv.org/html/2605.00864v1)、[Saguillo et al. (2025) · Polymarket 套利](https://arxiv.org/abs/2508.03474)
- [Polymarket · T1 vs Gen.G 规则](https://polymarket.com/esports/league-of-legends/lck/lol-t1-gen-2026-06-14)、[Struct · 总局数规则](https://explorer.struct.to/markets/lol-t1-gen-2026-06-14-total-games-4pt5)、[Orrery · 让局规则](https://orrery.me/markets/lol-mvk-cfo-2026-05-23-game-handicap-away-1pt5)、[Orrery · 单局规则](https://orrery.me/markets/lol-al-we-2026-06-01-game1)、[lines.com · Worlds 决赛盘口](https://www.lines.com/prediction-markets/sports/lol/lol-blg-gen-2026-11-14)
- [CryptoStruct · 文件格式](https://cryptostruct.com/skills/cryptostruct-market-data/references/day-file-format.md)、[CryptoStruct · 读取脚本](https://cryptostruct.com/skills/cryptostruct-market-data/scripts/cryptostruct_reader.py)、[CryptoStruct · Polymarket 数据](https://cryptostruct.com/exchanges/polymarket)、[Polymarket · 价格与订单簿](https://docs.polymarket.com/concepts/prices-orderbook)

仅见搜索摘要、未能打开原文的：Sheep Esports 的 Polymarket Worlds 流动性奖励文章；Prediction Hunt 的单场比赛页（已跳转至其他域名）。
