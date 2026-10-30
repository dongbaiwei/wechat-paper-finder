# 精简卡片：默认工作流

先按 SKILL.md 识别输入和核验论文。多个 DOI 可逐个 prepare；多个链接／截图按卡片分别提取、resolve，再合并。脚本不直接理解截图；依照用户配置的 OCR/视觉流程获取线索。每份清单保留输入来源以及主推论文，不把背景引用自动扩展为主推论文。

```text
python scripts/paper_finder.py prepare --doi "10.…" --profile basic --out results/paper --cache work/http-cache --jif-cache work/jif-cache
python scripts/paper_finder.py prepare --manifest results/paper/papers.json --profile basic --out results/paper --details work/reviewed-details.json --jif-cache work/jif-cache
python scripts/paper_finder.py collect --manifests results/card1/papers.json results/card2/papers.json --profile basic --out results/batch --jif-cache work/jif-cache
```

每次输出 `basic-cards.md`、`basic-cards.csv`、`basic-cards.json`。prepare 另保留 `papers.json` 和可补充的 `research-details.json`。basic 文件是本次交付；目录中可能存在之前生成的完整报告，不应把旧文件当本次输出。

单篇在聊天中展示卡片，多篇展示总表及逐篇卡片，并链接三种导出。相同已核验 DOI／版本合并为一张卡片，保留所有 origins；候选不去重，预印本与正式版不合并。机构保留作者对应关系，不只罗列机构名。缺失字段及失败输入保留，不等所有字段齐全才交付。

## 补充字段

使用生成的 research-details.json；每条 id、doi/arxiv_id 必须对应原清单。basic 模式只需填 bibliography 和 impact_factor，其余模块不必填写：

```json
{
  "schema_version": 1,
  "papers": [{
    "id": "paper_001",
    "doi": "10.1234/example",
    "research": {
      "bibliography": {
        "author_details": [{"name": "Example Author", "affiliations": ["Example University"]}],
        "evidence": [{"source_url": "https://publisher.example/article", "location": "Author information"}]
      },
      "impact_factor": {
        "value": 1.2,
        "metric_year": 2025,
        "journal": "Example Journal",
        "source_url": "https://publisher.example/metrics",
        "checked_at": "2026-10-30"
      }
    }
  }]
}
```

上述仅为格式示例，不能用于真实指标。JIF 优先使用 JCR 或期刊出版社官方指标页面；记录指标年份而不是查询年份。无法取得来源时 value 留空，预印本没有自身期刊 JIF。

## JIF 缓存

`--jif-cache` 默认为当前工作目录的 `work/jif-cache`。跨批次需要使用同一目录。按期刊标识（可用 ISSN 时优先，否则规范化期刊名）和指标年份保存；保留源链接与原始 checked_at，不因读取刷新时间。

prepare 首次生成的卡片会显示缓存指标及 `fresh`／`stale`。没有缓存或超过30天时，agent 查询一次官方来源；成功后通过 details 更新。失败时在 impact_factor 添加 `refresh_error` 描述实际原因，再生成卡片。脚本本身不会查询指标网站，也不会把未尝试更新误称为更新失败。同批次先收集已有指标，再按期刊复用。损坏缓存会跳过并提示。

## 扩展功能

只有用户明确要求中文摘要、图谱、复现清单或完整研究准备时，才读 research-preparation.md 并使用 `--profile full`；原有下载流程保持按需。图谱检索仍使用正式论文全称。
