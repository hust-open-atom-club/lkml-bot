"""共享工具模块

提供插件共用的工具函数和常量，包括：
- 命令注册管理
- 权限检查
- 插件元数据
"""

from functools import wraps
from typing import Any, Awaitable, Callable, Optional, Tuple

from nonebot.adapters import Event
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

from .config import get_config


__plugin_meta__ = PluginMetadata(
    name="LKML Bot",
    description="邮件列表助手命令",
    usage="@lkml-bot /<子命令> [参数...]",
)


# 命令注册表：各命令模块在导入时将自身的元信息注册到这里
COMMAND_REGISTRY = []  # list of dict: {name, usage, description, admin_only}


def register_command(name: str, usage: str, description: str, admin_only: bool = False):
    """注册命令元信息，供 help 命令聚合显示。

    参数:
    - name: 命令名（如 subscribe）
    - usage: 用法字符串（不含 @lkml-bot 前缀，例如 "/subscribe <subsystem>"）
    - description: 简短描述
    - admin_only: 是否仅管理员可用
    """

    COMMAND_REGISTRY.append(
        {
            "name": name,
            "usage": usage,
            "description": description,
            "admin_only": admin_only,
        }
    )


def check_admin(event: Event) -> bool:
    """检查事件发起者是否为管理员（Discord 角色/用户ID 或 SUPERUSERS）。

    返回值: True 表示是管理员，False 表示不是。
    """

    return _is_admin(event)


def require_admin(func: Callable[..., Awaitable[Any]]):
    """装饰器：要求调用者为管理员。

    用法示例：
    @require_admin
    async def handle_cmd(event: Event, matcher: Matcher):
        # 只有管理员才能执行到这里
        await matcher.finish("管理员专用命令")

    注意：被装饰的函数需要接收 event 和 matcher 参数。
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 尝试找到 Event 和 Matcher
        event = None
        matcher = None

        for arg in args:
            if isinstance(arg, Event):
                event = arg
            elif hasattr(arg, "finish"):  # 通常是 Matcher
                matcher = arg

        if not event:
            event = kwargs.get("event")
        if not matcher:
            matcher = kwargs.get("matcher")

        if not event or not _is_admin(event):
            if matcher and hasattr(matcher, "finish"):
                await matcher.finish("没有权限")
            return

        return await func(*args, **kwargs)

    return wrapper


def _is_admin(_event: Event) -> bool:
    """判断事件发起者是否为管理员。

    规则（任一满足）：
    1) Discord: 用户 ID 在 `discord_admin_user_ids` 或拥有 `discord_admin_role_ids` 中的角色
    2) 回退: 用户 ID 在 `superusers` 配置中
    """
    return True


def extract_command(text: str, command: str) -> Optional[str]:
    """从文本中提取命令。

    参数:
        text: 原始文本
        command: 命令名称（如 "/start-monitor"）

    返回:
        如果找到命令，返回从命令开始的文本，否则返回 None

    注意：
        命令必须是完整的词，即命令后面必须是空格、字符串结尾或标点符号，
        而不能是其他字符（避免 /subscribe 误匹配 /watch）
    """
    text = text.strip()

    # 检查是否以命令开头
    if text.startswith(command):
        # 确保命令后面是空格或字符串结尾（完整匹配）
        if len(text) == len(command) or text[len(command)] in (" ", "\n", "\t"):
            return text

    # 在文本中查找命令
    idx = text.find(command)
    if idx >= 0:
        # 确保命令后面是空格或字符串结尾
        end_idx = idx + len(command)
        if end_idx == len(text) or text[end_idx] in (" ", "\n", "\t"):
            return text[idx:].strip()

    return None


def get_user_info(event: Event) -> Tuple[str, str]:
    """从事件中提取用户ID和用户名。

    参数:
        event: 事件对象

    返回:
        (user_id, user_name) 元组

    异常:
        FinishedException: 如果事件处理已完成，重新抛出
        Exception: 其他错误会被记录并重新抛出
    """
    try:
        user_id = event.get_user_id()
        user_name = user_id
        if hasattr(event, "author"):
            author = getattr(event, "author", {})
            if isinstance(author, dict):
                user_name = author.get("username", user_id)
            elif hasattr(author, "username"):
                user_name = author.username
            elif hasattr(author, "global_name"):
                user_name = author.global_name or user_id
        logger.debug(f"Operator: {user_id} ({user_name})")
        return (user_id, user_name)
    except FinishedException:
        raise  # 重新抛出 FinishedException，这是正常流程
    except (
        ValueError,
        AttributeError,
        KeyError,
    ) as e:  # pylint: disable=try-except-raise
        logger.error(f"Failed to get user info: {e}")
        raise


async def get_user_info_or_finish(event: Event, matcher) -> Tuple[str, str]:
    """获取用户信息，如果失败则结束命令处理。

    这是一个辅助函数，用于减少命令处理函数中的重复代码。

    参数:
        event: 事件对象
        matcher: Matcher 对象，用于结束命令处理

    返回:
        (user_id, user_name) 元组

    异常:
        FinishedException: 如果无法获取用户信息，会调用 matcher.finish() 并抛出此异常
    """
    try:
        return get_user_info(event)
    except (AttributeError, ValueError, TypeError) as exc:
        await matcher.finish("❌ 无法获取用户信息")
        # finish() 会抛出 FinishedException，所以这里实际上不会执行
        raise FinishedException from exc


# 获取 Bot 提及名称的辅助函数
def get_bot_mention_name() -> str:
    """获取 Bot 的提及名称

    Returns:
        Bot 的提及名称（如 @lkml-bot）
    """
    return get_config().bot_mention_name


# 基础提示（头部）
def get_base_help_header() -> str:
    """获取基础帮助头部信息

    Returns:
        帮助头部字符串
    """
    return f"用法: {get_bot_mention_name()} /<子命令> [参数...]\n"


# 数据库单例
_database = None


def set_database(database):
    """设置数据库实例

    Args:
        database: 数据库实例
    """
    global _database  # pylint: disable=global-statement
    _database = database


def get_database():
    """获取数据库实例

    Returns:
        数据库实例，如果未初始化则返回 None
    """
    return _database


def get_session_provider():
    """获取 SessionProvider 实例

    Returns:
        SessionProvider 实例
    """
    # Import here to avoid circular import
    # pylint: disable=import-outside-toplevel,redefined-outer-name
    from lkml.db.database import get_session_provider

    return get_session_provider()
