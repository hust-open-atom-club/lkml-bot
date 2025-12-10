# Zeabur 部署指南

本指南说明如何在 Zeabur 平台上使用 Docker 方式部署 LKML Bot。

## 前置准备

1. 确保你有一个 Zeabur 账号
2. 将代码推送到 GitHub/GitLab 等 Git 仓库
3. 准备好必要的环境变量配置

## 部署步骤

### 1. 在 Zeabur 创建新项目

1. 登录 [Zeabur](https://zeabur.com)
2. 点击 "New Project"
3. 选择 "Deploy from Git Repository"
4. 连接你的 Git 仓库

### 2. 配置构建设置

Zeabur 会自动检测 Dockerfile，如果没有自动检测到，请：

1. 在项目设置中选择 "Docker"
2. 确保 Dockerfile 路径为 `Dockerfile`（根目录）

### 3. 配置环境变量

在 Zeabur 项目设置中添加以下环境变量：

#### 必需环境变量

```bash
# Discord Bot Token（必需）
DISCORD_BOTS='[{"token": "YOUR_BOT_TOKEN", "intent": {"guild_messages": true, "direct_messages": true}}]'

# Discord Webhook URL（用于发送通知消息）
LKML_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Discord Bot Token（必需）
LKML_DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN_HERE

# Discord 频道 ID（用于发送通知消息）
LKML_DISCORD_CHANNEL_ID=CHANNEL_ID
```

#### 可选环境变量

```bash
# 数据库连接 URL（可选，默认为 sqlite+aiosqlite:///./lkml_bot.db）
# 注意：在 Zeabur 上，建议使用持久化存储卷来保存数据库文件
LKML_DATABASE_URL=sqlite+aiosqlite:///./data/lkml_bot.db

# 手动配置的额外子系统（可选，逗号分隔）
LKML_MANUAL_SUBSYSTEMS=rust-for-linux,lkml,qemu-rust,qemu-riscv

# 每次更新显示的最大news数量（可选，默认 20）
LKML_MAX_NEWS_COUNT=20

# 监控任务执行周期（秒，可选，默认 300 秒即 5 分钟）
LKML_MONITORING_INTERVAL=300

# NoneBot Driver 配置（可选，默认使用 FastAPI）
DRIVER=~fastapi+~httpx+~websockets

# 端口配置（可选，Zeabur 会自动检测，但可以手动指定）
PORT=8080
```

### 4. 配置持久化存储（重要）

由于应用使用 SQLite 数据库，需要配置持久化存储卷来保存数据：

1. 在 Zeabur 项目设置中找到 "Storage" 或 "Volumes" 选项
2. 添加一个新的存储卷，挂载到 `/app/data` 路径
3. 这样数据库文件会持久化保存，即使容器重启也不会丢失

### 5. 部署

1. 点击 "Deploy" 按钮
2. 等待构建和部署完成
3. 查看日志确认应用已成功启动

## 验证部署

部署成功后，你可以：

1. 在 Discord 中 @ 机器人并发送 `/help` 命令，确认机器人响应正常
2. 查看 Zeabur 的日志输出，确认没有错误信息
3. 测试订阅功能：`@机器人 /subscribe lkml`

## 注意事项

1. **数据库持久化**：务必配置存储卷，否则容器重启后数据会丢失
2. **环境变量安全**：不要在代码中硬编码敏感信息，使用 Zeabur 的环境变量功能
3. **资源限制**：根据实际使用情况调整 Zeabur 分配的资源（CPU、内存）
4. **监控任务**：机器人启动后会自动启动监控任务，无需手动操作

## 故障排查

### 应用无法启动

- 检查环境变量是否正确配置
- 查看日志中的错误信息
- 确认 Discord Bot Token 是否有效

### 数据库问题

- 确认存储卷已正确挂载到 `/app/data`
- 检查数据库文件权限
- 查看日志中的数据库连接错误

### 无法连接到 Discord

- 检查 `DISCORD_BOTS` 环境变量格式是否正确（JSON 格式）
- 确认 Bot Token 是否有效
- 检查网络连接是否正常

## 更新部署

当你推送新的代码到 Git 仓库后，Zeabur 会自动触发重新部署。你也可以手动触发部署：

1. 在 Zeabur 项目页面点击 "Redeploy"
2. 等待构建和部署完成

## 相关资源

- [Zeabur 文档](https://zeabur.com/docs)
- [NoneBot 文档](https://nonebot.dev/)
- [Docker 文档](https://docs.docker.com/)

