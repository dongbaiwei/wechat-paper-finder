# 公众号论文查找 · WeChat Paper Finder

从微信公众号链接、截图或复制的正文找到推文推荐的原论文，核实正式题名、DOI 和出版社链接，并按需下载可合法获取的 PDF。

这是一个 **Codex Skill + Python 命令行工具** 小项目。模型负责理解推文、处理中文译名和判断论文角色；脚本负责元数据查询、候选整理、下载与文件校验。完整 Skill 需要具备相应工具的 agent；CLI 本身主要识别明确的标识符和带标签的题名。

## 能做什么

- 接收微信公众号 URL、保存的 HTML、文字或 Markdown；通过 agent 的 OCR/视觉、文档工具接收截图和 PDF/Word。
- 接收导师转发的文章分享卡片截图：识别可见标题、公众号名和摘要，搜索并核对原推文，再从全文识别论文。
- 一张截图含多张卡片时逐条查找；一篇推文介绍多篇论文时逐篇记录，最后汇总并保留推文与论文的对应关系。
- 保留原文证据、来源与匹配依据，区分主要推荐、背景引用和延伸阅读。
- 用 Crossref 查询 DOI/题名，用 arXiv 查询明确的 ID 和版本。
- 发现并保留候选；存在冲突或只有中文译名时由 agent 进一步核验。
- 从 arXiv、Europe PMC OA、Unpaywall 或明确授权的链接获取正文 PDF。
- 检查 PDF 格式、可读性和首页题名；记录版本、来源、页数与 SHA-256。
- 输出 Markdown 报告、JSON 清单、BibTeX 和 PDF；重跑时校验已有文件。

## 安装与本地使用

需要 Python 3.10+。在克隆或解压后的项目目录执行：

```bash
python -m pip install '.[pdf]'
python scripts/install_skill.py
```

安装脚本将 `SKILL.md`、`agents/`、`references/`、`scripts/` 复制到 `$CODEX_HOME/skills/wechat-paper-finder`；未设置 `CODEX_HOME` 时使用 `~/.codex/skills/`。已有同名技能时停止，确认更新后加 `--update`。也可用 `--skills-dir PATH` 指定位置。

如果 `python` 不在 PATH，请使用实际 Python 路径；不需要把密钥或账号放入项目。安装后若当前聊天未列出技能，打开新聊天。

直接对 Codex 说：

```text
使用 $wechat-paper-finder 找出这篇公众号推文主要推荐的论文，
核实正式题名并给出 DOI 和原文链接：[推文链接]
```

```text
使用 $wechat-paper-finder 识别这几张截图中的原论文，
能合法下载的正文也下载到我指定的文件夹。
```

只要求找链接时不会运行下载。默认处理主要推荐论文；可明确要求全部参考文献。下载器只处理正文 PDF；补充材料和机构访问由 agent 按请求调用相应工具。

## 可选解析与全文配置

| 功能 | 依赖／配置 |
|---|---|
| 文字、HTML、Crossref、arXiv 元数据 | Python 标准库；无需必填 API key |
| PDF 校验 | `pip install '.[pdf]'` 中的 `pypdf` |
| 图片截图 | agent 的 OCR/视觉能力；在原作者环境中使用 `ds-vision-skill` |
| PDF/Word 转 Markdown | MinerU 或配置好的文档解析工作流；在原作者环境中遵循先转 Markdown 的规则 |
| 跨学科开放全文查询 | `UNPAYWALL_EMAIL` 环境变量；使用你自己的联系邮箱 |
| 机构全文 | 用户授权的浏览器会话或下载工具；不是本 CLI 自带能力 |

Unpaywall 是可选来源；未设置邮箱时仍可检索论文并尝试 arXiv／Europe PMC 范围内的开放全文。不要使用虚构邮箱。

PowerShell：

```powershell
$env:UNPAYWALL_EMAIL = '你的联系邮箱'
```

macOS/Linux：

```bash
export UNPAYWALL_EMAIL='你的联系邮箱'
```

不要提交含个人邮箱的配置文件。OCR、MinerU、学术接口会把相应输入发送给所配置的服务；敏感材料可选择本地 OCR 或仅提交已提取的书目线索。程序不需要机构密码或导出的 Cookie。

## 命令行示例

如果输入是聊天里的文章分享卡片，agent 先用视觉工具读取可见线索，再生成找推文的检索计划：

```bash
python scripts/paper_finder.py discover --input examples/share-card.example.json --out work/discovery.json
```

示例线索是虚构的，仅演示结构。`discover` 生成检索词，由 agent 使用可用搜索／浏览器执行；它不声称已经找到推文。找到候选后：

```bash
python scripts/paper_finder.py extract --url 'https://mp.weixin.qq.com/s/实际推文' --discovery work/discovery.json --out work/intake.json
```

输出保留分享截图来源，并对照实际页面的标题和公众号身份。标题被截断、同名推文或公众号不一致时保留待确认状态。导师姓名和聊天时间不用于推断公众号或发布日期。完整流程见 [分享卡片找原文](references/share-card-discovery.md)。

多卡片示例使用 `examples/share-cards.example.json`。`discover` 为每张卡片分别生成查询；读取候选推文时用 `--card card_001` 指定来源。每条推文单独输出目录后可以汇总：

