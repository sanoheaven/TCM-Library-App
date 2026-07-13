from pathlib import Path
import pdfplumber

# ===== 测试PDF（当前固定使用这一篇）=====
PDF_FILE = Path(
    r"D:\TCM-Library\05_Journal\2024_王瑞_面向智能诊断探讨中医证素知识框架体系的构建.pdf"
)


def extract_text(pdf_path: Path) -> str:
    """读取PDF并返回全部文字"""

    text_list = []

    with pdfplumber.open(pdf_path) as pdf:
        print("=" * 60)
        print(f"文件：{pdf_path.name}")
        print(f"页数：{len(pdf.pages)}")
        print("=" * 60)

        for i, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text()

            if page_text:
                text_list.append(page_text)
            else:
                print(f"第 {i} 页没有提取到文字。")

    return "\n".join(text_list)


def main():

    if not PDF_FILE.exists():
        print("找不到PDF：")
        print(PDF_FILE)
        return

    text = extract_text(PDF_FILE)

    print("\n")
    print("=" * 60)
    print("文字总长度：", len(text))
    print("=" * 60)

    print("\n前500个字符：\n")

    print(text[:500])

    print("\n")
    print("=" * 60)
    print("PDF解析成功！")
    print("=" * 60)


if __name__ == "__main__":
    main()