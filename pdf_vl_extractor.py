"""
PDF逐页AI识别工具
将PDF每页转为图片，使用VL模型识别内容并保存
"""

import base64
import requests
import fitz
from pathlib import Path
import time

# ============== 配置 ==============
LM_STUDIO_URL = "http://192.168.21.44:1234"
MODEL_NAME = "qwen3-vl-8b-instruct"

SYSTEM_PROMPT = """你是专业的文档解析专家。请仔细识别这张图片中的所有内容，完整提取不要省略。
包括：书名、作者、简介、ISBN、定价、出版社信息、套书介绍等所有内容。
保持原有结构和格式输出。"""

# ============== 工具函数 ==============


def encode_image_to_base64(img_bytes):
    return base64.b64encode(img_bytes).decode("utf-8")


def extract_page_as_image(pdf_path, page_num, scale=1.5):
    """将PDF指定页转换为PNG图片"""
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def call_vl_model(image_base64, prompt=SYSTEM_PROMPT, max_retries=3):
    """调用VL模型识别图片"""
    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{LM_STUDIO_URL}/v1/chat/completions",
                json={
                    "model": MODEL_NAME,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{image_base64}"
                                    },
                                },
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                    "max_tokens": 4000,
                    "temperature": 0.1,
                },
                timeout=180,
            )

            if response.status_code == 200:
                result = response.json()
                msg = result["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                if not content:
                    return "[错误: 模型未返回有效内容]"
                return content
            elif "failed to process image" in response.text:
                return f"[错误: 图片处理失败]"
            else:
                print(
                    f"  API错误 ({attempt + 1}/{max_retries}): {response.status_code}"
                )

        except requests.exceptions.Timeout:
            print(f"  请求超时 ({attempt + 1}/{max_retries})")
        except Exception as e:
            print(f"  错误 ({attempt + 1}/{max_retries}): {e}")

        if attempt < max_retries - 1:
            time.sleep(3)

    return "[错误: 无法从VL模型获取响应]"


def save_results_to_markdown(pdf_path, output_path, results):
    """保存结果到Markdown文件"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# {Path(pdf_path).stem}\n\n")
        f.write(f"**总页数**: {len(results)}\n\n")
        f.write("---\n\n")

        for page_num in sorted(results.keys()):
            f.write(f"## 第 {page_num + 1} 页\n\n")
            f.write(results[page_num])
            f.write("\n\n---\n\n")


# ============== 主程序 ==============

if __name__ == "__main__":
    pdf_file = "2024订货会书目.pdf"
    output_file = "2024订货会书目_全文.md"

    print("=" * 60)
    print("PDF逐页AI识别工具")
    print(f"输入: {pdf_file}")
    print(f"输出: {output_file}")
    print("=" * 60)

    # 获取PDF总页数
    doc = fitz.open(pdf_file)
    total_pages = len(doc)
    doc.close()

    print(f"PDF总页数: {total_pages}")
    print(f"开始处理...\n")

    all_results = {}
    errors = []

    for i in range(total_pages):
        page_num = i
        print(f"[{i + 1}/{total_pages}] Page {page_num + 1}...", end=" ", flush=True)

        try:
            img_bytes = extract_page_as_image(pdf_file, page_num)
            img_base64 = encode_image_to_base64(img_bytes)
            result = call_vl_model(img_base64)
            all_results[page_num] = result
            print(f"OK ({len(result)} chars)")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(page_num)
            all_results[page_num] = f"[Error: {e}]"

        # 每10页保存一次进度
        if (i + 1) % 10 == 0:
            save_results_to_markdown(pdf_file, output_file, all_results)
            print(f">>> Saved ({i + 1}/{total_pages})")

        time.sleep(0.3)

    # 最终保存
    save_results_to_markdown(pdf_file, output_file, all_results)

    print()
    print("=" * 60)
    print(f"完成! 输出文件: {output_file}")
    print(f"成功: {len(all_results) - len(errors)} 页")
    if errors:
        print(f"失败: {[p + 1 for p in errors]}")
    print("=" * 60)
