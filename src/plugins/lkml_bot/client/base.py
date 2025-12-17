"""平台客户端基类

定义统一的平台客户端接口，采用做法B：拆分为 PatchCardClient 和 ThreadClient。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class PatchCardClient(ABC):
    """Patch Card 客户端接口

    所有平台都必须实现这个接口，用于发送 Patch Card。
    """

    @abstractmethod
    async def send_patch_card(self, rendered_data: Any) -> Optional[str]:
        """发送 Patch Card

        Args:
            rendered_data: 渲染后的数据（平台特定格式）

        Returns:
            平台消息 ID，失败返回 None
        """
        raise NotImplementedError(
            "PatchCardClient.send_patch_card must be implemented by subclasses"
        )


class ThreadClient(ABC):
    """Thread 客户端接口

    只有支持 Thread 概念的平台才需要实现这个接口（如 Discord）。
    不支持 Thread 的平台可以实现为发送通知卡片（如 Feishu）。
    """

    @abstractmethod
    async def create_thread(
        self, thread_name: str, message_id: str
    ) -> Tuple[Optional[str], bool]:
        """创建 Thread（或发送 Thread 创建通知）

        Args:
            thread_name: Thread 名称
            message_id: 消息 ID（Thread 将从这条消息创建，或用于通知）

        Returns:
            (Thread ID 或通知消息 ID, is_thread_exists_error) 元组
            - 对于支持 Thread 的平台：返回 Thread ID
            - 对于不支持 Thread 的平台：可以返回通知消息 ID 或 None
        """
        raise NotImplementedError(
            "ThreadClient.create_thread must be implemented by subclasses"
        )

    @abstractmethod
    async def send_thread_overview(
        self, thread_id: str, overview_data: Any
    ) -> Dict[int, str]:
        """发送 Thread Overview（或发送 Thread 创建通知卡片）

        Args:
            thread_id: Thread ID（对于不支持 Thread 的平台，可以是任意标识符）
            overview_data: Thread Overview 数据

        Returns:
            {patch_index: message_id} 映射
            - 对于支持 Thread 的平台：返回每个子 patch 的消息 ID
            - 对于不支持 Thread 的平台：可以返回空字典或通知消息 ID
        """
        raise NotImplementedError(
            "ThreadClient.send_thread_overview must be implemented by subclasses"
        )

    @abstractmethod
    async def update_thread_overview(
        self, thread_id: str, message_id: str, overview_data: Any
    ) -> bool:
        """更新 Thread Overview（或发送 Thread 更新通知卡片）

        Args:
            thread_id: Thread ID（对于不支持 Thread 的平台，可以是任意标识符）
            message_id: 要更新的消息 ID（对于不支持 Thread 的平台，可以忽略）
            overview_data: Thread Overview 数据

        Returns:
            成功返回 True，失败返回 False
        """
        raise NotImplementedError(
            "ThreadClient.update_thread_overview must be implemented by subclasses"
        )

    @abstractmethod
    async def send_thread_update_notification(
        self, channel_id: str, thread_id: str, platform_message_id: Optional[str] = None
    ) -> bool:
        """发送 Thread 更新通知

        Args:
            channel_id: 频道 ID
            thread_id: Thread ID
            platform_message_id: Patch Card 的消息 ID（可选）

        Returns:
            成功返回 True，失败返回 False
        """
        raise NotImplementedError(
            "ThreadClient.send_thread_update_notification must be implemented by subclasses"
        )
