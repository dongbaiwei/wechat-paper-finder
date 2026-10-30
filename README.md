# WeChat Paper Finder · 论文批量信息卡

**把导师分享的论文截图、公众号推文或 DOI，整理成格式统一、来源可查的论文信息卡。**

支持一张截图中的多条推荐、一篇推文中的多篇论文，以及多个链接或 DOI。默认提供基本信息和论文原文链接；需要时再生成中文摘要、关联文献入口或复现资源清单。

这是一个 **Codex Skill + Python 命令行工具**。Skill 负责组织模型的识别、检索与核验，脚本负责元数据查询、去重、缓存和导出。

[快速开始](#快速开始) · [输出示例](#输出示例) · [命令行使用](#命令行使用) · [扩展功能](#扩展功能) · [开发与验证](#开发与验证)

## 能帮你做什么

| 你提供 | 项目如何处理 |
|---|---|
| 一张或多张微信分享截图 | 识别各条推荐，检索对应论文，保留截图与论文的对应关系 |
| 公众号链接、复制的正文或保存的文章 | 提取主要推荐论文；一篇推文可以对应多篇论文 |
| 论文链接、DOI 或 arXiv ID | 查询正式书目信息，整理作者机构和原文链接 |
| 多个来源重复推荐同一篇论文 | 对已核验的相同 DOI／版本合并卡片，保留全部来源 |

默认处理**主要推荐论文**。候选不确定、来源打不开或字段缺失时，保留记录并标注待核实，不会强行给出完整答案。预印本与正式发表版本分别记录。

## 快速开始

### 1. 安装到 Codex

需要 **Python 3.10+**。在终端执行：

```bash
git clone https://github.com/dongbaiwei/wechat-paper-finder.git
cd wechat-paper-finder
python scripts/install_skill.py
```

安装位置为 `$CODEX_HOME/skills/wechat-paper-finder`；未设置 `CODEX_HOME` 时使用 `~/.codex/skills/wechat-paper-finder`。如果当前聊天没有显示技能，请打开新聊天。

> Windows 上如果 `python` 不可用，可使用 `py` 或实际 Python 路径。基本元数据查询使用 Python 标准库，无必填 API key。处理截图还需要所在 AI 环境具备视觉／OCR 和联网检索能力。

### 2. 上传材料并调用

上传截图后，或在消息后附上链接／DOI：

```text
使用 $wechat-paper-finder 处理这些截图，输出精简论文信息卡。
```

批量处理也可以一次说明：

```text
使用 $wechat-paper-finder 处理下面的多个 DOI，合并重复论文，
输出信息总表和每篇论文的详细卡片，并保存 Markdown、CSV 和 JSON。
```

### 3. 查看结果

单篇直接展示信息卡；多篇提供总表与逐篇卡片，并导出：

| 文件 | 用途 |
|---|---|
| `basic-cards.md` | 阅读、分享和保存论文卡片 |
| `basic-cards.csv` | 用 Excel 查看、筛选和整理 |
| `basic-cards.json` | 保存结构化字段、来源和核验状态 |

更新已安装的 skill 时，先检查本地自定义修改，再执行：

```bash
git pull --ff-only
python scripts/install_skill.py --update
```

## 输出示例

每篇卡片固定包含以下信息。下表是**格式示意**，不是一篇真实论文的完整结果。

| 字段 | 展示内容 |
|---|---|
| 标题 | 正式论文标题 |
| DOI | 完整 `10.…` 编号及可点击的 DOI 永久链接 |
| 作者与机构 | 完整作者名单，以及每位作者发表时的所属机构 |
| 期刊与年份 | 期刊名称、论文发表年份 |
| 影响因子（JIF） | 数值、指标年份、来源链接、查询日期及缓存状态 |
| 原文网站 | 出版社论文页面，或预印本的正式托管页面 |
| 核验与缺失信息 | 论文身份是否核验、与输入是否对应、哪些字段仍待补充 |

**DOI 每篇必列。** 查不到时显示“未查到／待确认”，候选编号标为“待核验”。论文身份已核验，也可能仍缺少机构或 JIF，字段状态会分别展示。

JIF 按期刊和指标年份缓存，30天内复用并保留原查询日期；超过30天标为待更新，更新失败时记录原因。预印本没有自身的期刊影响因子。

**完整作者机构和 JIF 可能需要模型继续查阅权威来源。** 单独运行 CLI 得到的可能是待补全卡片，缺失字段会如实标注。具体补充方式见[精简卡片工作流](references/basic-cards.md)。

## 命令行使用

以下命令在项目目录运行。截图和中文推文的理解由模型及其视觉、检索工具完成；CLI 接收整理后的标识符或清单。

### 生成一篇论文的精简卡片

```bash
python scripts/paper_finder.py prepare --doi "10.1038/s41586-021-03819-2" --profile basic --out results/paper --cache work/http-cache --jif-cache work/jif-cache
```

这会查询元数据并生成卡片草稿。需要补充作者机构或指标时，编辑生成的 `research-details.json`，再按[字段说明](references/basic-cards.md)合并。

### 汇总多份论文清单

先分别准备各输入的 `papers.json`，再执行：

```bash
python scripts/paper_finder.py collect --manifests results/card1/papers.json results/card2/papers.json --profile basic --out results/batch --jif-cache work/jif-cache
```

汇总保留输入来源和失败项，并对已核验的相同 DOI／版本去重。跨批次复用 JIF 时，使用相同的 `--jif-cache` 目录。

> **模式区别：** Skill 默认显式传入 `--profile basic`；为兼容旧用法，CLI 不传 `--profile` 时仍生成完整研究报告，也可显式指定 `--profile full`。

<details>
<summary>从推文或文本开始：提取 → 查询 → 生成卡片</summary>

```bash
python scripts/paper_finder.py extract --input examples/post.md --out work/intake.json
python scripts/paper_finder.py resolve --input work/intake.json --out results/post --cache work/http-cache
python scripts/paper_finder.py prepare --manifest results/post/papers.json --profile basic --out results/post
```

也可用 `extract --url "推文网址"`。模型需要审阅提取的线索、论文角色和候选匹配；`resolve` 的首选候选不一定就是正确论文。仅有中文宣传标题时通常需要额外检索。

分享卡片的发现命令、候选确认及来源对应规则见[分享卡片找原文](references/share-card-discovery.md)和[论文匹配规则](references/matching.md)。

</details>

## 扩展功能

这些功能按需启用，默认信息卡不查询中文摘要、Connected Papers 或复现资源。

| 需求 | 可以这样调用 |
|---|---|
| 中文摘要 | `使用 $wechat-paper-finder 补充这篇论文正式摘要的中文翻译。` |
| 关联文献入口 | `使用 $wechat-paper-finder 查找这篇论文的 Connected Papers 图谱，无法取得时提供检索入口。` |
| 复现资源清单 | `使用 $wechat-paper-finder 整理论文的数据、代码、环境、材料仪器和补充材料链接。` |
| 完整研究准备报告 | `使用 $wechat-paper-finder 生成完整研究准备报告，包含以上三个模块。` |
| 正文下载 | `使用 $wechat-paper-finder 下载这篇论文可合法获取的正文 PDF，保存到我指定的文件夹。` |

完整报告额外生成 `research-report.md`、`research-details.json` 和 `reproduction-checklist.csv`。详细流程见[研究准备工作流](references/research-preparation.md)。

<details>
<summary>关联图谱与复现资源的核验方式</summary>

- Connected Papers 使用**论文完整英文题名**检索。检索入口与实际图谱分别标注；只有检查过起点论文的图谱才记为已核验。
- 资源清单区分本文作者提供、第三方工具和引用研究的资源；软件版本、材料型号及访问条件以原始来源为准。
- 复现清单用于准备工作。它不会自动执行代码、安装实验环境或下载大型数据，也不代表已经成功复现。

</details>

<details>
<summary>下载依赖、开放全文来源与可选配置</summary>

启用 PDF 校验：

```bash
python -m pip install ".[pdf]"
```

正文下载可使用 arXiv、Europe PMC OA、Unpaywall 或已核验的开放／授权链接。下载后检查格式、可读性和首页题名，并记录版本、页数及 SHA-256。BibTeX 只导出已核验记录。

Unpaywall 可选，配置自己的联系邮箱后可增加开放全文查询覆盖：

```powershell
# Windows PowerShell
$env:UNPAYWALL_EMAIL = '你的联系邮箱'
```

```bash
# macOS / Linux
export UNPAYWALL_EMAIL='你的联系邮箱'
```

截图依赖所在 AI 环境的视觉／OCR 工具；PDF、Word 等文档需要可用的解析工作流。在原作者环境中分别使用 `ds-vision-skill` 和 MinerU。机构全文需要用户授权的浏览器会话或下载工具，CLI 不自带机构登录能力。默认下载正文，补充材料需另行请求。

</details>

## 使用边界与数据说明

- 微信页面可能受登录、验证码或抓取限制影响；可改用截图或复制正文继续检索。
- 找到 DOI 不保证能取得全文，开放索引和出版社访问条件会影响下载结果。
- 元数据主要来自 Crossref／arXiv；缺失字段由模型检索并记录证据。
- OCR、文档解析和检索可能将输入发送至所配置的服务；处理敏感材料时选择合适的本地工具或仅提供书目线索。
- 真实截图、推文全文、论文 PDF、个人配置和缓存留在本地。项目不需要机构密码、导出的 Cookie 或上传到仓库的密钥。

## 开发与验证

```bash
python -m pip install ".[dev]"
python -m unittest discover -s tests -v
```

离线测试覆盖候选冲突、重复 DOI、版本区分、缺失字段、JIF 缓存、PDF 校验及导出。GitHub Actions 配置覆盖 Windows／Linux 和 Python 3.10、3.12、3.13。

10个真实 DOI 的元数据烟测与缓存验证可单独运行；它不代表同模型端到端速度对照。样本、验证记录和对照方法见[测试与性能对照](references/benchmark.md)。

| 位置 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | Skill 入口与工作流 |
| [scripts/](scripts/) | 提取、查询、卡片导出、完整报告及安装脚本 |
| [references/](references/) | 字段格式、核验规则和详细用法 |
| [examples/](examples/) | 脱敏示例、合成演示及公开 DOI 样本 |
| [tests/](tests/) | 离线行为测试 |

## 数据源与许可

[Crossref](https://github.com/Crossref/rest-api-doc) · [arXiv](https://info.arxiv.org/help/api/user-manual.html) · [Europe PMC](https://europepmc.org/RestfulWebService) · [Unpaywall](https://unpaywall.org/products/api)

本项目代码使用 [MIT License](LICENSE)，论文、推文及第三方内容遵循各自许可。

欢迎通过 [Issues](https://github.com/dongbaiwei/wechat-paper-finder/issues) 提供已脱敏的失败案例、预期结果和工具版本。
