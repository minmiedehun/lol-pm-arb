# lol-pm-arb

LoL 电竞预测市场套利研究的代码与资料。所有脚本都只读，不下单。

- 背景、约束、已核实事实、下一步：见 `CLAUDE.md`（Claude Code 会自动读取）
- 研究文档快照：`docs/research_doc.md`
- 对话经过：`docs/conversation_log.md`

## 在 claude.ai/code（网页版）里用

1. 在 claude.ai/code 新会话页面选这个仓库。
2. 环境设置见 `CLAUDE.md` 的“运行环境”一节：Network access 选 Custom，填 Polymarket 等域名，勾选默认包管理器列表。
3. 依赖由 `.claude/settings.json` 的 SessionStart hook 自动安装，不用写 Setup script。

## 在本机用

```bash
cd lol-pm-arb
python3 -m pip install -r requirements.txt
./run_tests.sh
```

## 常用命令

```bash
python3 scanner/lol_c_scan.py meta --event-slug lol-blg-gen-2026-11-14
python3 scanner/lol_c_scan.py cs-inspect 样本.txt.zst --event-slug <赛事slug> --head 5
python3 scanner/lol_c_scan.py cs-replay 数据目录/ --event-slug <slug1> <slug2>
python3 recorder/pm_recorder.py --event-slug <slug> --check
```
