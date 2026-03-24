"""
PDF逐页AI识别工具 - Web界面版
上传PDF，选择模型，实时查看处理进度
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

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["OUTPUT_FOLDER"] = "outputs"

# 确保目录存在
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["OUTPUT_FOLDER"], exist_ok=True)

# 全局任务状态
tasks = {}


@app.route("/")
def index():
    """主页"""
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/models", methods=["GET"])
def get_models():
    """获取可用的VL模型列表"""
    lm_url = request.args.get("lm_url", "http://192.168.21.44:1234")

    try:
        response = requests.get(f"{lm_url}/v1/models", timeout=5)
        if response.status_code == 200:
            models = response.json().get("data", [])
            # 过滤可能的视觉模型（通常名字含vl或vision）
            all_models = [m["id"] for m in models]
            vision_models = [
                m for m in all_models if "vl" in m.lower() or "vision" in m.lower()
            ]
            return jsonify(
                {
                    "success": True,
                    "all_models": all_models,
                    "vision_models": vision_models if vision_models else all_models[:5],
                }
            )
        return jsonify({"success": False, "error": "无法连接LM Studio"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


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

    # 保存文件
    task_id = str(uuid.uuid4())[:8]
    filename = f"{task_id}_{file.filename}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    # 获取PDF信息
    try:
        doc = fitz.open(filepath)
        total_pages = len(doc)
        doc.close()
    except Exception as e:
        os.remove(filepath)
        return jsonify({"success": False, "error": f"PDF读取失败: {str(e)}"})

    # 初始化任务状态
    tasks[task_id] = {
        "id": task_id,
        "filename": file.filename,
        "filepath": filepath,
        "total_pages": total_pages,
        "current_page": 0,
        "status": "ready",  # ready, running, completed, error
        "results": {},
        "errors": [],
        "output_file": None,
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
    model_name = data.get("model")
    lm_url = data.get("lm_url", "http://192.168.21.44:1234")
    prompt = data.get("prompt", DEFAULT_PROMPT)

    if task_id not in tasks:
        return jsonify({"success": False, "error": "任务不存在"})

    task = tasks[task_id]
    if task["status"] == "running":
        return jsonify({"success": False, "error": "任务已在运行中"})

    # 启动处理线程
    thread = threading.Thread(
        target=process_pdf, args=(task_id, model_name, lm_url, prompt)
    )
    thread.daemon = True
    thread.start()

    return jsonify({"success": True, "message": "处理已开始"})


@app.route("/api/status/<task_id>")
def get_status(task_id):
    """获取任务状态"""
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
            "errors": task["errors"][-5:],  # 最近5个错误
        }
    )


@app.route("/api/stream/<task_id>")
def stream_status(task_id):
    """SSE流式推送进度"""

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
    """下载结果文件"""
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
    """预览某一页的识别结果"""
    if task_id not in tasks:
        return jsonify({"success": False, "error": "任务不存在"})

    task = tasks[task_id]
    page_result = task["results"].get(page)

    if page_result is None:
        return jsonify({"success": False, "error": "该页未处理或无结果"})

    return jsonify({"success": True, "page": page, "content": page_result})


# ============== 处理函数 ==============

DEFAULT_PROMPT = """你是专业的文档解析专家。请仔细识别这张图片中的所有内容，完整提取不要省略。
包括：书名、作者、简介、ISBN、定价、出版社信息、套书介绍等所有内容。
保持原有结构和格式输出。"""


def extract_page_as_image(pdf_path, page_num, scale=1.5):
    """将PDF指定页转换为PNG图片"""
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def call_vl_model(lm_url, model_name, image_base64, prompt, max_retries=3):
    """调用VL模型识别图片"""
    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{lm_url}/v1/chat/completions",
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
                print(f"  API错误: {response.status_code} - {response.text[:100]}")

        except requests.exceptions.Timeout:
            print(f"  请求超时")
        except Exception as e:
            print(f"  错误: {e}")

        if attempt < max_retries - 1:
            time.sleep(3)

    return "[错误: 无法从VL模型获取响应]"


def save_results_to_markdown(task):
    """保存结果到Markdown文件"""
    output_file = os.path.join(
        app.config["OUTPUT_FOLDER"],
        f"{task['id']}_{Path(task['filename']).stem}_全文.md",
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# {Path(task['filename']).stem}\n\n")
        f.write(f"**总页数**: {task['total_pages']}\n\n")
        f.write("---\n\n")

        for page_num in sorted(task["results"].keys()):
            f.write(f"## 第 {page_num + 1} 页\n\n")
            f.write(task["results"][page_num])
            f.write("\n\n---\n\n")

    return output_file


def process_pdf(task_id, model_name, lm_url, prompt):
    """后台处理PDF"""
    task = tasks[task_id]
    task["status"] = "running"

    try:
        for i in range(task["total_pages"]):
            task["current_page"] = i

            try:
                img_bytes = extract_page_as_image(task["filepath"], i)
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                result = call_vl_model(lm_url, model_name, img_base64, prompt)
                task["results"][i] = result
            except Exception as e:
                task["errors"].append(f"第{i + 1}页: {str(e)}")
                task["results"][i] = f"[Error: {e}]"

            time.sleep(0.3)

        # 保存结果
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
    <title>PDF AI识别工具</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { text-align: center; color: #333; margin-bottom: 30px; }
        
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
        .file-info .size { color: #888; font-size: 13px; margin-top: 4px; }
        .file-info .pages { color: #4a90d9; font-size: 13px; }
        
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
    </style>
</head>
<body>
    <div class="container">
        <h1>📄 PDF AI识别工具</h1>
        
        <!-- 配置区域 -->
        <div class="card">
            <h2>⚙️ LM Studio 配置</h2>
            <div class="form-group">
                <label>LM Studio 地址</label>
                <input type="text" id="lmUrl" value="http://192.168.21.44:1234" placeholder="http://192.168.1.100:1234">
            </div>
            <div class="form-group">
                <label>选择模型</label>
                <div style="display: flex; gap: 8px; margin-bottom: 8px;">
                    <button class="btn btn-primary" onclick="loadModels()" style="padding: 8px 16px;">刷新模型列表</button>
                </div>
                <div class="model-list" id="modelList">
                    <div class="model-item" onclick="selectModel(this, '')">点击"刷新模型列表"加载可用模型</div>
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
                <textarea id="prompt" placeholder="输入你想要的识别指令...">你是专业的文档解析专家。请仔细识别这张图片中的所有内容，完整提取不要省略。包括：书名、作者、简介、ISBN、定价、出版社信息、套书介绍等所有内容。保持原有结构和格式输出。</textarea>
                <small>默认已填写通用提示词，可根据需要修改</small>
            </div>
        </div>
        
        <!-- 操作按钮 -->
        <div class="card">
            <div class="actions">
                <button class="btn btn-primary" id="startBtn" onclick="startProcessing()" disabled>开始识别</button>
                <button class="btn btn-success" id="downloadBtn" onclick="downloadResult()" style="display: none;">下载结果</button>
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
        let eventSource = null;
        let lastPreviewPage = 0;
        
        async function loadModels() {
            const lmUrl = document.getElementById('lmUrl').value;
            const modelList = document.getElementById('modelList');
            modelList.innerHTML = '<div class="model-item">加载中...</div>';
            
            try {
                const resp = await fetch(`/api/models?lm_url=${encodeURIComponent(lmUrl)}`);
                const data = await resp.json();
                
                if (data.success) {
                    const models = data.vision_models || data.all_models;
                    if (models.length === 0) {
                        modelList.innerHTML = '<div class="model-item">未检测到模型，请确保LM Studio正在运行</div>';
                    } else {
                        modelList.innerHTML = models.map(m => 
                            `<div class="model-item" onclick="selectModel(this, '${m}')">${m}</div>`
                        ).join('');
                    }
                } else {
                    modelList.innerHTML = `<div class="model-item">错误: ${data.error}</div>`;
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
            const lmUrl = document.getElementById('lmUrl').value;
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
                    model: model,
                    lm_url: lmUrl,
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
            
            // SSE连接
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
            const fill = document.getElementById('progressFill');
            const text = document.getElementById('progressText');
            const statusBox = document.getElementById('statusBox');
            
            fill.style.width = data.progress + '%';
            text.textContent = `第 ${data.current_page} / ${data.total_pages} 页 (${data.progress}%)`;
            
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
        
        function prevPage() {
            if (lastPreviewPage > 0) loadPreview(lastPreviewPage - 1);
        }
        
        function nextPage() {
            loadPreview(lastPreviewPage + 1);
        }
        
        function downloadResult() {
            window.location.href = `/api/download/${currentTaskId}`;
        }
        
        // 页面加载时自动加载模型列表
        window.onload = loadModels;
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    print("=" * 50)
    print("PDF AI识别工具 Web界面")
    print("请打开浏览器访问: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
