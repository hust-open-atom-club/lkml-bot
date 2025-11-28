"""Thread 渲染器

Plugins 层渲染器：只负责渲染 Thread Overview 并发送到 Discord。
所有业务逻辑由 Service 层处理。
"""

import asyncio
from typing import Dict

from nonebot.log import logger

from lkml.service import FeedMessage
from lkml.service.types import (
    ReplyMapEntry,
    SubPatchOverviewData,
    ThreadOverviewData,
)

from ...client import (
    send_message_to_thread as api_send_message_to_thread,
    update_message_in_thread,
)


class ThreadOverviewRenderer:
    """Thread Overview 渲染器

    职责：
    1. 将 ThreadOverviewData 渲染成文本
    2. 发送到 Discord Thread
    3. 仅此而已

    不做：
    - 数据查询
    - 业务逻辑判断
    - 数据库操作
    """

    def __init__(self, config):
        """初始化渲染器

        Args:
            config: 配置对象
        """
        self.config = config

    async def render_and_send(
        self, thread_id: str, overview_data: ThreadOverviewData
    ) -> dict:
        """渲染并发送 Thread Overview

        为每个 PATCH 发送一条独立的消息。
        - 系列 PATCH：为每个子 PATCH 发送一条消息
        - 单 PATCH：发送一条 overview 消息

        Args:
            thread_id: Discord Thread ID
            overview_data: Thread Overview 数据

        Returns:
            PATCH 消息映射 {patch_index: message_id}，失败返回空字典
        """
        try:
            sub_patch_messages = {}
            patch_card = overview_data.patch_card

            # 使用 service 层准备好的 sub_patch_overviews
            if overview_data.sub_patch_overviews:
                sub_patch_overviews = overview_data.sub_patch_overviews

                logger.info(
                    f"Rendering {len(sub_patch_overviews)} patches for thread {thread_id}"
                )

                for idx, sub_overview in enumerate(sub_patch_overviews):
                    patch = sub_overview.patch
                    patch_index = patch.patch_index
                    subject = patch.subject[:60]

                    # 渲染子 PATCH 消息（直接使用 service 层准备好的数据）
                    patch_content = self._render_sub_patch(sub_overview)

                    # 如果不是最后一个 PATCH，添加分割线
                    if idx < len(sub_patch_overviews) - 1:
                        patch_content += "\n\n---\n"

                    # 发送消息
                    logger.debug(
                        f"Sending sub-patch [{patch_index}] to thread {thread_id}: {subject}"
                    )
                    msg_id = await api_send_message_to_thread(
                        self.config, thread_id, patch_content
                    )

                    if msg_id:
                        sub_patch_messages[patch_index] = msg_id
                        logger.info(
                            f"✓ Sent sub-patch [{patch_index}] to thread {thread_id}, "
                            f"message_id={msg_id}"
                        )
                    else:
                        logger.warning(
                            f"✗ Failed to send sub-patch [{patch_index}] to thread {thread_id}: {subject}"
                        )

                    # 添加延迟以避免触发 Discord rate limit
                    # 为每个子 PATCH 消息之间添加 200ms 延迟
                    await asyncio.sleep(0.2)
            else:
                logger.warning(
                    f"No sub_patch_overviews available in overview_data for thread {thread_id}"
                )

            logger.info(
                f"Sent {len(sub_patch_messages)} patch messages to thread {thread_id}"
            )
            return sub_patch_messages

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to render and send multi-message overview: {e}", exc_info=True
            )
            return {}

    def _render_sub_patch(self, sub_overview: SubPatchOverviewData) -> str:
        """渲染单个子 PATCH 消息

        格式：
        [subject](url)

        ` 时间 作者
            ` 时间 作者  # 子回复
        ` 时间 作者

        Args:
            sub_overview: 子 PATCH 的完整 Overview 数据（由 service 层准备）

        Returns:
            渲染后的子 PATCH 文本
        """
        lines = []
        patch = sub_overview.patch

        lines.append(f"[{patch.subject}]({patch.url})")
        lines.append("")  # 空行

        # 使用 service 层准备好的回复层级结构
        reply_hierarchy = sub_overview.reply_hierarchy
        reply_map = reply_hierarchy.reply_map
        root_replies = reply_hierarchy.root_replies

        if root_replies:
            # 为该 PATCH 的每个顶层回复构建层级树
            for root_reply_id in root_replies:
                if root_reply_id in reply_map:
                    root_reply = reply_map[root_reply_id].reply
                    reply_lines = self._format_reply_tree(
                        root_reply, reply_map, level=0
                    )
                    lines.extend(reply_lines)
        else:
            lines.append("_(No replies)_")

        return "\n".join(lines)

    def _format_reply_tree(
        self, reply: FeedMessage, reply_map: Dict[str, ReplyMapEntry], level: int
    ) -> list:
        """递归格式化回复树

        格式：
        ` 时间 作者 (邮箱)
            ` 时间 作者 (邮箱)  # level=1
                ` 时间 作者 (邮箱)  # level=2

        Args:
            reply: 回复对象
            reply_map: 回复映射 {message_id: ReplyMapEntry}
            level: 层级深度（0 = 顶层）

        Returns:
            格式化后的行列表
        """
        lines = []

        # 缩进：使用 tab 字符
        indent = "\t" * level

        # 格式化当前回复：` 时间 作者 (邮箱)
        reply_time = reply.received_at.strftime("%Y-%m-%d %H:%M")
        author = reply.author if reply.author else "Unknown"

        lines.append(f"{indent}[` {reply_time} {author}]({reply.url})")

        # 递归处理子回复
        message_id = reply.message_id_header
        if message_id in reply_map:
            reply_entry = reply_map[message_id]
            children_ids = reply_entry.children
            for child_id in children_ids:
                if child_id in reply_map:
                    child_reply = reply_map[child_id].reply
                    child_lines = self._format_reply_tree(
                        child_reply, reply_map, level + 1
                    )
                    lines.extend(child_lines)

        return lines

    async def update_sub_patch_message(
        self,
        thread_id: str,
        message_id: str,
        sub_overview: SubPatchOverviewData,
    ) -> bool:
        """更新单个子 PATCH 消息

        Args:
            thread_id: Discord Thread ID
            message_id: 要更新的消息 ID
            sub_overview: 子 PATCH 的完整 Overview 数据（由 service 层准备）

        Returns:
            是否更新成功
        """
        try:
            # 直接使用 service 层准备好的数据渲染
            content = self._render_sub_patch(sub_overview)

            # 更新消息
            success = await update_message_in_thread(
                self.config, thread_id, message_id, content
            )

            if success:
                logger.info(
                    f"Updated sub-patch message in thread {thread_id}, message_id={message_id}"
                )
            else:
                logger.error(
                    f"Failed to update sub-patch message in thread {thread_id}"
                )

            return success

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to update sub-patch message: {e}", exc_info=True)
            return False
