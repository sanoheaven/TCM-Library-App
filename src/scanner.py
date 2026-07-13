from pathlib import Path

LIBRARY = Path(r"D:\TCM-Library")

SEARCH_DIRS = [
    "03_Books",
    "04_Dissertation",
    "05_Journal",
]

def scan_pdfs():
    pdfs = []

    for folder in SEARCH_DIRS:
        path = LIBRARY / folder

        if not path.exists():
            continue

        pdfs.extend(path.rglob("*.pdf"))

    return pdfs


if __name__ == "__main__":

    pdfs = scan_pdfs()

    print("=" * 50)
    print(f"发现PDF：{len(pdfs)}")
    print("=" * 50)

    for pdf in pdfs:
        print(pdf.name)