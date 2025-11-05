"""消息适配器基类"""

from abc import ABC, abstractmethod

from lkml.feed import SubsystemUpdate


class MessageAdapter(ABC):  # pylint: disable=too-few-public-methods
    """消息适配器抽象基类

    这是抽象基类，只定义核心接口方法。
    """

    @abstractmethod
    async def send_subsystem_update(
        self, subsystem: str, update_data: SubsystemUpdate
    ) -> None:
        """发送子系统更新到对应平台

        Args:
            subsystem: 子系统名称
            update_data: 更新数据
        """
