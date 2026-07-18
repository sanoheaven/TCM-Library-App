# TCM Library App

第一轮只生成可人工复核的 PDF 转换包，不批量入库、不自动提炼知识。

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
