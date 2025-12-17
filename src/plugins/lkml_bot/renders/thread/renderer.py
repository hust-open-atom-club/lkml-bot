"""Thread 渲染器

Plugins 层渲染器：只负责渲染 Thread Overview。
所有业务逻辑由 Service 层处理，发送由客户端处理。
"""

from typing import Dict

from lkml.service import FeedMessage
from lkml.service.types import (
    ReplyMapEntry,
    SubPatchOverviewData,
    ThreadOverviewData,
)

from ..types import DiscordRenderedThreadMessage, DiscordRenderedThreadOverview


class ThreadOverviewRenderer:
    """Thread Overview 渲染器

    职责：
    1. 将 ThreadOverviewData 渲染成 Discord 格式
    2. 仅此而已

    不做：
    - 数据查询
    - 业务逻辑判断
    - 数据库操作
    - 发送消息（由客户端负责）
    """

    def __init__(self, config):
        """初始化渲染器

        Args:
            config: 配置对象（保留以便未来扩展）
        """
        self.config = config

    def render(
        self, overview_data: ThreadOverviewData
    ) -> DiscordRenderedThreadOverview:
        """渲染 Thread Overview 为 Discord 格式（不发送）

        为每个 PATCH 渲染一条独立的消息。
        - 系列 PATCH：为每个子 PATCH 渲染一条消息
        - 单 PATCH：渲染一条 overview 消息

        Args:
            overview_data: Thread Overview 数据

        Returns:
            DiscordRenderedThreadOverview 渲染结果
        """

        messages: Dict[int, DiscordRenderedThreadMessage] = {}

        # 使用 service 层准备好的 sub_patch_overviews
        if overview_data.sub_patch_overviews:
            for sub_overview in overview_data.sub_patch_overviews:
                patch = sub_overview.patch
                patch_index = patch.patch_index

                # 渲染子 PATCH 消息
                patch_content = self._render_sub_patch(sub_overview)
                patch_content += "\n\n---\n"

                messages[patch_index] = DiscordRenderedThreadMessage(
                    content=patch_content, embed=None
                )

        return DiscordRenderedThreadOverview(messages=messages)

    def render_sub_patch(
        self, sub_overview: SubPatchOverviewData
    ) -> DiscordRenderedThreadMessage:
        """渲染单个子 PATCH 消息（用于更新）

        Args:
            sub_overview: 子 PATCH 的完整 Overview 数据

        Returns:
            DiscordRenderedThreadMessage 渲染结果
        """
        content = self._render_sub_patch(sub_overview)
        content += "\n\n---\n"
        return DiscordRenderedThreadMessage(content=content, embed=None)

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
        subject = reply.subject.split("] ", 1)[0] + "]"
        reply_time = reply.received_at.strftime("%Y-%m-%d %H:%M")
        author = reply.author.split(" (", 1)[0] if reply.author else "Unknown"

        lines.append(f"{indent}\\` {reply_time} [{subject}]({reply.url}) {author}")

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
