# Docker 部署指南

## 使用 Docker 快速开始

### 前置要求
- 已安装 Docker 和 Docker Compose
- Git（用于克隆仓库）

### 部署步骤

1. **克隆仓库**（如果还没有克隆）：
   ```bash
   git clone https://github.com/iLearn-Lab/NovelClaw.git
   cd NovelClaw
   ```

2. **配置环境变量**：
   ```bash
   # 复制示例环境变量文件
   cp .env.auth-portal.example apps/auth-portal/.env
   cp .env.multiagent.example apps/multiagent/.env
   cp .env.novelclaw.example apps/novelclaw/.env
   ```

3. **编辑 .env 文件**，添加你的 API 密钥：
   - `apps/novelclaw/.env` - 添加 OpenAI/Anthropic API 密钥
   - `apps/multiagent/.env` - 添加 OpenAI/Anthropic API 密钥
   - `apps/auth-portal/.env` - 修改 SECRET_KEY

4. **构建并启动所有服务**：
   
   **Windows 用户**：
   ```batch
   .\docker-start.bat
   ```
   
   **Linux/Mac 用户**：
   ```bash
   chmod +x docker-start.sh
   ./docker-start.sh
   ```
   
   **或手动启动**：
   ```bash
   docker-compose up -d
   ```

5. **访问应用**：
   - 认证门户：http://localhost:8010/select-mode
   - 多智能体：http://localhost:8011/dashboard
   - NovelClaw：http://localhost:8012/dashboard

### Docker 常用命令

**启动服务**：
```bash
docker-compose up -d
```

**停止服务**：
```bash
docker-compose down
```

**查看日志**：
```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f novelclaw
docker-compose logs -f multiagent
docker-compose logs -f auth-portal
```

**代码更改后重新构建**：
```bash
docker-compose up -d --build
```

**重启特定服务**：
```bash
docker-compose restart novelclaw
```

### 数据持久化

以下目录通过卷挂载实现数据持久化：
- `apps/auth-portal/local_web_portal/data` - 认证门户数据库
- `apps/multiagent/local_web_portal/data` - 多智能体数据
- `apps/novelclaw/local_web_portal/data` - NovelClaw 数据库
- `apps/novelclaw/local_web_portal/runs` - 写作运行记录和输出

### 故障排除

**端口冲突**：
如果端口 8010、8011 或 8012 已被占用，编辑 `docker-compose.yml` 修改端口映射：
```yaml
ports:
  - "9010:8010"  # 将 9010 改为你想要的端口
```

**权限问题**：
在 Linux/Mac 上，可能需要调整权限：
```bash
chmod -R 755 apps/*/local_web_portal/data
chmod -R 755 apps/novelclaw/local_web_portal/runs
```

**查看容器状态**：
```bash
docker-compose ps
```

**进入容器调试**：
```bash
docker exec -it novelclaw-workspace bash
```

### 生产环境部署

生产环境部署建议：
1. 使用专业的密钥管理（不要使用 .env 文件）
2. 配置反向代理（nginx 示例见 `infra/nginx/`）
3. 设置 SSL/TLS 证书
4. 使用外部数据库替代 SQLite
5. 配置数据卷的备份策略
6. 在 docker-compose.yml 中设置资源限制

更多生产部署细节请参考 [DEPLOYMENT.md](DEPLOYMENT.md) 和 [docs/DEPLOYMENT.zh-CN.md](docs/DEPLOYMENT.zh-CN.md)。

### Docker 部署优势

✅ **无需配置 Python 环境** - 所有依赖都打包在镜像中

✅ **跨平台一致性** - Windows、Linux、Mac 使用相同的部署方式

✅ **易于管理** - 一键启动、停止、重启所有服务

✅ **数据持久化** - 通过卷挂载确保数据不丢失

✅ **隔离性好** - 每个服务运行在独立容器中

✅ **易于扩展** - 可以轻松添加更多服务或调整资源
