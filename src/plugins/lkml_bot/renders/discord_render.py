"""Discord 平台渲染器

实现 Discord Embed 格式的消息渲染。
"""

from lkml.feed import SubsystemUpdate
from .base import BaseTextRenderer


class DiscordRenderer(BaseTextRenderer):
    """Discord 平台渲染器

    将子系统更新渲染为 Discord Embed 格式，使用颜色区分不同子系统。
    """

    def render(self, subsystem: str, update_data: SubsystemUpdate) -> dict:
        """渲染为 Discord Embed 格式

        Args:
            subsystem: 子系统名称
            update_data: 更新数据

        Returns:
            Discord Embed 字典
        """
        # 设置颜色（根据子系统类型）
        color_map = {
            "lkml": 0x5865F2,  # Discord蓝
            "rust-for-linux": 0xCE412B,  # Rust橙色
            "netdev": 0x3498DB,  # 蓝色
            "dri-devel": 0xE74C3C,  # 红色
        }
        color = color_map.get(subsystem, 0x5865F2)  # Discord蓝作为默认

        # 构建描述内容
        description_parts = []

        # 统计信息
        stats = self._format_stats(update_data)
        if stats:
            description_parts.append(" | ".join(stats))
            description_parts.append("")

        # 显示最近几条新邮件的摘要
        entry_lines = self._format_entries(update_data.entries)
        description_parts.extend(entry_lines)

        embed = {
            "title": f"📧 {subsystem.upper()} 邮件列表更新",
            "description": (
                "\n".join(description_parts) if description_parts else "无新更新"
            ),
            "color": color,
            "footer": {"text": "LKML Bot"},
        }

        return embed
