# NBA 彩排出门清单 · 2026-11-10 76ers 对 Celtics

只测量，不交易。录制在家里一直开着的 Mac 上跑，手机进场只打点。

## 已核实的配置（11/10 美东 11:30 在云端会话实测）

| 项目 | 值 | 来源 |
| --- | --- | --- |
| Polymarket 赛事 slug | `nba-bos-phi-2026-11-10`（标题 “Celtics vs. 76ers”，开赛 2026-11-11T01:00Z = 美东 20:00） | 【事实】Gamma `events?slug=` |
| 盘口 / token | 452 个盘口，904 个 token，全部 accepting orders；以球员道具为主（得分 64、篮板 64、助攻 48、三分 46），另有让分 33、总分 30 等 | 【事实】Gamma |
| seconds_delay | 452 个盘口全部为 0 | 【事实】CLOB `markets/<condition_id>`，赛前值，开赛后是否改变由 meta_end.json 记录 |
| NBA 比赛编号 | `0022600212`（BOS @ PHI，Xfinity Mobile Arena，01:00Z） | 【事实】cdn.nba.com 全赛季赛程 `scheduleLeagueV2.json` |
| 逐回合文件 | 赛前返回 HTTP 403；已结束比赛（0022600203）返回 200 | 【事实】实测。【推演】开赛前文件还没生成，403 属正常 |

- 【事实】cdn.nba.com 的 403 不是 IP 封锁：不带 `Referer/Origin: https://www.nba.com` 时返回 403，带上（录制脚本默认就带）返回 200。
- 【事实】`todaysScoreboard_00.json` 在美东 11:25 仍停在 2026-11-09，所以 `--nba-teams PHI,BOS` 当时查不到今晚这场。已给录制脚本加了回退：比分板查不到时按美东日期查全赛季赛程（v0.1.2）。**今晚直接用 `--nba-game-id 0022600212`，新旧版本脚本都适用。**
- 【事实】Polymarket 比分推送只推正在进行的比赛；上午样本里没有 NBA，所以 NBA 消息的队名写法（76ers 还是 PHI）未核实。【判断】今晚不加 `--sports-filter`：上午实测约 2 条/秒，全部保留每小时只有几 MB，过滤反而可能把 NBA 消息滤掉。
- 【推演】盘口数据量：赛前稳定后约 31 KB/秒（≈110 MB/小时）；开赛后会更多。【判断】提前到 15:00 启动后录制约 10 小时，Mac 上至少留 5 GB 空间。
- 【推演】盘口清单在启动时固定：15:00 之后才上架的盘口不会被订阅。主盘（胜负、让分、总分）赛前已在，影响有限；赛后在云端重新取 Gamma 盘口清单，对比 `meta_start.json` 看漏了哪些（`meta_end.json` 只覆盖启动时的盘口）。

## 14:30–14:50 出门前在家里 Mac 上（JN 15:00 出门，改为提前启动）

1. 进入项目目录，确认依赖（Python 3.9 以上）：

```bash
cd ~/lol-pm-arb
```

```bash
python3 -m pip install websockets certifi
```

2. 15 秒自检：

```bash
python3 recorder/pm_recorder.py --event-slug nba-bos-phi-2026-11-10 --nba-game-id 0022600212 --check
```

**正常的样子**：
- `赛事：Celtics vs. 76ers · 盘口 452 个 · token 904 个 · seconds_delay 取值 0`（盘口数可能略有增减）
- `pm_market#0` 到 `pm_market#9` 共 10 条 `connected`，加 `pm_sports connected`
- 每 5 秒一行状态，`盘口消息` 数字在涨；`重连 0`
- 最后一行：`检查结果：盘口 正常；比分推送 正常；NBA 逐回合 HTTP 403（开赛前可能还没有文件）`
  - 开赛前 NBA 逐回合 403 正常；脚本每 5 秒重试，文件出现后自动开始记录，不需要人在家再自检。赛后看 `nba_pbp.jsonl` 有没有内容即可
- 输出目录里的 `clock.jsonl` 有 `offset_ms`。云端会话里 pool.ntp.org 解析失败，家里网络应该正常；如果出现 `error`，不影响录制，赛后用 time.is 的两次读数补偿

3. 正式录制（15:00 前启动；10 小时覆盖到约 01:00）：

```bash
caffeinate -i python3 recorder/pm_recorder.py --event-slug nba-bos-phi-2026-11-10 --nba-game-id 0022600212 --hours 10 --out rec_nba-bos-phi-2026-11-10
```

4. 出门前看一眼：每 30 秒一行状态，`盘口消息` 在涨、`重连` 不在快速增加。`caffeinate -i` 只防闲置睡眠：笔记本不要合盖，Mac mini 不用管。

## 进场前（手机）

1. 打开线上打点页 <https://claude.ai/artifact/GAcuu2okikTFXbesm3HJy9>（本地 `taplog/index.html` 没有数据库，只能复制 CSV）。顶部状态显示已连上数据库。
2. “场次、对时与导出”里选 **NBA**，A 队 `PHI`（主队）、B 队 `BOS`。已有旧打点就先点“开始新场次”。
3. 浏览器打开 time.is，按显示的快/慢秒数填进去，点 **记为赛前**。
4. 关掉自动锁屏，带充电宝；比赛中不刷新页面、不清浏览器数据。

## 场内

- 【事实】Xfinity Mobile Arena 禁止录像和录音设备：只打点，不拍。
- 球进网的瞬间按对应键：`+2 / +3 / +1 罚球`，分 PHI 和 BOS。
- 暂停或死球按 **暂停**，每节结束按 **节末**，其他值得记的事按 **标记**（可加备注）。
- 第四节最后 5 分钟最重要：盘口这时对每一球反应最大。

## 赛后

1. time.is 再读一次，点 **记为赛后**。
2. 等脚本自然结束，或 Ctrl+C 停止（已写入的数据不会丢）；最后会写 `meta_end.json`，含各盘口收盘时的 seconds_delay。
3. 确认目录里有 `pm_market.jsonl`、`pm_sports.jsonl`、`nba_pbp.jsonl`（应有内容）、`clock.jsonl`、`meta_start.json`、`meta_end.json`、`nba_pbp_final.json`。
4. 压缩录制目录，11/11 放进仓库或上传到会话，用来对齐：现场打点、NBA timeActual、Polymarket 比分推送、盘口首次变动。

## 未核实

- 赛中 Polymarket 比分推送里 NBA 消息的格式（队名写法、是否带比赛编号）。
- 公开逐回合 JSON 是否带 timeActual 等字段（研究文档已列为赛后验证）。
- 线上打点页与仓库里的 `taplog/index.html` 是否为同一版本（本次只核对了源码：NBA 预设 PHI/BOS、得分键、暂停、节末、赛前/赛后对时都在）。
