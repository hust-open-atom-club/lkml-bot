"""Thread 服务

封装 Thread 相关的数据库操作和内容处理，提供业务逻辑层接口。
包括 Thread 的 CRUD 操作、回复处理、回复层级构建、PATCH 查找等功能。
Service 层通过依赖注入接受 Repository 实例。
"""

import logging
from datetime import datetime
from typing import Optional, Dict, List

from ..db.repo import (
    FeedMessageRepository,
    PatchCardRepository,
    PatchThreadData as RepoPatchThreadData,
    PatchThreadRepository,
)
from .types import (
    PatchThread,
    ThreadOverviewData,
    ReplyHierarchy,
    ReplyMapEntry,
    FeedMessage,
)

logger = logging.getLogger(__name__)


# ========== 回复处理辅助函数 ==========


def parse_reply_time(reply) -> Optional[datetime]:
    """解析回复时间

    Args:
        reply: EmailMessage 对象

    Returns:
        datetime 对象，如果解析失败则返回 None
    """
    if not reply.received_at:
        return None

    try:
        # FeedMessage.received_at 是 datetime 对象，直接返回
        reply_time = reply.received_at
        if reply_time.tzinfo:
            reply_time = reply_time.astimezone(datetime.now().astimezone().tzinfo)
        else:
            reply_time = reply_time.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return reply_time
    except (ValueError, TypeError):
        return None


def _extract_message_id_from_header(in_reply_to_header: Optional[str]) -> Optional[str]:
    """从 in_reply_to_header 中提取 message_id

    处理可能包含尖括号、多个 message_id 等情况

    Args:
        in_reply_to_header: in_reply_to 头部值

    Returns:
        提取的 message_id，如果无法提取则返回 None
    """
    if not in_reply_to_header:
        return None

    # 移除尖括号
    cleaned = in_reply_to_header.strip()
    if cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1]

    # 如果包含多个 message_id（用空格或逗号分隔），取第一个
    # 通常第一个是主要的回复目标
    parts = cleaned.split()
    if parts:
        return parts[0].strip()

    return cleaned if cleaned else None


async def _find_parent_reply_in_list(  # pylint: disable=too-many-return-statements
    session,
    in_reply_to: str,
    reply_map: Dict[str, ReplyMapEntry],
    patch_message_id: str,
    max_depth: int = 5,
) -> Optional[str]:
    """在回复列表中查找父回复

    递归查找 in_reply_to 链，直到找到在回复列表中的父回复

    Args:
        session: 数据库会话
        in_reply_to: 回复的 in_reply_to_header
        reply_map: 回复映射字典
        patch_message_id: PATCH 的 message_id
        max_depth: 最大递归深度

    Returns:
        父回复的 message_id_header，如果找不到则返回 None
    """
    if max_depth <= 0 or not in_reply_to:
        return None

    # 提取 message_id（处理尖括号、多个 message_id 等情况）
    extracted_id = _extract_message_id_from_header(in_reply_to)
    if not extracted_id:
        return None

    # 检查是否是直接回复 PATCH
    if extracted_id == patch_message_id or patch_message_id in extracted_id:
        return None  # 对 PATCH 的直接回复，没有父回复

    # 在回复列表中查找
    if extracted_id in reply_map:
        return extracted_id

    # 尝试模糊匹配（处理带尖括号等情况）
    for reply_id in reply_map:
        if extracted_id in reply_id or reply_id in extracted_id:
            return reply_id

    # 如果找不到，递归查找 in_reply_to 链
    feed_message_repo = FeedMessageRepository(session)
    feed_msg = await feed_message_repo.find_by_message_id_header(extracted_id)
    if feed_msg and feed_msg.in_reply_to_header:
        return await _find_parent_reply_in_list(
            session,
            feed_msg.in_reply_to_header,
            reply_map,
            patch_message_id,
            max_depth - 1,
        )

    return None


