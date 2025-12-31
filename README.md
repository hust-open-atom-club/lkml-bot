# LKML-BOT

基于 [NoneBot 2](https://nonebot.dev/) 框架构建的机器人，用于监控 Linux 内核及其他子系统邮件列表，并通过 Discord/Feishu 推送更新与指令交互。支持监控多个子系统，并可用 Discord 命令进行订阅与管理。

> 框架与组件引用：本项目使用 NoneBot 2 及其适配器生态（例如 `nonebot-adapter-discord`、`nonebot-adapter-feishu`），并基于其插件与驱动机制实现业务逻辑。

## 功能特性

- 📧 监控多个邮件列表子系统
- 🔔 自动检测新邮件和回复，并发送通知到 Discord/Feishu

## 如何启用

### 前置要求

- Python 3.9+
- NoneBot 框架
- Discord Bot Token

### 安装依赖

```bash
# 安装运行时依赖
pip install -e .

# 安装开发依赖（包括代码规范和格式化工具）
pip install -e ".[dev]"
```

### 配置环境变量

创建 `.env` 文件（或在系统环境变量中设置）：

```bash
DISCORD_BOTS='[{"token": "YOUR_BOT_TOKEN", "intent": {"guild_messages": true, "direct_messages": true}}]'

# Discord Bot Token（必需）
LKML_DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN_HERE

# Discord 频道 ID（用于发送通知消息）
LKML_DISCORD_CHANNEL_ID=CHANNEL_ID

# Discord Webhook URL（用于发送通知消息）
LKML_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Feishu Webhook URL（用于发送通知消息）
LKML_FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/...

# 数据库连接 URL（可选，默认为 sqlite+aiosqlite:///./lkml_bot.db）
LKML_DATABASE_URL=sqlite+aiosqlite:///./lkml_bot.db

# 手动配置的额外子系统（可选，逗号分隔）
LKML_MANUAL_SUBSYSTEMS=rust-for-linux

# 每次更新显示的最大news数量（可选，默认 20）
LKML_MAX_NEWS_COUNT=20

# 监控任务执行周期（秒，可选，默认 300 秒即 5 分钟）
# 最小值为 60 秒（1 分钟），避免过于频繁的请求
LKML_MONITORING_INTERVAL=300
```

### 启动机器人

```bash
# 使用 NoneBot CLI 启动
nb run

# 或使用 Python 直接运行
python bot.py
```

机器人启动后会自动：
- 连接到 Discord
- 加载插件
- 初始化数据库
- 启动监控调度器（如果已启动监控任务）

## 配置项说明

### 必需配置

| 环境变量 | 说明 | 示例 |
|---------|------|------|
| `DISCORD_BOTS` | Discord Bot Token JSON 配置 | `[{"token": "YOUR_TOKEN", ...}]` |
| `LKML_DISCORD_BOT_TOKEN` | Discord Bot Token | `YOUR_BOT_TOKEN_HERE` |
| `LKML_DISCORD_CHANNEL_ID` | Discord 频道 ID | `CHANNEL_ID` |
| `LKML_DISCORD_WEBHOOK_URL` | Discord Webhook URL，用于发送通知消息。如果未配置，消息只会在日志中记录 | - |
| `LKML_FEISHU_WEBHOOK_URL` | Feishu Webhook URL，用于发送通知消息。如果未配置，消息只会在日志中记录 | - |

### 可选配置

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `LKML_DATABASE_URL` | 数据库连接 URL | `sqlite+aiosqlite:///./lkml_bot.db` |
| `LKML_MANUAL_SUBSYSTEMS` | 手动配置的额外子系统列表（逗号分隔）。内核子系统会自动从 vger 缓存获取，此配置用于添加无法从网页直接获取的子系统 | - |
| `LKML_MAX_NEWS_COUNT` | 每次更新显示的最大新闻数量 | `20` |
| `LKML_MONITORING_INTERVAL` | 监控任务执行周期（秒）。最小值为 60 秒（1 分钟），避免过于频繁的请求 | `300`（5 分钟） |

## 如何使用

### 命令格式

所有命令均需要 @ 提及机器人，格式为：`@机器人 /命令 [参数...]`

### 可用命令

#### `/help`
查看帮助信息，自动汇总所有已注册的命令。

**示例：**
```
@lkml-bot /help
```

#### `/subscribe` / `/sub`
订阅或管理子系统的邮件列表。订阅后，当该子系统有新邮件或回复时，你会收到通知。

支持的用法：

- 订阅单个子系统：
  - `@lkml-bot /subscribe rust-for-linux`
  - `@lkml-bot /sub rust-for-linux`
- 批量订阅多个子系统（空格或逗号分隔）：
  - `@lkml-bot /subscribe linux-kernel netdev dri-devel`
  - `@lkml-bot /sub linux-kernel,netdev,dri-devel`
- 查看当前订阅和所有可订阅的子系统（Discord Embed 展示，5 个一行）：
  - `@lkml-bot /subscribe list`
- 按关键字模糊搜索可订阅子系统：
  - `@lkml-bot /subscribe search linux`

#### `/unsubscribe` / `/unsub`
取消订阅一个或多个子系统的邮件列表。

支持的用法：

- 取消订阅单个子系统：
  - `@lkml-bot /unsubscribe rust-for-linux`
  - `@lkml-bot /unsub rust-for-linux`
- 批量取消订阅多个子系统（空格或逗号分隔）：
  - `@lkml-bot /unsubscribe linux-kernel netdev dri-devel`
  - `@lkml-bot /unsub linux-kernel,netdev,dri-devel`

#### `/start-monitor`
启动邮件列表监控定时任务。启动后，机器人会定期检查所有已订阅的子系统，并在发现新邮件时发送通知。

**注意**：机器人启动时会自动启动监控任务，此命令仅在监控被停止后需要手动启动时使用。

**示例：**
```
@lkml-bot /start-monitor
```

#### `/stop-monitor`
停止邮件列表监控定时任务。

**示例：**
```
@lkml-bot /stop-monitor
```

#### `/run-monitor`
立即执行一次邮件列表监控任务，不等待定时触发。用于测试或手动触发检查。

**示例：**
```
@lkml-bot /run-monitor
```
#### `/filter`

用于控制哪些 PATCH 会创建卡片，支持“高亮模式”和“独占模式”。仅管理员可用。

支持的子命令：

- `/filter add <name> <conditions> [--exclusive] [description]` 添加或覆盖规则（同名覆盖）
- `/filter list [--enabled-only]` 列出规则
- `/filter show <name|id>` 查看规则详情
- `/filter remove <name|id>` 删除规则
- `/filter enable <name|id>` 启用规则
- `/filter disable <name|id>` 禁用规则

条件格式（仅支持 key=value；逗号表示列表）：

- 文本匹配：普通字符串按"子串包含"匹配（大小写不敏感）
- 正则匹配：用 `/.../` 包裹，默认区分大小写；用 `/.../i` 则不区分大小写（标准 i 标志）
- 列表：逗号分隔，表示"任一匹配即可"
- 数字：自动转整型，例如 `min_patch_total=3`

常用键：

- author: 作者名称（字符串或列表，支持正则）
- author_email: 作者邮箱（字符串或列表，支持正则）
- subsys | subsystem: 子系统名称（字符串或列表，支持正则）
- subject: 主题（字符串或列表，支持正则）
- keywords: 内容关键词（字符串或列表，支持正则，从邮件内容中匹配）
- cclist | cc: To/CC 列表（字符串或列表，支持正则，从 root patch 的 To 和 CC 列表中匹配）

模式格式:
- 普通文本: 精确/包含匹配（大小写不敏感）
- /regex/: 正则匹配（大小写敏感）
- 列表: 逗号分隔，表示 OR 逻辑（任一匹配即可）

模式说明：

- 默认高亮模式（不带 `--exclusive`）：所有 PATCH 卡片都创建，匹配的卡片会额外标识匹配的规则
- 独占模式（`--exclusive`）：只有匹配规则的 PATCH 卡片才会创建

示例：

```bash
# 添加邮箱域名规则（高亮模式）
/filter add email-domain author_email=@gmail\.com

# 添加邮箱域名规则（正则，含子域，独占模式）
/filter add email-domain author_email=/@(?:.*\.)?/@gmail\.com$/ --exclusive "仅这些域名"

# 查看与列表
/filter show email-domain
/filter list --enabled-only

# 禁用与删除
/filter disable email-domain
/filter remove email-domain
```

规则详情展示为可读文本：

```
📋 过滤规则详情: email-domain
ID: 1
状态: ✅ 启用
模式: ⭐ 高亮模式（所有都创建但高亮匹配的）

过滤条件:
author_email: /@(?:.*\.)?@gmail\.com$/
```

#### `/watch`

用于为系列 PATCH 的封面（Cover Letter）创建专属 Thread，持续聚合后续回复，便于跟踪讨论。

- `/watch <message_id_header>` 为指定 PATCH 卡片创建 Thread 并开始跟踪

行为说明：

- 对系列 PATCH：机器人只为 Cover Letter 创建卡片；子补丁保存在数据库中用于 Thread 概览
- 当系列有新的子补丁或回复时，机器人会更新该系列卡片的概览，并在频道发送“Thread Overview 已更新”通知，附带 Thread 提及（例如 `Thread: <#1234567890>`）

示例：

```bash
# 为系列补丁的 Cover Letter 创建 Thread
/watch <message_id_header>
```

注意：

- 需要在配置中设置 Discord Bot Token 与频道 ID，并确保机器人在频道有发消息与创建 Thread 的权限
- 如果 Thread 已存在，机器人会尝试检索已存在的 Thread 并继续使用

**注意**：目前所有命令都可以使用，管理员权限功能将在后续版本中实现。

1. **首次使用**：
   - 机器人启动时会自动启动监控任务（无需手动操作）
   - 用户执行 `/subscribe <subsystem>` 订阅感兴趣的子系统

2. **日常使用**：
   - 机器人自动定期检查邮件列表（每 5 分钟）
   - 当有新邮件或回复时，自动发送通知到 Discord Webhook
   - 用户可以随时订阅/取消订阅子系统

3. **维护**：
   - 可以使用 `/start-monitor` 启动监控（如果被停止）
   - 可以使用 `/stop-monitor` 暂停监控
   - 使用 `/run-monitor` 手动触发一次检查

## 注意事项

- 监控任务启动后会自动定期检查邮件列表更新并发送通知到 Discord/Feishu 频道
- 确保 Discord Bot 在目标频道有发送消息的权限
- 如果没有配置 `LKML_DISCORD_WEBHOOK_URL`，监控结果只会在日志中记录，不会发送到 Discord
- 如果没有配置 `LKML_FEISHU_WEBHOOK_URL`，监控结果只会在日志中记录，不会发送到 Feishu

## TODO

- [x] 实现从服务器缓存获取 vger 子系统列表的功能（`src/lkml/vger_cache.py`）
  - Bot 的服务器缓存会存储所有从 vger 获取的内核子系统信息（键值对格式）
  - 需要在 `get_vger_subsystems_from_cache()` 函数中实现从服务器缓存读取逻辑
  - 函数应返回子系统名称列表，例如: `["lkml", "netdev", "dri-devel", ...]`
- [ ] 实现管理员权限系统
  - 目前所有命令都可以使用，`check_admin()` 函数暂时返回 `True`
  - 后续需要实现 Discord 用户/角色权限验证
  - 管理员命令（如 `/start-monitor`、`/stop-monitor`、`/run-monitor`）应限制为特定用户或角色才能执行
- [x] 实现 `/add-user` 命令
  - 添加用户过滤功能，支持在子系统邮件列表中搜索指定用户/组织
  - 启用后仅发送来自已订阅用户的特定邮件
> /filter rule add demo-filter author_email=xxx@gmail.com,yyy@gmail.com
- [x] 实现 `/del-user` 命令
  - 删除已添加的用户过滤
  - 移除后不再发送与该用户相关的邮件信息
> /filter rule del demo-filter author_email=xxx@gmail.com
- [ ] 实现 `/news` 命令
  - 强制发送当前时间最新的前 N 条邮件列表记录
  - 支持指定子系统或所有已订阅子系统

## 项目结构

```
src/
├── lkml/                        # 核心业务逻辑（独立于机器人框架）
│   ├── config.py                # 配置管理（LKMLConfig）
│   ├── scheduler.py             # 任务调度器（LKMLScheduler）
│   ├── db/                      # 数据库接口与模型
│   │   ├── database.py          # 数据库接口与实现（LKMLDatabase）
│   │   └── models.py            # SQLAlchemy 模型
│   ├── service/                 # 业务服务层
│   │   ├── service.py           # 基础服务
│   │   ├── monitoring_service.py# 监控相关服务
│   │   ├── subsystem_service.py # 子系统相关服务
│   │   ├── query_service.py     # 查询相关服务
│   │   ├── patch_card_service.py# Patch Card 相关服务
│   │   ├── thread_service.py    # Thread 相关服务
│   │   ├── feed_message_service.py # Feed 消息处理（渲染编排）
│   │   ├── patch_card_filter_service.py # 过滤规则服务
│   │   ├── operation_log_service.py     # 操作日志服务
│   │   └── helpers.py           # 服务层辅助函数
│   └── feed/                    # 邮件列表监控
│       ├── feed.py              # Feed 抓取与入库
│       ├── feed_monitor.py      # 监控编排（LKMLFeedMonitor）
│       ├── feed_message_classifier.py # PATCH 主题解析
│       ├── vger_subsystems.py   # vger 子系统来源（get_vger_subsystems）
│       └── types.py             # 数据类型定义
└── plugins/
    └── lkml_bot/                # NoneBot 插件实现
        ├── __init__.py          # 插件入口（注册调度器、启动/停止钩子）
        ├── config.py            # 插件侧配置（继承 LKMLConfig）
        ├── shared.py            # 插件共享工具
        ├── message_sender.py    # 聚合发送器
        ├── client/              # 平台客户端（Discord 等）
        ├── commands/            # 命令处理器
        └── renders/             # 渲染器集合（Discord/Feishu，PatchCard/Thread）
```

## 代码规范和格式化

项目使用 make check-fmt && make check-lint 进行代码检查和格式化。

### 安装开发工具

```bash
pip install -e ".[dev]"
```

### 使用方法

```bash
# 检查代码（不修改文件）
make check-lint

# 格式化代码
make check-fmt

```

### VS Code 集成

推荐安装以下 VS Code 扩展：
- [MyPy Type Checker](https://marketplace.visualstudio.com/items?itemName=ms-python.mypy-type-checker) - 类型检查

## 文档

更多信息请查看 [NoneBot 官方文档](https://nonebot.dev/)


## 许可证

本项目使用 MIT License。详情见根目录的 `LICENSE` 文件。
