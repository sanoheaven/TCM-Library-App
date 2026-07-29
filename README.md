# TCM Library App

第一轮只生成可人工复核的 PDF 转换包，不批量入库、不自动提炼知识。

## OCR 风险规则回归测试

`src/risk_rules.py` 只输出待人工核对的风险标记，不会自动改写 OCR 文本。风险标记用于安排人工核图顺序，不能替代逐页、全量人工核对；未被标记的区域也不得默认正确。

`tests/test_risk_rules.py` 以《中医内科学评讲》“感冒”章节的 10 条已核定 OCR 差异作为回归集。100% 召回只表示已知错误没有回归漏检，不代表规则可以覆盖未知错误，也不授权跳过非风险区域。

使用 bundled Python 或已安装依赖运行：

```powershell
python src/main.py --source-type DIS --dry-run
python src/main.py --pdf "D:\TCM-Library\02_PDF\一篇资料.pdf" --source-type DIS
python src/main.py --pdf "D:\TCM-Library\02_PDF\已确认的另一版本.pdf" --source-type JRN --confirm-near-duplicate "保留高清扫描版，供舌图复核"
python -m unittest discover -s tests
```

默认输入目录为 `D:\TCM-Library\02_PDF`。每次均须显式填写资料载体类型（例如 `DIS`、`JRN`）；实际转换默认要求传入一篇明确的 `--pdf` 路径。目录批处理必须先 `--dry-run`，再显式使用 `--batch`。

转换前会在 `02_PDF` 与 `03`—`07` 原始资料目录中按文件大小和 SHA-256 查找同内容 PDF；发现完全重复时自动跳过，不生成新的审阅包。相同作者、年份和近似标题的不同版本会被标为 `NEEDS_DUPLICATE_REVIEW`，必须由人工以 `--confirm-near-duplicate` 留下决定理由后才可转换。`PAT` 为专利的正式资料类型代码。输出位于：

- `D:\TCM-Library\09_Markdown\<类别>\<文献ID>\`
- `D:\TCM-Library\11_Metadata\<文献ID>.manifest.json`

生成结果一律为 `needs_review`。高风险表格、舌象图和引文映射经人工复核前，不得进入 Ingest。

## 模型辅助 OCR 结构化流程

模型不得从整章 OCR 自由生成最终 Markdown。当前流程为：

1. 冻结 PDF 页码、OCR 行号、原始文字和坐标。
2. 模型逐行输出 JSON 角色映射；每条原文逐字符不变，评讲使用稳定 `block_id`。
3. 程序检查行数、顺序、页码、行号、原文、唯一角色、评讲跨页和标签配对。
4. 只有硬校验通过后，程序才渲染 Markdown。
5. 人工逐页核图，核对标题、评讲边界、图示、附方、方药和生僻字。
6. 每次运行后查找共性问题；确认的新问题必须同时形成规则、检测和最小回归样例。
7. 更新规则后重跑当前章节及完整回归测试。

模型输出的“100%覆盖”或“全部通过”不是审计证据。覆盖率、重复率和标签配对等统计必须由程序根据冻结输入重新计算。

## 流程文档

- [实施计划](docs/ocr/implementation-plan.md)
- [结构保真规则](docs/ocr/structure-fidelity-rules.md)
- [共性问题与验证方案](docs/ocr/common-issues-and-verification.md)

章节状态、未核定映射和审计备份属于本地资料资产，不纳入仓库。
## T5 稳定版结构预处理

使用 `scripts/preprocess_structure_candidates.py --manifest <本地章节清单.json> --mapping-dir <章节映射目录>` 检查父子项边界、拆行标题、重复页眉和评讲续句。仓库仅提供 `config/ocr-chapter-manifest.example.json`；实际书目清单和 resolution 留在本地资料区。程序不改 OCR、不自动决定最终角色；传入 `--fail-on-errors` 时，发现映射边界错误会以非零状态退出。

关键 review 还必须传入 `--resolutions <resolution.json>`；resolution 逐项记录规则、页码、来源行、处理结论和页图证据。子项起页会自动读取前一页上下文，可重复指定 `--mapping-dir` 读取父项与子项的独立映射。manifest 的 `title_aliases`／`header_aliases` 仅在登记页段生效，不是全局 OCR 改写。
