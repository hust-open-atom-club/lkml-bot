"""Vger 子系统来源

提供统一函数以获取可用的 vger 子系统名称列表，至于数据从哪里来（内存、配置、数据库、
外部服务等）由实现决定，调用方无需关心。
"""

import asyncio
import re
from typing import List, Optional

from nonebot.log import logger

VGER_SUBSYSTEMS_URL = "https://subspace.kernel.org/vger.kernel.org.html"

# 模块级缓存变量
_vger_subsystems_cache: Optional[List[str]] = None

# 表头关键词（需要排除）
TABLE_HEADER_KEYWORDS = ("name", "description", "fl", "addresses", "subs")
# 需要排除的前缀
EXCLUDED_PREFIXES = ("sub", "unsub", "post", "archive", "http", "mailto")


def _is_valid_subsystem_name(name: str) -> bool:
    """验证子系统名称是否有效

    Args:
        name: 子系统名称

    Returns:
        如果名称有效返回 True，否则返回 False
    """
    if not name or name.isdigit() or len(name) <= 1:
        return False

    name_lower = name.lower()
    if name_lower in TABLE_HEADER_KEYWORDS:
        return False

    if name.startswith(EXCLUDED_PREFIXES):
        return False

    if "/" in name or "@" in name or " " in name:
        return False

    # 验证格式：小写字母、数字、连字符
    return bool(re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$", name))


# 每日更新间隔（秒）：24 小时 = 86400 秒
DAILY_UPDATE_INTERVAL = 24 * 60 * 60


def get_vger_subsystems() -> List[str]:
    """从模块级缓存获取 vger 子系统列表

    Bot 的服务器缓存会存储所有从 vger 获取的内核子系统信息。
    此函数从模块级缓存变量中读取缓存的子系统列表。

    Returns:
        子系统名称列表，例如: ["lkml", "netdev", "dri-devel", ...]
        如果缓存中没有数据，返回空列表。
    """
    try:
        if _vger_subsystems_cache is not None and isinstance(
            _vger_subsystems_cache, list
        ):
            return _vger_subsystems_cache
        logger.warning(
            "Vger subsystems cache not found or invalid, returning empty list"
        )
        return []
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to get vger subsystems from cache: {e}", exc_info=True)
        return []


async def fetch_vger_subsystems() -> List[str]:
    """从 vger.kernel.org 网页抓取子系统列表

    从 https://subspace.kernel.org/vger.kernel.org.html 解析 HTML 表格，
    提取所有子系统的名称。

    Returns:
        子系统名称列表，例如: ["lkml", "netdev", "dri-devel", ...]
        如果抓取失败，返回空列表。
    """
    try:
        import httpx  # pylint: disable=import-outside-toplevel

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(VGER_SUBSYSTEMS_URL)
            response.raise_for_status()
            html_content = response.text

        # 使用正则表达式从 HTML 表格中提取子系统名称
        # 表格格式: 每行 <tr> 包含多个 <td>，第一列是子系统名称
        # 匹配每行的第一个 <td> 标签内容（可能是纯文本或链接）
        # 模式1: <td>name</td> (纯文本)
        # 模式2: <td><a ...>name</a></td> (链接)
        # 模式3: <td>name</td> (可能包含空白)

        # 先提取所有表格行
        table_rows_pattern = r"<tr[^>]*>(.*?)</tr>"
        rows = re.findall(table_rows_pattern, html_content, re.DOTALL | re.IGNORECASE)

        subsystems = []
        for row in rows:
            # 提取第一个 <td> 的内容
            # 匹配 <th>...</th>，考虑可能包含 <a> 标签的情况
            first_th_pattern = r"<th[^>]*>(.*?)</th>"
            first_th_match = re.search(first_th_pattern, row, re.DOTALL | re.IGNORECASE)
            if not first_th_match:
                continue

            th_content = first_th_match.group(1).strip()
            # 如果包含 <a> 标签，提取链接文本
            link_pattern = r"<a[^>]*>(.*?)</a>"
            link_match = re.search(link_pattern, th_content, re.IGNORECASE)
            if link_match:
                name = link_match.group(1).strip()
            else:
                name = re.sub(r"<[^>]+>", "", th_content).strip()  # 移除所有 HTML 标签

            # 验证子系统名称格式：小写字母、数字、连字符
            # 排除表头、空字符串、数字、URL、邮箱等
            if _is_valid_subsystem_name(name):
                subsystems.append(name)

        # 去重并排序
        subsystems = sorted(list(set(subsystems)))

        logger.info(
            f"Fetched {len(subsystems)} vger subsystems from {VGER_SUBSYSTEMS_URL}"
        )
        return subsystems

    except ImportError:
        logger.error("httpx is not installed, cannot fetch vger subsystems")
        return []
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to fetch vger subsystems: {e}", exc_info=True)
        return []


async def update_vger_subsystems_cache() -> bool:
    """更新模块级缓存中的 vger 子系统列表

    从 vger.kernel.org 抓取最新的子系统列表，并存储到模块级缓存变量中。

    Returns:
        如果更新成功返回 True，否则返回 False。
    """
    global _vger_subsystems_cache  # pylint: disable=global-statement
    try:
        subsystems = await fetch_vger_subsystems()
        if not subsystems:
            logger.warning("No subsystems fetched, cache not updated")
            return False

        # 存储到模块级缓存变量
        _vger_subsystems_cache = subsystems
        logger.info(
            f"Updated vger subsystems cache with {len(subsystems)} subsystems: "
            f"{', '.join(subsystems[:10])}{'...' if len(subsystems) > 10 else ''}"
        )
        return True
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to update vger subsystems cache: {e}", exc_info=True)
        return False


async def daily_update_task() -> None:
    """每日更新 vger 子系统缓存的定时任务

    此任务会每天自动执行一次，更新服务器缓存中的 vger 子系统列表。
    """
    logger.info("Starting daily vger subsystems cache update task")

    while True:
        try:
            # 等待一天（24小时）
            await asyncio.sleep(DAILY_UPDATE_INTERVAL)

            logger.info("Running scheduled daily update of vger subsystems cache")
            success = await update_vger_subsystems_cache()
            if success:
                logger.info("Daily vger subsystems cache update completed successfully")
            else:
                logger.warning(
                    "Daily vger subsystems cache update failed, will retry tomorrow"
                )
        except asyncio.CancelledError:
            logger.info("Daily vger subsystems cache update task cancelled")
            break
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                f"Error in daily vger subsystems cache update task: {e}",
                exc_info=True,
            )
            # 出错时等待1小时后重试，避免连续失败
            await asyncio.sleep(3600)


def start_daily_update_task() -> asyncio.Task:
    """启动每日更新任务

    Returns:
        创建的 asyncio.Task 对象，可用于取消任务
    """
    task = asyncio.create_task(daily_update_task())
    logger.info("Daily vger subsystems cache update task started")
    return task
