# 企业微信 DeepSeek 个人助理

这是一个可部署的个人 AI 助理后端：企业微信作为入口，DeepSeek 作为大脑，带长期记忆、记账、提醒、免费优先搜索和每日/每周摘要。

## 已实现能力

- 企业微信自建应用回调校验、消息解密、白名单身份校验、应用消息回复。
- DeepSeek OpenAI-compatible Chat Completions，支持工具调用和降级回复。
- 长期记忆分层：偏好、事实、事件、财务、项目、指令等。
- 花销自然语言录入和查询：例如 `午饭 36`、`昨天打车 42.8`、`这个月餐饮花了多少`。
- 免费优先搜索：内置 SearXNG 作为 `web_search` 工具，失败时自动降级。
- 提醒、每日花销摘要、每周记忆回顾。
- PostgreSQL + pgvector、Redis、Docker Compose 部署。

## 本地启动

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .[dev]
copy .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8008
```

本地没有 DeepSeek Key 时，接口会返回安全降级回复，方便先测试企业微信链路和工具解析。

## Docker 启动

```bash
copy .env.example .env
docker compose up -d --build
```

低内存服务器先用：

```bash
docker compose -f docker-compose.lowmem.yml up -d --build
```

健康检查：

```bash
curl http://127.0.0.1:8008/health
```

## 企业微信配置

1. 企业微信管理后台创建自建应用。
2. 打开“接收消息”，填写：
   - URL：`https://你的域名/wecom/callback`
   - Token：对应 `.env` 的 `WE_COM_TOKEN`
   - EncodingAESKey：对应 `.env` 的 `WE_COM_ENCODING_AES_KEY`
3. `.env` 里设置 `WE_COM_CORP_ID`、`WE_COM_AGENT_ID`、`WE_COM_SECRET`、`OWNER_WE_COM_USER_ID`。
4. 只有 `OWNER_WE_COM_USER_ID` 会被服务，其他用户消息会被拒绝。

## 云服务器低内存建议

你的服务器约 1.8GB 内存。标准 Compose 会同时跑应用、Postgres、Redis、SearXNG，建议先保留 1GB 以上可用内存再启动。

如果内存紧张，优先级建议：

1. 先停掉不用的 Node/PM2 服务，例如摄影展览站点。
2. Redis 已经以无持久化轻量模式运行。
3. SearXNG 最占弹性内存，必要时可先把 `SEARCH_ENABLED=false`，等主链路稳定后再打开。

## 测试

```bash
pytest
```

## 重要说明

DeepSeek API 不会替你保存对话状态，本项目会自行拼装短期上下文并写入长期记忆。涉及删除记忆、批量改账等高风险工具默认要求确认，避免模型误操作。
