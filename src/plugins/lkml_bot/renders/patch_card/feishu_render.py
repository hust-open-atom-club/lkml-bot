"""Feishu 平台渲染器"""

from lkml.service import PatchCard

from ..types import FeishuRenderedPatchCard


class FeishuPatchCardRenderer:  # pylint: disable=too-few-public-methods
    """Feishu 平台 PatchCard 渲染器（只负责渲染，不负责发送）"""

    def __init__(self, config):
        self.config = config  # 目前未使用，保留以便未来扩展

    def render(self, patch_card: PatchCard) -> FeishuRenderedPatchCard:
        """渲染 PatchCard 为 Feishu 卡片（不发送）

        Args:
            patch_card: 待渲染的 PatchCard 对象

        Returns:
            FeishuRenderedPatchCard 渲染结果
        """
        header_title = patch_card.subject[:200]
        date_str = (
            patch_card.expires_at.strftime("%Y-%m-%d %H:%M UTC")
            if patch_card.expires_at
            else ""
        )
        author_str = patch_card.author or "Unknown"

        # 是否为系列 PATCH（Single Patch 时不显示 Series 信息）
        is_series = bool(
            patch_card.is_series_patch
            or (patch_card.patch_total is not None and patch_card.patch_total > 1)
        )

        # 只有系列 PATCH 时才构建 Series 相关信息
        subpatch_md, received = self._build_series_markdown_and_received(
            patch_card, is_series
        )

        # 基础信息（Single Patch / Series 共用）
        base_content_lines = [
            f"• **Subsystem** ：{patch_card.subsystem_name}",
            f"• **Date** ：{date_str}",
            f"• **Author** ：{author_str}",
        ]

        # 只有系列 PATCH 时才显示统计信息
        if is_series:
            total_patches = patch_card.patch_total or 0
            base_content_lines.append(f"• **Total Patches** ：{total_patches}")
            base_content_lines.append(f"• **Received** ：{received}/{total_patches}")

        base_content = "\n".join(base_content_lines)

        card = {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",
                "config": {"update_multi": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"{header_title}",
                    },
                    "subtitle": {"tag": "plain_text", "content": ""},
                    "text_tag_list": [
                        {
                            "tag": "text_tag",
                            "text": {"tag": "plain_text", "content": "新提交"},
                            "color": "blue",
                        }
                    ],
                    "template": "blue",
                    "padding": "12px 8px 12px 8px",
                },
                "body": {
                    "direction": "vertical",
                    "elements": [],
                },
            },
        }

        elements = [
            {
                "tag": "column_set",
                "flex_mode": "stretch",
                "horizontal_spacing": "8px",
                "horizontal_align": "left",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "background_style": "blue-50",
                        "elements": [
                            {
                                "tag": "markdown",
                                "content": base_content,
                                "text_align": "left",
                                "text_size": "normal",
                            }
                        ],
                        "padding": "12px 12px 12px 12px",
                        "vertical_spacing": "8px",
                        "horizontal_align": "left",
                        "vertical_align": "top",
                        "weight": 1,
                    }
                ],
                "margin": "0px 0px 0px 0px",
            }
        ]

        # 只有系列 PATCH 时才添加 Series 模块
        if is_series and subpatch_md:
            elements.append(
                {
                    "tag": "column_set",
                    "flex_mode": "stretch",
                    "horizontal_spacing": "8px",
                    "horizontal_align": "left",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "background_style": "grey-50",
                            "elements": [
                                {
                                    "tag": "markdown",
                                    "content": ("• **Series** ：\n" + subpatch_md),
                                    "text_align": "left",
                                    "text_size": "normal",
                                }
                            ],
                            "padding": "12px 12px 12px 12px",
                            "vertical_spacing": "8px",
                            "horizontal_align": "left",
                            "vertical_align": "top",
                            "weight": 1,
                        }
                    ],
                    "margin": "0px 0px 0px 0px",
                }
            )

        # 查看详情按钮（始终存在）
        elements.append(
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "查看补丁详情",
                },
                "type": "primary_filled",
                "width": "fill",
                "behaviors": [
                    {
                        "type": "open_url",
                        "default_url": patch_card.url or "",
                        "pc_url": "",
                        "ios_url": "",
                        "android_url": "",
                    }
                ],
                "margin": "4px 0px 4px 0px",
            }
        )

        card["card"]["body"]["elements"] = elements

        return FeishuRenderedPatchCard(card=card)

    def _build_series_markdown_and_received(
        self, patch_card: PatchCard, is_series: bool
    ) -> tuple[str, int]:
        """构建系列 PATCH 的 Markdown 列表及计数。"""
        if not (is_series and patch_card.series_patches):
            return "", 0

        subpatch_lines = []
        for series_patch in patch_card.series_patches:
            subject = series_patch.subject
            link = series_patch.url or ""
            subpatch_lines.append(f"  - [{subject}]({link}) ")

        return "\n".join(subpatch_lines), len(patch_card.series_patches)
