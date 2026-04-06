import pdfplumber

pdf_path = "/Users/chiauhung/Downloads/Ralph Kimball, Margy Ross - The Data Warehouse Toolkit_ The Definitive Guide to Dimensional Modeling-Wiley (2013).pdf"

start_page = 126  # 注意：0-based
end_page = 127

texts = []

with pdfplumber.open(pdf_path) as pdf:
    for i in range(start_page, end_page):
        page = pdf.pages[i]
        text = page.extract_text()
        texts.append(text)

result = "\n\n".join(texts)
print(result)
