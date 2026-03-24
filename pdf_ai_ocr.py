"""
PDF AI识别工具 - 支持Ollama和LM Studio
开源项目: https://github.com/bbblq/pdf-ai-ocr
"""

import os
import base64
import requests
import fitz
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from flask import render_template_string, Response
import uuid
import json
import time
import threading
import re

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["OUTPUT_FOLDER"] = "outputs"

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

tasks = {}

# ============== 支持的提供商配置 ==============

PROVIDERS = {
    "lmstudio": {
        "name": "LM Studio",
        "default_url": "http://localhost:1234",
        "api_type": "openai_compatible",
    },
    "ollama": {
        "name": "Ollama",
        "default_url": "http://localhost:11434",
        "api_type": "ollama",
    },
}

DEFAULT_PROMPT = """你是专业的文档解析专家。请仔细识别这张图片中的所有内容，完整提取不要省略。
包括：书名、作者、简介、ISBN、定价、出版社信息、套书介绍等所有内容。
保持原有结构和格式输出。"""


# ============== API接口函数 ==============


def get_models_lmstudio(url):
    """获取LM Studio模型列表"""
    try:
        response = requests.get(f"{url}/v1/models", timeout=5)
        if response.status_code == 200:
            models = response.json().get("data", [])
            return [m["id"] for m in models]
    except:
        pass
    return []


def get_models_ollama(url):
    """获取Ollama模型列表"""
    try:
        response = requests.get(f"{url}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            return [m["name"] for m in models]
    except:
        pass
    return []


def get_all_models(provider, url):
    """获取指定提供商的模型列表"""
    if provider == "lmstudio":
        return get_models_lmstudio(url)
    elif provider == "ollama":
        return get_models_ollama(url)
    return []


def call_vl_model_lmstudio(url, model_name, image_base64, prompt, max_retries=3):
    """调用LM Studio的VL模型"""
    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{url}/v1/chat/completions",
                json={
                    "model": model_name,
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
                print(f"  LM Studio API错误: {response.status_code}")

        except requests.exceptions.Timeout:
            print(f"  请求超时")
        except Exception as e:
            print(f"  错误: {e}")

        if attempt < max_retries - 1:
            time.sleep(3)

    return "[错误: 无法从LM Studio获取响应]"


def call_vl_model_ollama(url, model_name, image_base64, prompt, max_retries=3):
    """调用Ollama的VL模型"""
    for attempt in range(max_retries):
        try:
            # Ollama使用不同的API格式
            response = requests.post(
                f"{url}/api/chat",
                json={
                    "model": model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image", "data": image_base64},
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                    "stream": False,
                    "options": {"num_predict": 4000, "temperature": 0.1},
                },
                timeout=180,
            )

            if response.status_code == 200:
                result = response.json()
                content = result.get("message", {}).get("content", "")
                if not content:
                    return "[错误: 模型未返回有效内容]"
                return content
            else:
                print(
                    f"  Ollama API错误: {response.status_code} - {response.text[:100]}"
                )

        except requests.exceptions.Timeout:
            print(f"  请求超时")
        except Exception as e:
            print(f"  错误: {e}")

        if attempt < max_retries - 1:
            time.sleep(3)

    return "[错误: 无法从Ollama获取响应]"


def call_vl_model(provider, url, model_name, image_base64, prompt, max_retries=3):
    """根据提供商调用对应的VL模型"""
    if provider == "lmstudio":
        return call_vl_model_lmstudio(
            url, model_name, image_base64, prompt, max_retries
        )
    elif provider == "ollama":
        return call_vl_model_ollama(url, model_name, image_base64, prompt, max_retries)
    else:
        return "[错误: 不支持的提供商]"


# ============== Flask路由 ==============


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/providers", methods=["GET"])
def get_providers():
    """获取支持的提供商列表"""
    return jsonify(
        {
            "success": True,
            "providers": [
                {"id": k, "name": v["name"], "default_url": v["default_url"]}
                for k, v in PROVIDERS.items()
            ],
        }
    )


@app.route("/api/models", methods=["GET"])
def get_models():
    """获取指定提供商的模型列表"""
    provider = request.args.get("provider", "lmstudio")
    url = request.args.get(
        "url", PROVIDERS.get(provider, {}).get("default_url", "http://localhost:1234")
    )

    models = get_all_models(provider, url)

    # 过滤视觉模型
    vision_keywords = [
        "vl",
        "vision",
        "llava",
        "qwen2-vl",
        "qwen3-vl",
        "llama3.2-vision",
    ]
    vision_models = [m for m in models if any(k in m.lower() for k in vision_keywords)]

    return jsonify(
        {
            "success": True if models else False,
            "provider": provider,
            "url": url,
            "all_models": models,
            "vision_models": vision_models if vision_models else models[:10],
        }
    )


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """上传PDF文件"""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "没有文件"})

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "文件名为空"})

    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "error": "只支持PDF文件"})

    task_id = str(uuid.uuid4())[:8]
    filename = f"{task_id}_{file.filename}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    try:
        doc = fitz.open(filepath)
        total_pages = len(doc)
        doc.close()
    except Exception as e:
        os.remove(filepath)
        return jsonify({"success": False, "error": f"PDF读取失败: {str(e)}"})

    tasks[task_id] = {
        "id": task_id,
        "filename": file.filename,
        "filepath": filepath,
        "total_pages": total_pages,
        "current_page": 0,
        "status": "ready",
        "results": {},
        "errors": [],
        "output_file": None,
        "provider": None,
        "model": None,
    }

    return jsonify(
        {
            "success": True,
            "task_id": task_id,
            "filename": file.filename,
            "total_pages": total_pages,
        }
    )


