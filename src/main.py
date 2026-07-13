from pathlib import Path

from scanner import scan_pdfs
from parser import extract_text, PDF_FILE
from writer import save_markdown


def process_pdf(pdf_path: Path):

    print("\n" + "=" * 60)
    print(f"开始处理：{pdf_path.name}")
    print("=" * 60)

    text = extract_text(pdf_path)

    save_path = save_markdown(pdf_path.stem, text)

    print(f"\nMarkdown 已保存：")
    print(save_path)


def main():

    pdfs = scan_pdfs()

    print("=" * 60)
    print(f"发现PDF：{len(pdfs)}")
    print("=" * 60)

    if len(pdfs) == 0:
        return

    # V0.1 先处理第一篇
    process_pdf(pdfs[0])

    print("\n")
    print("=" * 60)
    print("全部完成")
    print("=" * 60)


if __name__ == "__main__":
    main()