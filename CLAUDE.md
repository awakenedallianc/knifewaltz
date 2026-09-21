# 刀尖舞 KnifeWaltz · 给 Claude Code 的项目说明

1. 先读 `PROGRESS.md`（断点）与 `data/state/spec_core.json`（产品规格核心：品牌/IA/信号引擎/风控框架）。完整规格书在 D:\机会监控\data\raw\blade_channel_spec.json。
2. 本站铁律：**运行时零大模型**（Jev 只允许离线跑批回概率）；**统计不撒谎**——每个数字带数据源徽章与口径标注（自算 vs 引用），胜率必配 Wilson 区间与最差一次；**双口径并列**（持有 252 日 vs A 档执行口径）。
3. 设计语言「鞘 SAYA」（v2，规格全文 `data/state/style_spec.json`，表面是公文/内里是刑场）：--up/--down 可翻转（静息降饱和，仅当日实时值用 --up-live/--down-live）；--blood/--signal/--amber 永不参与翻转；**金 --gold 每页 ≤1 个元素**（优先级：插入字卡 > 判定行 > FLIP-BACK 徽标 > 抽屉 CATCH 金点）；血红每屏面积 <2%；**全站动效恰 4 种**（hazard 警戒纹唯一无限动画且仅 RED 态 / 判定行打字机每会话一次 / hover 0.1s 迟到红残影 / 抽屉 160ms），白名单外动效即 bug；方角零圆角；显示字体 KW Serif（Noto Serif SC Black 子集，改显示用字后跑 `python scripts/subset_font.py` 并同步 `scripts/display_chars.txt`，缺字回退宋体）。
4. 状态持久化：`data/state/*.json` 由 Actions 提交回仓库（台账 ledger.json、状态机 knife_states.json、重放缓存 vix_replay.json）。`data/history.sqlite` 与 `docs/` 不进 git。
5. 军规语义（勿再弄混）：A 档=恐慌反弹（≤1 月，只接 T1，三层止损）；B 档=价值回归（-60% 资格线，36 个月，无时间止损）；3-12 个月=动量死区禁接；T3 永不发信号。
6. 发布：目前手动 git push（触发 Actions 构建+部署）。姊妹项目机会监控在 D:\机会监控（互不影响）。
7. 本地预览：机会监控的 .claude/launch.json 里 `kw`（端口 8792）。