@app.route("/api/start", methods=["POST"])
def start_processing():
    """开始处理PDF"""
    data = request.json
    task_id = data.get("task_id")
    provider = data.get("provider", "lmstudio")
    model_name = data.get("model")
    url = data.get("url") or PROVIDERS.get(provider, {}).get("default_url")
    prompt = data.get("prompt", DEFAULT_PROMPT)

    if task_id not in tasks:
        return jsonify({"success": False, "error": "任务不存在"})

    if not model_name:
        return jsonify({"success": False, "error": "请选择模型"})

    task = tasks[task_id]
    task["provider"] = provider
    task["model"] = model_name
    task["url"] = url
    task["prompt"] = prompt

    if task["status"] == "running":
        return jsonify({"success": False, "error": "任务已在运行中"})

    thread = threading.Thread(
        target=process_pdf, args=(task_id, provider, url, model_name, prompt)
    )
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "message": "处理已开始"})


@app.route("/api/status/<task_id>")
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({"success": False, "error": "任务不存在"})

    task = tasks[task_id]
    return jsonify(
        {
            "success": True,
            "status": task["status"],
            "current_page": task["current_page"],
            "total_pages": task["total_pages"],
            "progress": round(task["current_page"] / task["total_pages"] * 100, 1)
            if task["total_pages"] > 0
            else 0,
            "errors": task["errors"][-5:],
        }
    )


@app.route("/api/stream/<task_id>")
def stream_status(task_id):
    def generate():
        last_page = -1
        while True:
            if task_id not in tasks:
                yield f"data: {json.dumps({'done': True, 'error': '任务不存在'})}\n\n"
                break

            task = tasks[task_id]

            if task["current_page"] != last_page:
                last_page = task["current_page"]
                yield f"data: {
                    json.dumps(
                        {
                            'current_page': task['current_page'],
                            'total_pages': task['total_pages'],
                            'progress': round(
                                task['current_page'] / task['total_pages'] * 100, 1
                            ),
                            'status': task['status'],
                        }
                    )
                }\n\n"

            if task["status"] in ["completed", "error"]:
                yield f"data: {json.dumps({'done': True, 'status': task['status']})}\n\n"
                break

            time.sleep(0.5)

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/download/<task_id>")
def download_result(task_id):
    if task_id not in tasks:
        return jsonify({"success": False, "error": "任务不存在"})

    task = tasks[task_id]
    if not task["output_file"] or not os.path.exists(task["output_file"]):
        return jsonify({"success": False, "error": "文件不存在"})

    return send_file(
        task["output_file"],
        as_attachment=True,
        download_name=f"{Path(task['filename']).stem}_全文.md",
    )


