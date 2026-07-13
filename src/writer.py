from pathlib import Path


OUTPUT_DIR = Path(r"D:\TCM-Library\09_Markdown")


def save_markdown(title: str, text: str) -> Path:
    """
    保存文本为 Markdown 文件
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    md_path = OUTPUT_DIR / f"{title}.md"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(text)

    return md_path