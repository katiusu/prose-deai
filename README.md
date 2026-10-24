# prose-deai

中文现代文写作规范 + 可执行自查脚本。目标只有一个：让文字像人写的——长句不断气，逗号少但不粘连，细节能数清，AI 味的模具、套话、跨章漂移被限量。

适用：**任何现代文**——小说（网文/短篇/严肃向）、叙事与抒情散文、随笔、记叙文、议论文、说明文、演讲稿。文体不同挂的层不同，见 SKILL.md §0 文体路由表。

## 硬约束：每次写完正文都要跑门

这不是建议，是交付条件。写完任何文字（一章、一段、一处改写、一篇作文）都跑一次，`VERDICT: PASS` 才算完成：

```bash
# 小说/记叙文
bash gates/postwrite.sh 正文/第001章.md
# 作文/议论文/说明文（跳过网文专属闸，保留禁词、套话、句式、一致性）
bash gates/postwrite.sh 作文/论坚持.md --essay
# RECEIPT: 第001章.md rc=0 VERDICT: PASS ... @ 2026-10-22 05:30:00
```

`FAIL` 就按命中条目改，改完重跑；回复里要带 `RECEIPT:` 行——没有回执等于没跑。Agent 侧把同一条写进 `AGENTS.md`，就不需要每次靠记忆提醒。

## 它治什么

| 病征 | 规范 |
|---|---|
| 一个动作一句话，句子碎成电报体 | 单句 50–120 字，句内逗号 0–3 个，靠连动／顿号／分号承接 |
| 逗号密度过高（一段五六个逗号） | 2.5–4.5 个/百字，超出先合并分句而不是抠标点 |
| `充满X的Y` 定语链、`如同/仿佛` 明喻铺满 | 配额：`充满` ≤3/千字，明喻 ≤1/300 字 |
| 每段都用"我能清晰地感觉到"起句 | ≤2 次/场景 |
| 一批句子骨架重复（句法模板化） | TCI10／复读句／句长 CV 三项对同句数人类分位；≥100 句才判模板化，<40 句只给句级榜；句级 ≥0.5 换骨架不换词 |
| 跨章文风漂移（第 10 章像另一个人写的） | 七项风格指标 vs 前文基线，\|z\|>3 先判断是不是剧情需要 |
| 作文套话成串（首先/其次/综上所述/在当今…时代） | 强套密度 ≤0.8 处/千字；删过渡词直接摆观点 |
| 句子停在单个实字上（`…一点腥`／`…一层红`） | 换成词语，不改句式（腥→腥气、红→红晕） |
| 部位清点式（腰、胸口、喉咙各点一次再收一句发声） | 直接写发声或写动作带出声音 |
| 动词省补语（`不肯松`、`没答`） | 写全：`不肯松开`、`没有回答` |

完整规则见 [SKILL.md](SKILL.md)。

## 用法

```bash
git clone https://github.com/katiusu/prose-deai ~/.agents/skills/prose-deai

# 只看风格层
python3 scripts/check_prose_dense.py 正文/第001章.md

# 一把跑完（命中 R18 词表时自动追加用词层）
bash scripts/run.sh 正文/第001章.md

# 作文模式：查套话 + 句式，跳过网文专属层
bash gates/postwrite.sh 作文/论坚持.md --essay
python3 scripts/check_essay_slop.py 作文/论坚持.md
```

退出码：`0` 通过，`1` 有强禁项。配额与密度只提示，不阻断。

## 输出示例

```
== 正文/第001章.md  OK
   R18: no
VERDICT: PASS
```

命中时：

```
== 正文/第002章.md  2 处
   [强禁] 句末单字:腥（换成词语，不改句式）
   [强禁] 句末单字:红（换成词语，不改句式）
合计违规 2 处
```

## 文件

```
SKILL.md                     主规范（14 节），含强制交付门禁
gates/                       门禁脚本包：总调度 + 写后回执 + 英文闸 + 覆盖对照表
gates/run_gates.sh           按语言路由，逐闸执行，给总体裁决
gates/postwrite.sh           跑门 + 落回执，末行输出 RECEIPT
gates/check_slop_en.py       英文 AI 味闸（stop-slop 规则独立实现，MIT）
gates/对齐表.md              与上游规则集的覆盖对照 + 冲突裁决
references/intimacy.md       可选扩展：亲密场景的用词与节奏（独立，不读也可用全部主规则）
scripts/check_prose_dense.py 风格层检查：句末单字／配额／逗号密度／题材词表探测
scripts/check_syntax_tpl.py 句式骨架检查：POS 5-gram 的 TCI10／句长CV／复读句／CDR，按句数分档判级（按 arXiv 2407.00211）
scripts/check_style_consistency.py 文风一致性检查：七项指标 vs 前文章节基线（稳健 z 判漂移）
scripts/check_essay_slop.py 作文套话检查：强套/弱套分档，按密度判（议论文、说明文、散文）
corpus/calibration.json     人类同句数分位校准表（3 部作品 36146 句，6 个句数档）
corpus/ref_templates.json   人类高频模板集（20396 条，CDR 的参考集）
corpus/human_baseline.md    旧口径自基线语料（保留兼容 --baseline）
scripts/tplcore.py          建表与检测共用的模板内核
scripts/build_reference.py  语料库 → 校准表 / 模板集（语料本体不入库）
scripts/check_intimacy.py    用词层检查：代称、语境指代（可选）
scripts/run.sh               一把跑完
```

## 依赖

Python 3.9+。装了 `jieba` 就按真实词边界判断句末单字；没装则退回内置白名单兜底，不会崩。

## License

MIT