@app.route("/api/preview/<task_id>/<int:page>")
def preview_page(task_id, page):
    if task_id not in tasks:
        return jsonify({"success": False, "error": "任务不存在"})

    task = tasks[task_id]
    page_result = task["results"].get(page)

    if page_result is None:
        return jsonify({"success": False, "error": "该页未处理或无结果"})

    return jsonify({"success": True, "page": page, "content": page_result})


# ============== 处理函数 ==============


def extract_page_as_image(pdf_path, page_num, scale=1.5):
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def save_results_to_markdown(task):
    output_file = os.path.join(
        app.config["OUTPUT_FOLDER"],
        f"{task['id']}_{Path(task['filename']).stem}_全文.md",
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# {Path(task['filename']).stem}\n\n")
        f.write(f"**总页数**: {task['total_pages']}\n")
        f.write(f"**模型**: {task.get('model', 'N/A')}\n")
        f.write(f"**提供商**: {task.get('provider', 'N/A')}\n\n")
        f.write("---\n\n")

        for page_num in sorted(task["results"].keys()):
            f.write(f"## 第 {page_num + 1} 页\n\n")
            f.write(task["results"][page_num])
            f.write("\n\n---\n\n")

    return output_file


def process_pdf(task_id, provider, url, model_name, prompt):
    task = tasks[task_id]
    task["status"] = "running"

    try:
        for i in range(task["total_pages"]):
            task["current_page"] = i

            try:
                img_bytes = extract_page_as_image(task["filepath"], i)
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                result = call_vl_model(provider, url, model_name, img_base64, prompt)
                task["results"][i] = result
            except Exception as e:
                task["errors"].append(f"第{i + 1}页: {str(e)}")
                task["results"][i] = f"[Error: {e}]"

            time.sleep(0.3)

        task["output_file"] = save_results_to_markdown(task)
        task["status"] = "completed"

    except Exception as e:
        task["status"] = "error"
        task["errors"].append(str(e))


# ============== HTML模板 ==============

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PDF AI识别工具 - 多后端支持</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { text-align: center; color: #333; margin-bottom: 30px; }
        h1 .subtitle { font-size: 14px; color: #888; font-weight: normal; }
        
        .card { background: white; border-radius: 12px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .card h2 { color: #666; font-size: 16px; margin-bottom: 16px; border-bottom: 1px solid #eee; padding-bottom: 10px; }
        
        .form-group { margin-bottom: 16px; }
        .form-group label { display: block; margin-bottom: 6px; color: #555; font-weight: 500; }
        .form-group input[type="text"], .form-group select, .form-group textarea { width: 100%; padding: 10px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
        .form-group textarea { height: 100px; resize: vertical; font-family: inherit; }
        .form-group small { color: #888; margin-top: 4px; display: block; }
        
        .btn { display: inline-block; padding: 12px 24px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; transition: all 0.2s; }
        .btn-primary { background: #4a90d9; color: white; }
        .btn-primary:hover { background: #357abd; }
        .btn-primary:disabled { background: #ccc; cursor: not-allowed; }
        .btn-success { background: #5cb85c; color: white; }
        .btn-success:hover { background: #4cae4c; }
        
        .upload-area { border: 2px dashed #ddd; border-radius: 8px; padding: 40px; text-align: center; cursor: pointer; transition: all 0.2s; }
        .upload-area:hover { border-color: #4a90d9; background: #f8f8f8; }
        .upload-area input { display: none; }
        .upload-area .icon { font-size: 48px; margin-bottom: 10px; }
        .upload-area .text { color: #666; }
        .upload-area .text strong { color: #4a90d9; }
        
        .file-info { background: #f8f8f8; padding: 16px; border-radius: 6px; margin-top: 16px; display: none; }
        .file-info.show { display: block; }
        .file-info .name { font-weight: 500; color: #333; }
        .file-info .pages { color: #4a90d9; font-size: 13px; }
        .file-info .size { color: #888; font-size: 13px; margin-top: 4px; }
        
        .progress-container { margin-top: 20px; display: none; }
        .progress-container.show { display: block; }
        .progress-bar { height: 24px; background: #e0e0e0; border-radius: 12px; overflow: hidden; }
        .progress-bar .fill { height: 100%; background: linear-gradient(90deg, #4a90d9, #5cb85c); transition: width 0.3s; width: 0%; }
        .progress-text { text-align: center; margin-top: 8px; color: #666; font-size: 14px; }
        
        .status { padding: 12px 16px; border-radius: 6px; margin-top: 16px; display: none; }
        .status.show { display: block; }
        .status.running { background: #e3f2fd; color: #1976d2; }
        .status.completed { background: #e8f5e9; color: #388e3c; }
        .status.error { background: #ffebee; color: #c62828; }
        
        .preview-section { margin-top: 20px; display: none; }
        .preview-section.show { display: block; }
        .preview-content { background: #f8f8f8; padding: 16px; border-radius: 6px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; font-size: 13px; line-height: 1.6; }
        
        .actions { display: flex; gap: 12px; margin-top: 16px; }
        
        .model-list { max-height: 200px; overflow-y: auto; border: 1px solid #ddd; border-radius: 6px; padding: 8px; }
        .model-item { padding: 8px 12px; border-radius: 4px; cursor: pointer; transition: background 0.2s; }
        .model-item:hover { background: #f0f0f0; }
        .model-item.selected { background: #e3f2fd; color: #1976d2; }
        
        .provider-tabs { display: flex; gap: 8px; margin-bottom: 16px; }
        .provider-tab { padding: 8px 16px; border: 1px solid #ddd; border-radius: 6px; cursor: pointer; background: white; }
        .provider-tab.active { background: #4a90d9; color: white; border-color: #4a90d9; }
        
        .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; background: #e0e0e0; color: #666; margin-left: 8px; }
        .badge.lmstudio { background: #ff6b6b; color: white; }
        .badge.ollama { background: #4ecdc4; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📄 PDF AI识别工具 <span class="subtitle">- 支持Ollama/LM Studio</span></h1>
        
        <!-- 提供商选择 -->
        <div class="card">
            <h2>⚙️ 选择AI提供商</h2>
            <div class="provider-tabs">
                <div class="provider-tab active" onclick="selectProvider('lmstudio')">LM Studio <span class="badge lmstudio">推荐</span></div>
                <div class="provider-tab" onclick="selectProvider('ollama')">Ollama</div>
            </div>
            
            <div class="form-group">
                <label>API地址</label>
                <input type="text" id="apiUrl" value="http://localhost:1234" placeholder="http://localhost:1234">
            </div>
            <div class="form-group">
                <label>选择模型</label>
                <div style="display: flex; gap: 8px; margin-bottom: 8px;">
                    <button class="btn btn-primary" onclick="loadModels()" style="padding: 8px 16px;">🔄 刷新模型列表</button>
                </div>
                <div class="model-list" id="modelList">
                    <div class="model-item">点击"刷新模型列表"加载可用模型</div>
                </div>
                <input type="hidden" id="selectedModel" value="">
            </div>
        </div>
        
        <!-- 文件上传 -->
        <div class="card">
            <h2>📤 上传PDF文件</h2>
            <div class="upload-area" onclick="document.getElementById('fileInput').click()">
                <input type="file" id="fileInput" accept=".pdf" onchange="handleFileSelect(event)">
                <div class="icon">📄</div>
                <div class="text">点击或拖拽PDF文件到这里<br><strong>支持最多500MB的PDF</strong></div>
            </div>
            <div class="file-info" id="fileInfo">
                <div class="name" id="fileName"></div>
                <div class="pages" id="filePages"></div>
                <div class="size" id="fileSize"></div>
            </div>
        </div>
        
        <!-- 提示词 -->
        <div class="card">
            <h2>💬 识别提示词（可选）</h2>
            <div class="form-group">
                <textarea id="prompt">你是专业的文档解析专家。请仔细识别这张图片中的所有内容，完整提取不要省略。包括：书名、作者、简介、ISBN、定价、出版社信息、套书介绍等所有内容。保持原有结构和格式输出。</textarea>
                <small>默认已填写通用提示词，可根据需要修改</small>
            </div>
        </div>
        
        <!-- 操作按钮 -->
        <div class="card">
            <div class="actions">
                <button class="btn btn-primary" id="startBtn" onclick="startProcessing()" disabled>🚀 开始识别</button>
                <button class="btn btn-success" id="downloadBtn" onclick="downloadResult()" style="display: none;">📥 下载结果</button>
            </div>
            
            <div class="progress-container" id="progressContainer">
                <div class="progress-bar"><div class="fill" id="progressFill"></div></div>
                <div class="progress-text" id="progressText">准备中...</div>
            </div>
            
            <div class="status" id="statusBox"></div>
        </div>
        
        <!-- 结果预览 -->
        <div class="card preview-section" id="previewSection">
            <h2>👁️ 结果预览</h2>
            <div style="margin-bottom: 12px;">
                <small>页码: <span id="previewPageNum">1</span></small>
                <button class="btn btn-primary" onclick="prevPage()" style="padding: 6px 12px; margin-left: 8px;">上一页</button>
                <button class="btn btn-primary" onclick="nextPage()" style="padding: 6px 12px;">下一页</button>
            </div>
            <div class="preview-content" id="previewContent">等待处理完成...</div>
        </div>
    </div>
    
    <script>
        let currentTaskId = null;
        let currentProvider = 'lmstudio';
        let eventSource = null;
        let lastPreviewPage = 0;
        
        function selectProvider(provider) {
            currentProvider = provider;
            document.querySelectorAll('.provider-tab').forEach(tab => tab.classList.remove('active'));
            event.target.closest('.provider-tab').classList.add('active');
            
            // 更新默认URL
            if (provider === 'lmstudio') {
                document.getElementById('apiUrl').value = 'http://localhost:1234';
            } else {
                document.getElementById('apiUrl').value = 'http://localhost:11434';
            }
            loadModels();
        }
        
        async function loadModels() {
            const url = document.getElementById('apiUrl').value;
            const modelList = document.getElementById('modelList');
            modelList.innerHTML = '<div class="model-item">加载中...</div>';
            
            try {
                const resp = await fetch(`/api/models?provider=${currentProvider}&url=${encodeURIComponent(url)}`);
                const data = await resp.json();
                
                if (data.success && data.all_models.length > 0) {
                    const models = data.vision_models || data.all_models;
                    modelList.innerHTML = models.map(m => 
                        `<div class="model-item" onclick="selectModel(this, '${m.replace(/'/g, "\\'")}')">${m}</div>`
                    ).join('');
                } else {
                    modelList.innerHTML = `<div class="model-item">未检测到模型，请确保${currentProvider === 'lmstudio' ? 'LM Studio' : 'Ollama'}正在运行</div>`;
                }
            } catch (e) {
                modelList.innerHTML = `<div class="model-item">连接失败: ${e.message}</div>`;
            }
        }
        
        function selectModel(el, model) {
            document.querySelectorAll('.model-item').forEach(item => item.classList.remove('selected'));
            el.classList.add('selected');
            document.getElementById('selectedModel').value = model;
        }
        
        function handleFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;
            
            const formData = new FormData();
            formData.append('file', file);
            
            fetch('/api/upload', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        currentTaskId = data.task_id;
                        document.getElementById('fileName').textContent = data.filename;
                        document.getElementById('filePages').textContent = `共 ${data.total_pages} 页`;
                        document.getElementById('fileSize').textContent = formatSize(file.size);
                        document.getElementById('fileInfo').classList.add('show');
                        document.getElementById('startBtn').disabled = false;
                    } else {
                        alert('上传失败: ' + data.error);
                    }
                });
        }
        
        function formatSize(bytes) {
            if (bytes > 1024*1024) return (bytes/1024/1024).toFixed(1) + ' MB';
            return (bytes/1024).toFixed(1) + ' KB';
        }
        
        function startProcessing() {
            if (!currentTaskId) return;
            
            const model = document.getElementById('selectedModel').value;
            const url = document.getElementById('apiUrl').value;
            const prompt = document.getElementById('prompt').value;
            
            if (!model) {
                alert('请先选择一个模型');
                return;
            }
            
            fetch('/api/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    task_id: currentTaskId,
                    provider: currentProvider,
                    model: model,
                    url: url,
                    prompt: prompt
                })
            }).then(r => r.json()).then(data => {
                if (data.success) {
                    showProgress();
                } else {
                    alert('启动失败: ' + data.error);
                }
            });
        }
        
        function showProgress() {
            document.getElementById('progressContainer').classList.add('show');
            document.getElementById('startBtn').disabled = true;
            document.getElementById('statusBox').className = 'status running show';
            document.getElementById('statusBox').textContent = '处理中...';
            
            if (eventSource) eventSource.close();
            eventSource = new EventSource(`/api/stream/${currentTaskId}`);
            
            eventSource.onmessage = function(e) {
                const data = JSON.parse(e.data);
                updateProgress(data);
            };
            
            eventSource.onerror = function() {
                eventSource.close();
                checkFinalStatus();
            };
        }
        
        function updateProgress(data) {
            document.getElementById('progressFill').style.width = data.progress + '%';
            document.getElementById('progressText').textContent = `第 ${data.current_page} / ${data.total_pages} 页 (${data.progress}%)`;
            
            if (data.done) {
                eventSource.close();
                checkFinalStatus();
            }
        }
        
        function checkFinalStatus() {
            fetch(`/api/status/${currentTaskId}`)
                .then(r => r.json())
                .then(data => {
                    const statusBox = document.getElementById('statusBox');
                    
                    if (data.status === 'completed') {
                        statusBox.className = 'status completed show';
                        statusBox.textContent = '处理完成！';
                        document.getElementById('downloadBtn').style.display = 'inline-block';
                        document.getElementById('previewSection').classList.add('show');
                        loadPreview(0);
                    } else if (data.status === 'error') {
                        statusBox.className = 'status error show';
                        statusBox.textContent = '处理出错: ' + (data.errors || []).join(', ');
                    } else {
                        statusBox.className = 'status running show';
                        statusBox.textContent = `处理中... ${data.progress}%`;
                    }
                });
        }
        
        function loadPreview(page) {
            lastPreviewPage = page;
            document.getElementById('previewPageNum').textContent = page + 1;
            
            fetch(`/api/preview/${currentTaskId}/${page}`)
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('previewContent').textContent = data.content;
                    } else {
                        document.getElementById('previewContent').textContent = '无内容';
                    }
                });
        }
        
        function prevPage() { if (lastPreviewPage > 0) loadPreview(lastPreviewPage - 1); }
        function nextPage() { loadPreview(lastPreviewPage + 1); }
        function downloadResult() { window.location.href = `/api/download/${currentTaskId}`; }
        
        window.onload = loadModels;
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    print("=" * 60)
    print("PDF AI识别工具 - 多后端支持版")
    print()
    print("支持的提供商:")
    print("  - LM Studio (默认: http://localhost:1234)")
    print("  - Ollama (默认: http://localhost:11434)")
    print()
    print("请打开浏览器访问: http://localhost:5000")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=False)
