# PDF AI OCR

基于本地VL模型（视觉语言模型）的PDF内容识别工具，支持Ollama和LM Studio作为后端。

## 功能特点

- 🌐 **多后端支持**: Ollama / LM Studio
- 📄 **逐页AI识别**: 将PDF每页转为图片，使用VL模型识别
- 📊 **保持原有格式**: 完整提取书名、作者、ISBN、定价、简介等信息
- ⚡ **实时进度**: Web界面实时显示处理进度
- 👁️ **结果预览**: 处理过程中即可预览已识别内容
- 📥 **一键下载**: 处理完成后直接下载Markdown文件

## 支持的模型

推荐使用具有图像识别能力的VL模型：

### LM Studio
- `qwen3-vl-8b-instruct`
- `qwen2-vl-7b-instruct`
- `llava` 系列
- `llama3.2-vision`

### Ollama
- `llama3.2-vision:latest`
- `qwen2.5-vl:latest`
- `llava:latest`

## 快速开始

### 1. 安装依赖

```bash
pip install flask pymupdf requests
```

### 2. 启动LM Studio或Ollama

**LM Studio:**
1. 下载 [LM Studio](https://lmstudio.ai/)
2. 下载VL模型（如 qwen3-vl-8b-instruct）
3. 启动本地服务器 (默认 http://localhost:1234)

**Ollama:**
```bash
# 安装Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 下载VL模型
ollama pull llama3.2-vision

# 启动服务 (默认 http://localhost:11434)
ollama serve
```

### 3. 运行工具

```bash
python pdf_ai_ocr.py
```

### 4. 打开浏览器

访问 http://localhost:5000

## 使用方法

1. **选择提供商**: 点击 "LM Studio" 或 "Ollama" 标签
2. **配置地址**: 确认API地址正确（默认已填充）
3. **刷新模型**: 点击刷新按钮加载可用模型列表
4. **选择模型**: 从列表中选择VL模型
5. **上传PDF**: 点击上传区域选择PDF文件
6. **开始识别**: 点击"开始识别"按钮
7. **预览下载**: 处理完成后可预览或下载结果

## 目录结构

```
pdf-ai-ocr/
├── pdf_ai_ocr.py      # 主程序（Web界面）
├── Dockerfile         # Docker部署文件
├── docker-compose.yml # Docker Compose配置
├── requirements.txt   # Python依赖
├── README.md          # 本文档
└── .dockerignore      # Docker忽略文件
```

## Docker部署

### 使用Docker Compose (推荐)

```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 使用Docker手动构建

```bash
# 构建镜像
docker build -t pdf-ai-ocr .

# 运行容器
docker run -d -p 5000:5000 \
  --add-host=host.docker.internal:host-gateway \
  pdf-ai-ocr
```

> 注意: Docker方式运行需要宿主机的Ollama/LM Studio服务在同一台机器上。

## 常用命令

### LM Studio
```bash
# 启动LM Studio后，在Settings -> Server中启用
# 默认地址: http://localhost:1234
```

### Ollama
```bash
# 查看已安装模型
ollama list

# 运行模型测试
ollama run llama3.2-vision

# API方式调用
curl http://localhost:11434/api/generate -d '{"model":"llama3.2-vision","prompt":"Hello"}'
```

## API接口

### Web界面
- `GET /` - Web界面

### REST API
- `GET /api/providers` - 获取支持的提供商列表
- `GET /api/models?provider=lmstudio&url=http://localhost:1234` - 获取模型列表
- `POST /api/upload` - 上传PDF文件
- `POST /api/start` - 开始处理
- `GET /api/status/<task_id>` - 获取处理状态
- `GET /api/stream/<task_id>` - SSE进度流
- `GET /api/download/<task_id>` - 下载结果
- `GET /api/preview/<task_id>/<page>` - 预览指定页

## 配置说明

### 环境变量
- `FLASK_HOST` - 监听地址 (默认: 0.0.0.0)
- `FLASK_PORT` - 监听端口 (默认: 5000)

### 提示词自定义

在Web界面中可自定义识别提示词，默认提示词:

```
你是专业的文档解析专家。请仔细识别这张图片中的所有内容，完整提取不要省略。
包括：书名、作者、简介、ISBN、定价、出版社信息、套书介绍等所有内容。
保持原有结构和格式输出。
```

## 常见问题

### Q: 提示"模型不支持图像处理"
A: 请确认已加载VL模型（带vl/vision/llava关键词的模型），普通文本模型无法处理图像。

### Q: 处理速度慢
A: 可以尝试降低PDF图片分辨率（修改代码中`scale=1.5`为更小的值），或使用更小的VL模型。

### Q: 如何处理纯文字PDF？
A: 如果PDF本身有文字层，可以直接使用`pdf_extractor.py`提取文字，速度更快。

## License

MIT License

## Star History

如果你觉得这个项目有用，请给个⭐️