async def build_reply_hierarchy_internal(
    session, patch_replies: list, patch_message_id: str
) -> ReplyHierarchy:
    """构建回复层级关系

    通过递归查找 in_reply_to 链来确定真正的父回复

    Args:
        session: 数据库会话
        patch_replies: 回复列表（应该已经按时间正序排序）
        patch_message_id: PATCH 的 message_id

    Returns:
        回复层级结构
    """
    # 构建回复映射
    reply_map: Dict[str, ReplyMapEntry] = {}
    root_replies: List[str] = []

    for reply in patch_replies:
        reply_map[reply.message_id_header] = ReplyMapEntry(reply=reply, children=[])

    # 构建层级关系
    for reply in patch_replies:
        in_reply_to_raw = reply.in_reply_to_header
        if not in_reply_to_raw:
            # 没有 in_reply_to，作为根回复
            root_replies.append(reply.message_id_header)
            continue

        # 提取 message_id（处理尖括号、多个 message_id 等情况）
        in_reply_to = _extract_message_id_from_header(in_reply_to_raw)

        if not in_reply_to:
            # 无法提取 message_id，作为根回复
            root_replies.append(reply.message_id_header)
            continue

        # 检查是否是直接回复 PATCH
        if in_reply_to == patch_message_id or patch_message_id in in_reply_to:
            root_replies.append(reply.message_id_header)
            continue

        # 查找父回复（递归查找 in_reply_to 链）
        parent_id = await _find_parent_reply_in_list(
            session, in_reply_to_raw, reply_map, patch_message_id
        )

        if parent_id:
            # 找到父回复，作为子回复
            reply_map[parent_id].children.append(reply.message_id_header)
        else:
            # 找不到父回复，作为根回复处理
            root_replies.append(reply.message_id_header)

    # 对根回复按时间正序排序
    root_replies.sort(
        key=lambda rid: parse_reply_time(reply_map[rid].reply) or datetime.min
    )

    # 对每个回复的子回复也按时间正序排序
    for reply_entry in reply_map.values():
        reply_entry.children.sort(
            key=lambda cid: parse_reply_time(reply_map[cid].reply) or datetime.min
        )

    return ReplyHierarchy(reply_map=reply_map, root_replies=root_replies)


async def find_actual_patch_for_reply(
    session, feed_message, max_depth: int = 5
) -> Optional[object]:
    """查找回复实际对应的 PATCH

    递归查找 in_reply_to 链，直到找到实际的 PATCH（不是 cover letter）

    Args:
        session: 数据库会话
        feed_message: Feed 消息对象
        max_depth: 最大递归深度

    Returns:
        PATCH 订阅对象，如果不存在则返回 None
    """
    if max_depth <= 0 or not feed_message.in_reply_to_header:
        return None

    in_reply_to = feed_message.in_reply_to_header

    # 创建 Repository 实例（轻量、无状态，可随时 new）
    patch_card_repo = PatchCardRepository(session)
    feed_message_repo = FeedMessageRepository(session)

    # 查找这个 message_id 对应的 PATCH
    patch_card = await patch_card_repo.find_by_message_id_header(in_reply_to)
    if patch_card:
        # 如果找到的 PATCH 不是 cover letter，返回它
        if patch_card.patch_index != 0:
            return patch_card
        # 如果是 cover letter，返回 None（表示这个回复是针对 cover letter 的）
        return None

    # 如果这个 message_id 不是 PATCH，查找对应的 Feed 消息，继续查找它的 in_reply_to
    feed_msg = await feed_message_repo.find_by_message_id_header(in_reply_to)
    if feed_msg and feed_msg.in_reply_to_header:
        return await find_actual_patch_for_reply(session, feed_msg, max_depth - 1)

    return None


# ========== ThreadService 类 ==========


