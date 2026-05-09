# AGENTS.md

This repository contains a personal WeCom assistant powered by DeepSeek. Treat it as a private, security-sensitive automation project.

## Project Shape

- Backend: Python 3.11+ / FastAPI.
- Entry point: `app.main:app`.
- WeCom integration: `app/gateways/wecom.py` and `app/gateways/wecom_crypto.py`.
- Core flow: `app/services/message_processor.py`.
- Long-term memory: `app/memory/`.
- Tools: `app/tools/`, including expenses, memory, search, and reminders.
- Deployment: `docker-compose.yml` for the full stack, `docker-compose.lowmem.yml` for small servers.

## Commands

- Install locally: `python -m pip install -e .[dev]`
- Run tests: `pytest -q`
- Health check after start: `curl http://127.0.0.1:8008/health`
- Low-memory deploy: `docker compose -f docker-compose.lowmem.yml up -d --build`
- Full deploy with search: `docker compose up -d --build`

## Safety Rules

- Never commit `.env`, API keys, WeCom secrets, tokens, EncodingAESKey values, database passwords, private keys, or server credentials.
- Keep `.env.example` as placeholders only.
- Before committing, check staged files and scan for likely secrets.
- Do not implement personal WeChat reverse-engineering or unofficial login flows. This project intentionally uses official WeCom/self-built-app capabilities.
- High-risk tools, including memory deletion and bulk finance changes, must require explicit confirmation.

## Deployment Notes

- The target server is memory-constrained, so prefer `docker-compose.lowmem.yml` first.
- Search is optional and can be disabled with `SEARCH_ENABLED=false`.
- SearXNG should only be enabled after the main WeCom, DeepSeek, memory, and expense flows are stable.
- If memory is insufficient, stop unused services before deploying instead of deleting application directories.

## Product Direction

The assistant should feel like a personal operating layer inside WeCom: concise, useful, warm, and action-oriented. It should remember stable preferences, handle expense capture naturally, answer questions through DeepSeek, and gracefully disclose uncertainty when search or fresh information is unavailable.