```bash
python scripts/paper_finder.py collect --manifests results/card_001/papers.json results/card_002/papers.json results/card_003/papers.json --out results/summary
```

`summary/report.md` 和 `collection.json` 保留每条推文的全部论文、各自核验状态及同一作品的多个来源；下载和 BibTeX 仍在各推文目录处理。不会把三张卡片强行转换成三篇论文。

先解析推文，保留正文、链接和图片清单：

```bash
python scripts/paper_finder.py extract --input examples/post.md --out work/intake.json
# 或：
python scripts/paper_finder.py extract --url 'https://mp.weixin.qq.com/s/你的推文' --out work/intake.json
```

agent 阅读 `work/intake.json`，合并同一论文的 DOI/题名线索，保留原文证据并设置 `role=main`。带有明确标识符的提取结果默认 `role=unknown`，需分类后才下载。自动发现的题名标签与 DOI 不会未经判断就合并。

仓库提供已整理的**人工演示输入**，可以直接测试查询：

```bash
python scripts/paper_finder.py resolve --input examples/intake.example.json --out results/demo --cache work/cache
```

检查 `results/demo/report.md` 和 `papers.json`。真实输入的中文译名或研究描述可能需要 agent 补充检索。已核验候选可用 `confirm` 记录来源和理由；这个命令只是记录审阅结论，不能替代审阅：

```bash
python scripts/paper_finder.py confirm --manifest results/demo/papers.json --paper paper_001 --candidate 1 --evidence-url 'https://真实的官方论文页面' --note '填写已经核对的原文线索及作者、题名或年份依据'
```

仅在结果有 `candidates` 时才使用 `confirm`。需要下载时：

```bash
python scripts/paper_finder.py download --manifest results/demo/papers.json --out results/demo --cache work/cache
```

`--out` 必须是 manifest 所在目录，以保持文件路径有效。可用 `--include-related` 纳入已明确分类的背景／延伸阅读；未知角色仍会跳过。`--max-mb` 默认 80，范围 1–300。

```text
results/demo/
├── report.md
├── papers.json
├── references.bib
└── PDFs/
```

JSON 保留完整证据和下载状态，BibTeX 只包含已核验记录。预印本标注为 preprint，不与正式发表版静默合并。PDF 校验偏保守：扫描件、出版社封面或特殊字体可能需要 OCR／人工确认。

## 当前边界

- 微信页面可能无法被普通 HTTP 请求读取。读取失败会明确报告，仍可用截图、复制正文或 agent 的浏览器继续。
- CLI 不会仅凭一段中文宣传标题自动确认论文；这一步需要 agent 的检索与判断。
- 找到 DOI 不等于拿到全文；开放索引可能缺少链接，出版商也可能限制自动下载。
- 元数据默认使用 Crossref/arXiv；其他来源、中文数据库和 PMID 可由 agent 检索并补充已核实记录。
- 不含付费墙绕过、自动机构登录、批量抓取公众号、定时监控或补充材料爬取。
- MIT 许可适用于本项目代码，不改变论文、推文和第三方内容的许可。

## 开发与验证

```bash
python -m pip install '.[dev]'
python -m unittest discover -s tests -v
```

测试使用合成文本、模拟 API 响应和程序生成的 PDF，离线验证题名冲突、重复 DOI、arXiv 版本、OA 条件、错误文件、已有文件和输出行为。网络演示是独立的烟雾测试，不属于 CI 的稳定性断言。GitHub Actions 配置为 Windows/Linux，Python 3.10/3.12/3.13。

```text
SKILL.md                    agent 工作流入口
agents/openai.yaml          技能显示信息
scripts/paper_finder.py      提取、检索、下载和导出 CLI
scripts/install_skill.py     安装技能有效载荷
references/                 匹配规则与输出格式
examples/                   不含私人信息的演示输入
tests/                      离线行为测试
```

## 上传到 GitHub

此目录可以作为独立仓库。先确认只暂存源代码、说明、测试和演示输入，真实推文、下载论文、个人配置与缓存留在仓库外。`.gitignore` 已排除常见研究输出和配置。

如已安装并登录 GitHub CLI，可在项目目录执行：

```bash
git init -b main
git add .
git commit -m 'Initial release: WeChat paper finder skill and CLI'
gh repo create wechat-paper-finder --public --source . --remote origin --push
```

若本机尚未设置 Git 提交身份，先配置你自己的 `user.name` 和 `user.email`。也可以在 GitHub 创建空仓库，再按页面给出的命令添加 remote 并推送。本项目不需要上传任何论文 PDF 或真实公众号全文。

## 数据源文档

- [Crossref REST API](https://github.com/Crossref/rest-api-doc)
- [arXiv API](https://info.arxiv.org/help/api/user-manual.html)
- [Europe PMC REST](https://europepmc.org/RestfulWebService)
- [Unpaywall API](https://unpaywall.org/products/api) / [版本与许可字段](https://unpaywall.org/data-format)

欢迎通过 issue 提供已脱敏的失败案例、预期结果和工具版本。请不要提交密钥、机构登录信息、私人推文或受限制的全文。
