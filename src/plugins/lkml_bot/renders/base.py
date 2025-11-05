"""渲染器基类

定义了消息渲染的抽象接口和通用实现，支持不同平台的消息格式转换。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional
import re
import html

from lkml.feed import FeedEntry, SubsystemUpdate


class BaseRenderer(ABC):  # pylint: disable=too-few-public-methods
    """渲染器基类

    定义了渲染子系统更新消息的抽象接口，不同平台可实现各自的渲染逻辑。
    这是抽象基类，只定义核心接口方法。
    """

    @abstractmethod
    def render(
        self, subsystem: str, update_data: SubsystemUpdate
    ) -> Any:  # 不同实现返回不同类型（dict、str等）
        """渲染子系统更新消息

        Args:
            subsystem: 子系统名称
            update_data: 更新数据

        Returns:
            渲染后的消息（格式取决于具体实现）
        """


class BaseTextRenderer(BaseRenderer):
    """文本渲染器基类（提供通用文本格式化方法）

    为文本渲染提供通用方法，如格式化统计信息、邮件条目列表等。
    """

    def _format_stats(self, update_data: SubsystemUpdate) -> list[str]:
        """格式化统计信息

        Args:
            update_data: 更新数据

        Returns:
            格式化的统计信息列表
        """
        stats: list[str] = []
        if update_data.new_count > 0:
            stats.append(f"🆕 新邮件: **{update_data.new_count}** 条")
        if update_data.reply_count > 0:
            stats.append(f"💬 回复: **{update_data.reply_count}** 条")
        return stats

    def _format_entries(
        self, entries: list[FeedEntry], display_count: int = 5
    ) -> list[str]:
        """格式化邮件条目列表

        Args:
            entries: 邮件条目列表
            display_count: 最多显示的条目数

        Returns:
            格式化后的文本行列表
        """
        lines: list[str] = []
        display_count = min(display_count, len(entries))

        if display_count > 0:
            lines.append("**最近更新:**")
            lines.append("")

            for i, entry in enumerate(entries[:display_count], 1):
                # 主题（如果有链接，添加链接）
                subject_line = f"**{i}.** "
                if entry.url:
                    subject_line += f"[{entry.subject}]({entry.url})"
                else:
                    subject_line += entry.subject
                lines.append(subject_line)

                # 使用 _get_author 获取作者信息
                author, email = self._get_author(entry)

                # 作者信息
                if email:
                    author_info = f"👤 `{author}` <{email}>"
                else:
                    author_info = f"👤 `{author}`"
                lines.append(author_info)

                # 仅当非回复且为 PATCH 时展示正文节选与 Thread overview
                is_reply = bool(getattr(entry, "is_reply", False))
                is_patch = bool(getattr(entry, "is_patch", False))

                # 仅非回复且为 PATCH 展示正文节选
                if (not is_reply) and is_patch:
                    excerpt = self._get_excerpt(entry, max_chars=600, max_lines=8)
                    if excerpt:
                        for ex_line in excerpt.splitlines():
                            lines.append(f"> {ex_line}")
                lines.append("")

            if len(entries) > display_count:
                remaining = len(entries) - display_count
                lines.append(f"*...还有 {remaining} 条邮件未显示*")

        return lines

    def _get_author(self, entry: FeedEntry) -> tuple[str, Optional[str]]:
        """获取作者信息，返回 (author, email)

        Args:
            entry: 邮件条目

        Returns:
            (作者名, 邮箱地址) 元组
        """
        author = (
            entry.author
            if entry.author
            else (entry.metadata.sender if entry.metadata.sender else "Unknown")
        )
        email = (
            entry.email
            if entry.email
            else (entry.metadata.sender_email if entry.metadata.sender_email else None)
        )
        return author, email

    def _clean_text(self, raw: str) -> str:
        """将 HTML/富文本转换为接近 lore 的纯文本风格。

        - 保留段落与换行（<p>、<br> 等转为 \n）
        - 列表项转换为以 "- " 开头
        - 删除其他标签但保留其文本
        - 解码 HTML 实体
        - 规范空白：去除行尾空格，合并多余空行
        """
        if not raw:
            return ""
        try:
            text = html.unescape(raw)
            # 标准化换行
            text = text.replace("\r\n", "\n").replace("\r", "\n")

            # 块级标签前后放换行，尽量保留段落感
            block_tags = [
                "p",
                "div",
                "section",
                "article",
                "header",
                "footer",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "pre",
                "code",
                "blockquote",
                "ul",
                "ol",
                "li",
            ]
            for tag in ["br", "br/"]:
                text = re.sub(rf"<\s*{tag}[^>]*>", "\n", text, flags=re.IGNORECASE)
            for tag in block_tags:
                # 开始/结束标签都作为换行分隔
                text = re.sub(rf"<\s*/?{tag}[^>]*>", "\n", text, flags=re.IGNORECASE)

            # 去掉剩余标签
            text = re.sub(r"<[^>]+>", "", text)

            # 去除每行首尾空白
            lines = [ln.strip() for ln in text.split("\n")]
            # 合并多空行，最多保留一个
            cleaned_lines: list[str] = []
            empty_streak = 0
            for ln in lines:
                if ln == "":
                    empty_streak += 1
                else:
                    empty_streak = 0
                if empty_streak <= 1:
                    cleaned_lines.append(ln)
            text = "\n".join(cleaned_lines).strip()
            return text
        except (AttributeError, TypeError, ValueError):
            return raw.strip()

    def _get_excerpt(
        self, entry: FeedEntry, max_chars: int = 600, max_lines: int = 8
    ) -> str:
        """从 summary/content 中抽取节选，限制长度。

        优先使用 summary，其次 content。
        """
        source = entry.content.summary or entry.metadata.content or ""
        if not source:
            return ""
        text = self._clean_text(source)
        # 先按行裁剪，尽量保留段落语义
        out_lines: list[str] = []
        total_chars = 0
        truncated = False
        for ln in text.splitlines():
            if ln.strip() == "":
                # 空行也计算一字符作为分隔
                add_len = 1
            else:
                add_len = len(ln)
            if (len(out_lines) + 1 > max_lines) or (total_chars + add_len > max_chars):
                truncated = True
                break
            out_lines.append(ln)
            total_chars += add_len

        result = "\n".join(out_lines).rstrip()
        if truncated:
            # 在最后一行尾部添加省略号
            if result.endswith("\n"):
                result = result + "…"
            else:
                result = result + "…"
        return result

    def render_text(self, subsystem: str, update_data: SubsystemUpdate) -> str:
        """渲染为文本格式（通用实现，各平台可覆盖）

        Args:
            subsystem: 子系统名称
            update_data: 更新数据

        Returns:
            渲染后的文本字符串
        """
        lines: list[str] = []

        # 标题行
        lines.append(f"📧 **{subsystem.upper()} 邮件列表更新**")
        lines.append("")

        # 统计信息
        stats = self._format_stats(update_data)
        if stats:
            lines.append(" | ".join(stats))
            lines.append("")

        # 显示最近几条新邮件的摘要
        entry_lines = self._format_entries(update_data.entries)
        lines.extend(entry_lines)

        return "\n".join(lines)
