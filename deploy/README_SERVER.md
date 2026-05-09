# 云服务器部署笔记

服务器内存约 1.8GB，建议第一版使用低内存部署：

```bash
ssh server
mkdir -p /www/wwwroot/wecom-deepseek-assistant
cd /www/wwwroot/wecom-deepseek-assistant
cp .env.example .env
vi .env
systemctl start docker
docker compose -f docker-compose.lowmem.yml up -d --build
curl http://127.0.0.1:8008/health
```

企业微信后台回调地址可以先填：

```text
http://8.138.150.200:8008/wecom/callback
```

如果后续绑定域名并走 Nginx/HTTPS，反向代理到：

```text
http://127.0.0.1:8008
```

低内存模式默认 `SEARCH_ENABLED=false`。主链路稳定后，如果还有 700MB 以上可用内存，再切换完整版本：

```bash
docker compose -f docker-compose.yml up -d --build
```

如果内存不足，先停占用较高且暂时不用的服务，例如：

```bash
pm2 stop photo-exhibition
```

不要直接删除站点目录，除非已经确认不需要保留源代码和资源文件。
