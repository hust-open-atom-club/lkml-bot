"""Feishu 线程概览渲染器

只负责渲染 Thread Overview 为 Feishu 卡片格式。
发送由客户端负责。
"""

from lkml.service.types import SubPatchOverviewData, ThreadOverviewData

from ..types import FeishuRenderedThreadNotification


class FeishuThreadOverviewRenderer:  # pylint: disable=too-few-public-methods
    """Feishu 平台 ThreadOverview 渲染器（只负责渲染，不负责发送）"""

    def __init__(self, config):
        self.config = config  # 目前未使用，保留以便未来扩展

    def render_create_notification(
        self, overview_data: ThreadOverviewData
    ) -> FeishuRenderedThreadNotification:
        """渲染 Thread 创建通知卡片（不发送）

        Args:
            overview_data: 线程概览数据

        Returns:
            FeishuRenderedThreadNotification 渲染结果
        """
        subject = overview_data.patch_card.subject[:200]
        patch_card_link = overview_data.patch_card.url or ""

        lines = []
        if overview_data.sub_patch_overviews:
            for sp in overview_data.sub_patch_overviews:
                subj = sp.patch.subject
                link = sp.patch.url or ""
                lines.append(f"  - [{subj}]({link}) ")
        sub_md = "\n".join(lines) if lines else ""

        card = {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",
                "config": {"update_multi": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"Thread Create: {subject}",
                    },
                    "subtitle": {"tag": "plain_text", "content": ""},
                    "text_tag_list": [
                        {
                            "tag": "text_tag",
                            "text": {
                                "tag": "plain_text",
                                "content": "Thread 已创建，有新回复时将自动推送",
                            },
                            "color": "green",
                        }
                    ],
                    "template": "green",
                    "padding": "12px 8px 12px 8px",
                },
                "body": {
                    "direction": "vertical",
                    "elements": [
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
                                            "content": ("• **Series** ：\n" + sub_md),
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
                        },
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
                                    "default_url": patch_card_link or "",
                                    "pc_url": "",
                                    "ios_url": "",
                                    "android_url": "",
                                }
                            ],
                            "margin": "4px 0px 4px 0px",
                        },
                    ],
                },
            },
        }

        return FeishuRenderedThreadNotification(card=card)

    def render_update_notification(
        self, sub_overview: SubPatchOverviewData
    ) -> FeishuRenderedThreadNotification:
        """渲染 Thread 更新通知卡片（不发送）

        Args:
            sub_overview: 子补丁概览数据

        Returns:
            FeishuRenderedThreadNotification 渲染结果
        """
        subj = sub_overview.patch.subject[:200]
        link = sub_overview.patch.url or ""

        card = {
            "msg_type": "interactive",
            "card": {
                "schema": "2.0",
                "config": {"update_multi": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"Thread Reply: {subj}",
                    },
                    "subtitle": {"tag": "plain_text", "content": ""},
                    "text_tag_list": [
                        {
                            "tag": "text_tag",
                            "text": {"tag": "plain_text", "content": "有回复"},
                            "color": "green",
                        }
                    ],
                    "template": "green",
                    "padding": "12px 8px 12px 8px",
                },
                "body": {
                    "direction": "vertical",
                    "elements": [
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
                                    "default_url": link or "",
                                    "pc_url": "",
                                    "ios_url": "",
                                    "android_url": "",
                                }
                            ],
                            "margin": "4px 0px 4px 0px",
                        },
                    ],
                },
            },
        }

        return FeishuRenderedThreadNotification(card=card)
