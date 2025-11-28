"""Repository 模块

提供数据库访问的仓储层实现。
"""

from .email_message_repository import EmailMessageData, EmailMessageRepository
from .feed_message_repository import FeedMessageData, FeedMessageRepository
from .patch_card_repository import PatchCardData, PatchCardRepository
from .patch_thread_repository import PatchThreadData, PatchThreadRepository
from .subsystem_repository import SUBSYSTEM_REPO

__all__ = [
    "EmailMessageData",
    "EmailMessageRepository",
    # Feed Message
    "FeedMessageData",
    "FeedMessageRepository",
    # Patch Card
    "PatchCardData",
    "PatchCardRepository",
    # Patch Thread
    "PatchThreadData",
    "PatchThreadRepository",
    # Subsystem
    "SUBSYSTEM_REPO",
]
