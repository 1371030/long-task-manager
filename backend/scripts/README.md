# 论文结构化抽取最小测试

`plan_probe.py` 是一个最小化测试脚本，用来验证 OpenAI Structured Outputs 对“从用户提供内容中抽取结构化字段”的支持。

脚本按官方 Structured Outputs 的 structured data 示例组织：

- OpenAI Python SDK
- `client.responses.parse(...)`
- `text_format=ResearchPaperExtraction`
- 默认 user content 与官方示例一致，为 `"..."`
- 抽取字段：`title`、`authors`、`abstract`、`keywords`
- 会自动读取 `backend/.env`
- `api_key` 从 `IMX_API_KEY` 或 `API_KEY` 读取
- `base_url` 从 `IMX_API_URL` 或 `API_URL` 读取，未配置时使用脚本默认值；这是为了本地兼容服务，官方示例直接使用 `OpenAI()`
- 模型从 `IMX_API_MODEL` 或 `API_MODEL` 读取，未配置时使用 `gpt-5.4`

## 运行方式

进入 backend 目录：

```bash
cd /Users/xjerry/.openclaw/workspace/long-agent-system/backend
```

配置 `.env`：

```bash
API_KEY=你的-key
API_URL=http://你的-openai-compatible-host/v1
API_MODEL=gpt-5.4
```

使用官方示例占位输入：

```bash
./.venv/bin/python scripts/plan_probe.py
```

从命令行传入论文内容：

```bash
./.venv/bin/python scripts/plan_probe.py "Attention Is All You Need. Ashish Vaswani, Noam Shazeer. Abstract: ..."
```

从文件传入论文内容：

```bash
./.venv/bin/python scripts/plan_probe.py --content-file /path/to/paper.txt
```

传入真实论文内容后，正常输出类似：

```json
{
  "title": "Deep Residual Learning for Image Recognition",
  "authors": ["Kaiming He", "Xiangyu Zhang", "Shaoqing Ren", "Jian Sun"],
  "abstract": "Deeper neural networks are more difficult to train...",
  "keywords": ["residual learning", "image recognition", "deep neural networks", "optimization"]
}
```
