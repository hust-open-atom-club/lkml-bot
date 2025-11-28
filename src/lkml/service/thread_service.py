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
        reply: FeedMessage 对象

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

    async def _prepare_single_patch_overview(self, patch):
        """为单个 Patch 准备 overview 数据

        Args:
            patch: Patch 对象（SeriesPatchInfo）

        Returns:
            SubPatchOverviewData 对象，失败返回 None
        """
        from .types import SubPatchOverviewData

        try:
            patch_replies = await self.get_all_replies_for_patch(patch.message_id)
            patch_reply_hierarchy = await self.build_reply_hierarchy(
                patch_replies, patch.message_id
            )

            return SubPatchOverviewData(
                patch=patch,
                replies=patch_replies,
                reply_hierarchy=patch_reply_hierarchy,
            )
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to prepare single patch overview: {e}",
                exc_info=True,
            )
            return None

    async def get_all_replies_for_patch(
        self, patch_message_id: str
    ) -> List[FeedMessage]:
        """获取某个 Patch 的所有 REPLY（包括 REPLY 的 REPLY）

        这个方法会递归查找所有直接和间接回复该 Patch 的消息。

        Args:
            patch_message_id: Patch 的 message_id_header

        Returns:
            该 Patch 的所有 REPLY 列表（包括 REPLY 的 REPLY）
        """
        try:
            # 使用递归方式查找所有回复（包括间接回复）
            all_replies = []
            message_ids_to_check = [patch_message_id]
            checked_message_ids = set()
            max_iterations = 20  # 防止无限循环

            iteration = 0
            while message_ids_to_check and iteration < max_iterations:
                iteration += 1
                current_message_id = message_ids_to_check.pop(0)

                # 避免重复检查
                if current_message_id in checked_message_ids:
                    continue
                checked_message_ids.add(current_message_id)

                # 查找直接回复当前消息的所有 REPLY
                direct_replies = await self.feed_message_repo.find_replies_to(
                    current_message_id, limit=100
                )

                # 转换为 Service 层的 FeedMessage
                for reply_data in direct_replies:
                    reply = self._repo_data_to_service_feed_message(reply_data)

                    # 如果这个 REPLY 还没有被添加到列表中，添加它
                    if not any(
                        r.message_id_header == reply.message_id_header
                        for r in all_replies
                    ):
                        all_replies.append(reply)
                        # 将这个 REPLY 的 message_id 加入待检查列表，以便查找回复它的 REPLY
                        if reply.message_id_header not in checked_message_ids:
                            message_ids_to_check.append(reply.message_id_header)

            return all_replies
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(
                f"Failed to get all replies for patch {patch_message_id}: {e}",
                exc_info=True,
            )
            return []

    async def prepare_thread_overview_data(
        self, message_id_header: str
    ) -> Optional[ThreadOverviewData]:
        """准备 Thread Overview 渲染数据（供 Plugins 层使用）

        统一处理单 Patch 和 Series Patch：
        - 单 Patch：为该 Patch 准备所有 REPLY 数据（包括 REPLY 的 REPLY）
        - Series Patch：以子 Patch 为单位，每个子 Patch 和单 Patch 的逻辑一致

        Args:
            message_id_header: PATCH message_id_header（Cover Letter 或单 Patch）

        Returns:
            ThreadOverviewData，如果不存在返回 None
        """
        from ..db.database import get_patch_card_service
        from .helpers import build_single_patch_info

        # ThreadOverviewData 已在模块顶部导入

        try:
            # 1. 获取 PatchCard（包含 series_patches）
            async with get_patch_card_service() as patch_card_service:
                patch_card = await patch_card_service.get_patch_card_with_series_data(
                    message_id_header
                )

            if not patch_card:
                logger.warning(f"PatchCard not found: {message_id_header}")
                return None

            # 2. 确定要处理的 Patch 列表
            if patch_card.is_series_patch and patch_card.series_patches:
                # Series Patch：处理所有子 Patch
                patches_to_process = list(patch_card.series_patches)
            else:
                # 单 Patch：构建 SeriesPatchInfo 对象
                single_patch = build_single_patch_info(patch_card)
                patches_to_process = [single_patch]

            if not patches_to_process:
                logger.warning(
                    f"No patches to process for message_id_header: {message_id_header}"
                )
                return None

            # 3. 为每个 Patch 准备独立的 overview 数据
            sub_patch_overviews = []
            for patch in patches_to_process:
                overview = await self._prepare_single_patch_overview(patch)
                if overview:
                    sub_patch_overviews.append(overview)

            # 4. 构建 ThreadOverviewData
            # 注意：replies 和 reply_hierarchy 字段保留用于兼容，但实际使用 sub_patch_overviews
            return ThreadOverviewData(
                patch_card=patch_card,
                replies=[],  # 不再使用整体 replies
                reply_hierarchy=None,  # 不再使用整体 reply_hierarchy
                sub_patch_overviews=sub_patch_overviews,
            )

        except (RuntimeError, ValueError, AttributeError) as e:
            logger.error(f"Failed to prepare thread overview data: {e}", exc_info=True)
            return None


# 工厂函数已移至 lkml.db.database 模块以避免循环导入
# 不再在此模块导入，直接从 lkml.db.database 或 lkml.service 导入
