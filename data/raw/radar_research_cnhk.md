# 港股+中概深跌扫描池实测（2026-09-22，全实测）

## 结论
可行。固化池 = 恒指 88（yfiua CSV）+ 中概 ADR 34（DADA 已退市剔除）= 122 标的；yahoo.py 现有节流全量日更约 40-60 秒，池小无需预筛省请求。

## 恒指池
- 源：https://yfiua.github.io/index-constituents/constituents-hsi.csv（与 config.yaml 现有 ndx100_url 同仓库同格式，Symbol,Name 表头，Yahoo 直用代码如 0700.HK；JSON 版 constituents-hsi.json 同源；Wikipedia 后备）
- 实测：200，89 行=88 只，含 2025 新纳入 9992.HK；官方 hsi.com.hk 不可机读（JS 壳/JSON 404/仅 PDF）
- 抽样 10/10 通过 chart(rng=3y)：全部 736 根（2023-09-21→2026-09-18），HKD 计价，量能齐全，最小 30 日均成交额 5.1 亿港币；样本 dd52w：0700 -38.2 / 9988 -41.0 / 1810 -55.6（最深）等，0/10 达 -60

## 中概 ADR 池（34/35 通过，全部 752 根，唯一失败 DADA 404 已退市）
BABA -38.8 / JD -24.6 / PDD -42.5 / BIDU -43.2 / NTES -23.5 / TME -67.6 / BILI -57.8 / IQ -63.3(仙股$0.99) / NIO -53.6 / XPEV -62.9 / LI -55.5 / TCOM -48.3 / YUMC -28.7 / BEKE -18.7 / ZTO -26.0 / HTHT -22.0 / EDU -13.3 / TAL -9.0 / GDS -27.0 / VNET -48.1 / WB -47.8(成交额<1000万) / MOMO -34.3(<500万) / ATAT -23.8 / QFIN -74.4 / FINV -57.2(<500万) / LX -86.6(仙股$0.78 慢性阴跌) / NOAH -33.8(83万/日 池内最差) / RLX -34.5(仙股$1.73) / YMM -41.7 / DIDIY -45.6(PNK 粉单仅观赏) / BZ -41.1 / KC -43.5 / TIGR -56.3 / FUTU -42.6

## 规则建议（采纳）
1. 预筛不复用 T2 的 -50：中概 34 只有 10 只(29.4%)≤-50，稀缺含义失效；-55 只少 1 名；**池小直接 -60 单级筛**，-50~-60 做「接近资格线观察名单」展示层
2. B 档 -60/250 日军规不动（可比性优先；中概达标者半数是 LX/IQ 类慢性阴跌，放宽只放进结构受损标的）
3. 真正的闸是 T3 定义闸：小盘流动性剔除（NOAH/MOMO/FINV/LX）、仙股 <$2 剔除（IQ/LX/RLX）、粉单 DIDIY 仅观赏——剔完核心中概约 25 只可进状态机
4. HKD 口径：dd 为价格比率不受影响；成交额与美元比较需 /7.8；HKD 不在 USX/GBX 换算名单，无需改 yahoo.py
5. bars：HK 736 / ADR 752，均满足 len>=60、252、504 需求；write_kline 756 上限恰好容纳

## 发现的存量 bug
Yahoo chart meta 无 marketCap 字段（AAPL/0700.HK/BABA 三验证）→ knives.py:147 的 mcap 恒为 None；spec_core.json:257「市值取 chart meta.marketCap」不成立。中概 T2 若要市值闸，用本固化清单人工分层替代。