class ThreadService:
    """Thread 服务类（业务 API 层）

    Service 层通过依赖注入接受 Repository 实例。
    Plugins 层通过 `get_thread_service()` 函数获取 Service 实例。
    """

    def __init__(
        self,
        patch_thread_repo: PatchThreadRepository,
        patch_card_repo: PatchCardRepository,
        feed_message_repo: FeedMessageRepository,
    ):
        """初始化服务

        Args:
            patch_thread_repo: PATCH Thread 仓库实例（已注入 session）
            patch_card_repo: PATCH 卡片仓库实例（已注入 session）
            feed_message_repo: Feed 消息仓库实例（已注入 session）
        """
        self.patch_thread_repo = patch_thread_repo
        self.patch_card_repo = patch_card_repo
        self.feed_message_repo = feed_message_repo

    def _repo_data_to_service_feed_message(self, repo_data) -> FeedMessage:
        """将 repo 层的 FeedMessageData 转换为 service 层的 FeedMessage

        Args:
            repo_data: repo 层的 FeedMessageData

        Returns:
            service 层的 FeedMessage
        """
        from ..db.repo import FeedMessageData

        # 如果已经是 FeedMessage，直接返回（防御性检查）
        if isinstance(repo_data, FeedMessage):
            return repo_data

        # 确保是 FeedMessageData 类型
        if not isinstance(repo_data, FeedMessageData):
            raise TypeError(
                f"Expected FeedMessageData or FeedMessage, got {type(repo_data)}"
            )

        from .helpers import extract_common_feed_message_fields

        common_fields = extract_common_feed_message_fields(repo_data)
        return FeedMessage(**common_fields)

    def _repo_data_to_service_data(self, repo_data: RepoPatchThreadData) -> PatchThread:
        """将 repo 层的 PatchThreadData 转换为 service 层的 PatchThread

        Args:
            repo_data: repo 层的 PatchThreadData

        Returns:
            service 层的 PatchThread
        """
        return PatchThread(
            patch_card_message_id_header=repo_data.patch_card_message_id_header,
            thread_id=repo_data.thread_id,
            thread_name=repo_data.thread_name,
            is_active=repo_data.is_active,
            overview_message_id=repo_data.overview_message_id,
            sub_patch_messages=repo_data.sub_patch_messages,
            created_at=repo_data.created_at,
            archived_at=repo_data.archived_at,
        )

    async def find_by_message_id_header(
        self, message_id_header: str
    ) -> Optional[PatchThread]:
        """根据 PATCH 卡片的 message_id_header 查找 Thread

        Args:
            message_id_header: PATCH 卡片的 message_id_header

        Returns:
            Thread 数据，如果不存在则返回 None
        """
        try:
            repo_data = await self.patch_thread_repo.find_by_message_id_header(
                message_id_header
            )
            return self._repo_data_to_service_data(repo_data) if repo_data else None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to find thread by message_id_header: {e}", exc_info=True
            )
            return None

    async def find_by_thread_id(self, thread_id: str) -> Optional[PatchThread]:
        """根据 Thread ID 查找 Thread

        Args:
            thread_id: Thread ID

        Returns:
            Thread 数据，如果不存在则返回 None
        """
        try:
            repo_data = await self.patch_thread_repo.find_by_thread_id(thread_id)
            return self._repo_data_to_service_data(repo_data) if repo_data else None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to find thread by thread_id: {e}", exc_info=True)
            return None

    async def create(
        self, message_id_header: str, thread_id: str, thread_name: str
    ) -> Optional[PatchThread]:
        """创建 Thread 记录

        Args:
            message_id_header: PATCH 卡片的 message_id_header
            thread_id: Thread ID
            thread_name: Thread 名称

        Returns:
            创建的 Thread 数据，失败返回 None
        """
        try:
            # 先通过 message_id_header 查找 patch_card
            repo_patch_card = await self.patch_card_repo.find_by_message_id_header(
                message_id_header
            )
            if not repo_patch_card:
                logger.error(
                    f"Cannot create thread: patch_card not found for message_id_header={message_id_header}"
                )
                return None

            repo_thread_data = RepoPatchThreadData(
                patch_card_message_id_header=message_id_header,
                thread_id=thread_id,
                thread_name=thread_name[:100],
            )
            repo_result = await self.patch_thread_repo.create(repo_thread_data)
            return self._repo_data_to_service_data(repo_result) if repo_result else None
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to create thread: {e}", exc_info=True)
            return None

    async def delete(self, thread_id: str) -> bool:
        """删除 Thread 记录

        Args:
            thread_id: Thread ID

        Returns:
            成功返回 True，失败返回 False
        """
        try:
            return await self.patch_thread_repo.delete(thread_id)
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to delete thread: {e}", exc_info=True)
            return False

    async def mark_as_inactive(self, thread_id: str) -> bool:
        """将 Thread 标记为不活跃

        Args:
            thread_id: Thread ID

        Returns:
            成功返回 True，失败返回 False
        """
        try:
            return await self.patch_thread_repo.mark_as_inactive(thread_id)
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to mark thread as inactive: {e}", exc_info=True)
            return False

    async def count_active_threads(self) -> int:
        """统计活跃的 Thread 数量

        Returns:
            活跃 Thread 的数量
        """
        try:
            return await self.patch_thread_repo.count_active_threads()
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to count active threads: {e}", exc_info=True)
            return 0

    async def update_overview_message_id(
        self, thread_id: str, overview_message_id: str
    ) -> bool:
        """更新 Thread 的 Overview 消息 ID

        Args:
            thread_id: Thread ID
            overview_message_id: Overview 消息 ID

        Returns:
            成功返回 True，失败返回 False
        """
        try:
            return await self.patch_thread_repo.update_overview_message_id(
                thread_id, overview_message_id
            )
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to update thread overview_message_id: {e}", exc_info=True
            )
            return False

    # ========== 回复处理相关 ==========

    async def build_reply_hierarchy(
        self, patch_replies: list, patch_message_id: str
    ) -> ReplyHierarchy:
        """构建回复层级关系

        Args:
            patch_replies: 回复列表（应该已经按时间正序排序）
            patch_message_id: PATCH 的 message_id

        Returns:
            回复层级结构
        """
        # 获取 session（从 repository）
        session = self.feed_message_repo.session
        return await build_reply_hierarchy_internal(
            session, patch_replies, patch_message_id
        )

    async def find_all_replies_to_patch(
        self, patch_message_id: str, max_depth: int = 10
    ) -> List[FeedMessage]:
        """查找 PATCH 的所有回复（包括直接回复和间接回复）

        Args:
            patch_message_id: PATCH 的 message_id
            max_depth: 最大递归深度

        Returns:
            所有回复列表
        """
        try:
            repo_replies = await self.feed_message_repo.find_replies_to(
                patch_message_id, limit=max_depth * 10
            )
            # 转换为 Service 层的 FeedMessage
            return [
                self._repo_data_to_service_feed_message(reply) for reply in repo_replies
            ]
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to find all replies to patch: {e}", exc_info=True)
            return []

    async def find_replies_to_sub_patch(
        self, sub_patch_message_id: str, max_depth: int = 10
    ) -> List[FeedMessage]:
        """查找特定子 PATCH 的所有回复

        Args:
            sub_patch_message_id: 子 PATCH 的 message_id
            max_depth: 最大递归深度

        Returns:
            该子 PATCH 的回复列表
        """
        try:
            repo_replies = await self.feed_message_repo.find_replies_to(
                sub_patch_message_id, limit=max_depth * 10
            )
            # 转换为 Service 层的 FeedMessage
            return [
                self._repo_data_to_service_feed_message(reply) for reply in repo_replies
            ]
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to find replies to sub-patch: {e}", exc_info=True)
            return []

    async def update_sub_patch_messages(
        self, thread_id: str, sub_patch_messages: dict
    ) -> bool:
        """更新 Thread 的子 PATCH 消息映射

        Args:
            thread_id: Thread ID
            sub_patch_messages: 子 PATCH 消息映射 {patch_index: message_id}

        Returns:
            是否更新成功
        """
        return await self.patch_thread_repo.update_sub_patch_messages(
            thread_id, sub_patch_messages
        )

    def _filter_replies_for_patch(
        self, all_replies: List[FeedMessage], patch_message_id: str
    ) -> List[FeedMessage]:
        """筛选某个 PATCH 的所有回复（包括直接和间接回复）

        Args:
            all_replies: 所有回复列表
            patch_message_id: PATCH 的 message_id

        Returns:
            该 PATCH 的所有回复列表（包括直接和间接回复）
        """
        patch_replies = []
        patch_message_ids = [patch_message_id]

        # 首先找到所有直接回复该 PATCH 的回复
        for reply in all_replies:
            if not reply.in_reply_to_header:
                continue

            # 提取 in_reply_to 中的 message_id
            in_reply_to = _extract_message_id_from_header(reply.in_reply_to_header)
            if not in_reply_to:
                continue

            # 检查是否是直接回复该 PATCH
            if patch_message_id in in_reply_to or in_reply_to == patch_message_id:
                if reply not in patch_replies:
                    patch_replies.append(reply)
                    patch_message_ids.append(reply.message_id_header)

        # 然后找到所有间接回复（回复的回复）
        # 递归查找所有回复该 PATCH 或其回复的消息
        changed = True
        while changed:
            changed = False
            for reply in all_replies:
                if reply in patch_replies:
                    continue

                if not reply.in_reply_to_header:
                    continue

                in_reply_to = _extract_message_id_from_header(reply.in_reply_to_header)
                if not in_reply_to:
                    continue

                # 检查是否是回复该 PATCH 或其任何回复
                for msg_id in patch_message_ids:
                    if msg_id in in_reply_to or in_reply_to == msg_id:
                        if reply not in patch_replies:
                            patch_replies.append(reply)
                            patch_message_ids.append(reply.message_id_header)
                            changed = True
                        break

        return patch_replies

    async def prepare_sub_patch_overview_data(
        self, patch: "SeriesPatchInfo", all_replies: List[FeedMessage]
    ) -> "SubPatchOverviewData":
        """为单个子 PATCH 准备独立的 Overview 数据

        Args:
            patch: 子 PATCH 信息
            all_replies: 所有回复列表（从整个系列中筛选）

        Returns:
            SubPatchOverviewData，包含该子 PATCH 的完整数据
        """
        from .types import SubPatchOverviewData

        # 1. 筛选该子 PATCH 的所有回复
        patch_replies = self._filter_replies_for_patch(all_replies, patch.message_id)

        # 2. 构建该子 PATCH 的回复层级
        patch_reply_hierarchy = await self.build_reply_hierarchy(
            patch_replies, patch.message_id
        )

        return SubPatchOverviewData(
            patch=patch,
            replies=patch_replies,
            reply_hierarchy=patch_reply_hierarchy,
        )

    async def prepare_thread_overview_data(
        self, message_id_header: str
    ) -> Optional[ThreadOverviewData]:
        """准备 Thread Overview 渲染数据（供 Plugins 层使用）

        这个方法做所有的业务逻辑：
        - 查询 PatchCard（包含 series_patches）
        - 查询所有 replies
        - 构建 reply hierarchy
        - 为每个子 PATCH 准备独立的 overview 数据
        - 返回完整的渲染数据

        Args:
            message_id_header: PATCH message_id_header

        Returns:
            ThreadOverviewData，如果不存在返回 None
        """
        from ..db.database import get_patch_card_service
        from .types import ThreadOverviewData

        try:
            # 1. 获取 PatchCard（包含 series_patches）
            async with get_patch_card_service() as patch_card_service:
                patch_card = await patch_card_service.get_patch_card_with_series_data(
                    message_id_header
                )

            if not patch_card:
                logger.warning(f"PatchCard not found: {message_id_header}")
                return None

            # 2. 查询所有 replies（整个系列的）
            replies = await self.find_all_replies_to_patch(message_id_header)

            # 3. 构建整体 reply hierarchy（基于 cover letter）
            reply_hierarchy = await self.build_reply_hierarchy(
                replies, message_id_header
            )

            # 4. 为每个子 PATCH 准备独立的 overview 数据
            sub_patch_overviews = None
            if patch_card.is_series_patch and patch_card.series_patches:
                # 系列 PATCH：为每个子 PATCH 准备独立数据
                sub_patch_overviews = []
                # 过滤掉 Cover Letter (index=0)
                patches_to_process = [
                    p for p in patch_card.series_patches if p.patch_index != 0
                ]
                for patch in patches_to_process:
                    sub_overview = await self.prepare_sub_patch_overview_data(
                        patch, replies
                    )
                    sub_patch_overviews.append(sub_overview)
            else:
                # 单 PATCH：也为它准备独立数据
                from .helpers import build_single_patch_info

                single_patch = build_single_patch_info(patch_card)
                sub_overview = await self.prepare_sub_patch_overview_data(
                    single_patch, replies
                )
                sub_patch_overviews = [sub_overview]

            return ThreadOverviewData(
                patch_card=patch_card,
                replies=replies,
                reply_hierarchy=reply_hierarchy,
                sub_patch_overviews=sub_patch_overviews,
            )

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to prepare thread overview data: {e}", exc_info=True)
            return None


# 工厂函数已移至 lkml.db.database 模块以避免循环导入
# 不再在此模块导入，直接从 lkml.db.database 或 lkml.service 导入
