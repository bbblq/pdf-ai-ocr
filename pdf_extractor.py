"""
PDF转Markdown工具 - 使用PyMuPDF直接提取文字层
适用于有文字层的PDF，速度快但无法处理纯图片页
"""

import fitz
import os
from pathlib import Path


def extract_pdf_to_markdown(pdf_path, output_path=None, start_page=0, end_page=None):
    """
    从PDF提取文字内容，按页保存为Markdown

    Args:
        pdf_path: PDF文件路径
        output_path: 输出文件路径（不含扩展名），默认与PDF同名
        start_page: 起始页（0索引）
        end_page: 结束页（不包含），None表示到最后一页
    """
    pdf_path = Path(pdf_path)
    if output_path is None:
        output_path = pdf_path.with_suffix("")
    else:
        output_path = Path(output_path)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    if end_page is None:
        end_page = total_pages

    print(f"PDF总页数: {total_pages}")
    print(f"处理范围: 第{start_page + 1}页 到 第{end_page}页")

    all_content = []

    for page_num in range(start_page, min(end_page, total_pages)):
        page = doc[page_num]
        text = page.get_text()
        images = page.get_images()

        # 检测这页的主要内容
        has_text = len(text.strip()) > 50  # 超过50字符认为是有效文字
        has_images = len(images) > 0

        page_content = f"\n\n## 第 {page_num + 1} 页\n\n"

        if has_text:
            # 清理文本，保留基本格式
            lines = text.split("\n")
            cleaned_lines = []
            for line in lines:
                line = line.strip()
                if line:
                    cleaned_lines.append(line)
            page_content += "\n".join(cleaned_lines)
        else:
            page_content += (
                f"[此页无文字层，包含 {len(images)} 张图片，需要VL模型处理]\n"
            )

        all_content.append(page_content)

        if (page_num + 1) % 50 == 0:
            print(f"已处理 {page_num + 1} / {total_pages} 页")

    doc.close()

    # 保存为单个Markdown文件
    output_file = output_path.with_suffix(".md")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# {pdf_path.stem}\n\n")
        f.write(f"总共 {total_pages} 页\n\n")
        f.write("\n".join(all_content))

    print(f"\n完成! 输出文件: {output_file}")
    return output_file


def extract_page_as_image(pdf_path, page_num, scale=2.0):
    """
    将PDF指定页转换为图片（用于VL模型处理）

    Args:
        pdf_path: PDF路径
        page_num: 页码（0索引）
        scale: 缩放倍数
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, format="png")
    doc.close()
    return pix.tobytes("png")


if __name__ == "__main__":
    import sys

    pdf_file = "2024订货会书目.pdf"

    print(f"开始提取: {pdf_file}")
    output = extract_pdf_to_markdown(pdf_file)
    print(f"\n初步提取完成，请查看 {output} 的内容质量")
    print("如果有些页是纯图片没有文字，需要用VL模型单独处理这些页")
