# PDF AI OCR

基于本地VL模型（视觉语言模型）的PDF内容识别工具，仅支持LM Studio作为后端。

## 功能特点

- 📄 **逐页AI识别**: 将PDF每页转为图片，使用VL模型识别
- 📊 **原样输出**: 严格OCR模式，不做总结改写，完整保留原文
- 📝 **多预设模板**: 合同、发票、证件、书籍、表格等常用场景
- 📥 **Word输出**: 识别结果直接导出为Word文档
- 📤 **批量处理**: 支持一次性上传多个PDF文件
- ⚡ **实时进度**: Web界面实时显示处理进度
- 👁️ **结果预览**: 处理过程中即可预览已识别内容

## 支持的模型

推荐使用具有图像识别能力的VL模型（仅支持LM Studio）：

- `qwen3-vl-8b` ⭐ **推荐**
- `qwen2-vl-7b-instruct`
- `llava` 系列
- `llama3.2-vision`

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动LM Studio

1. 下载 [LM Studio](https://lmstudio.ai/)
2. 下载VL模型（如 `qwen3-vl-8b`）
3. 启动本地服务器 (默认 http://localhost:1234)

### 3. 运行工具

```bash
python pdf_ai_ocr.py
```

### 4. 打开浏览器

访问 http://localhost:5000

## 使用方法

1. **刷新模型**: 点击刷新按钮加载可用VL模型
2. **选择模型**: 从列表中选择一个VL模型
3. **上传PDF**: 点击上传区域选择PDF文件（支持批量）
4. **选择预设**: 选择识别场景预设模板（合同/发票/证件等）
5. **开始识别**: 点击开始识别按钮
6. **预览下载**: 处理完成后可预览或下载Word文档

## 预设提示词

工具内置多种预设模板：

| 预设 | 适用场景 |
|------|----------|
| 📜 合同文档 | 合同条款、双方信息、金额、日期、签名 |
| 🧾 发票收据 | 发票号码、日期、金额、商品明细 |
| 🪪 身份证/证件 | 姓名、性别、民族、出生日期、地址、身份证号 |
| 📚 书籍资料 | 书名、作者、出版社、ISBN、目录、正文 |
| 📝 通用文档 | 任意文档的纯OCR识别 |
| 📊 表格数据 | 保持行列结构的表格识别 |

所有预设都采用**严格OCR指令**，确保模型只输出原文，不做任何总结或发挥。

## 目录结构

```
pdf-ai-ocr/
├── pdf_ai_ocr.py      # 主程序（Web界面）
├── requirements.txt    # Python依赖
├── Dockerfile         # Docker部署文件
├── docker-compose.yml # Docker Compose配置
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

> 注意: Docker方式运行需要宿主机的LM Studio服务在同一台机器上。

## 常见问题

### Q: 提示"模型不支持图像处理"
A: 请确认已加载VL模型（带vl/vision/llava关键词的模型），普通文本模型无法处理图像。

### Q: 模型不听话，输出总结而不是原文
A: 请使用内置预设模板，或在自定义提示词中明确写"禁止添加任何说明，只输出原文"。

### Q: 处理速度慢
A: 可以尝试降低PDF图片清晰度（代码中默认scale=1.0），或使用更小的VL模型。

### Q: 内存不足导致部分页面识别失败
A: 这是LM Studio的KV缓存问题，建议在LM Studio中降低Context Length设置，或使用更大的VL模型。

## API接口

### Web界面
- `GET /` - Web界面

### REST API
- `GET /api/models?url=http://localhost:1234` - 获取模型列表
- `GET /api/presets` - 获取预设提示词列表
- `POST /api/upload` - 上传PDF文件
- `POST /api/start` - 开始处理
- `GET /api/status/<task_id>` - 获取处理状态
- `GET /api/stream/<task_id>` - SSE进度流
- `GET /api/download/<task_id>` - 下载结果（Word文档）
- `GET /api/preview/<task_id>/<page>` - 预览指定页

## License

MIT License

## Star History

如果你觉得这个项目有用，请给个⭐️
