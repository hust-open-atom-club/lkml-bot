"""Feed 处理逻辑

负责从 lore.kernel.org 抓取邮件列表的 Atom feed，解析邮件内容并存储到数据库。
"""

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import feedparser
from feedparser.util import FeedParserDict
import logging

logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING

from ..config import get_config
from ..db.models import Subsystem
from ..db.repo import SUBSYSTEM_REPO
from ..db.repo import FeedMessageRepository
from ..service import FeedMessage

if TYPE_CHECKING:
    from ..db.repo import FeedMessageData
from .types import (
    FeedEntry,
    FeedEntryContent,
    FeedEntryMetadata,
    FeedProcessResult,
)
from .feed_message_classifier import classify_message


class FeedProcessor:
    """处理单个子系统的 feed：抓取、解析、入库、统计

    负责从指定 URL 抓取 Atom feed，解析邮件条目，去重后存储到数据库。
    """

    def __init__(
        self, *, database, thread_manager=None, feed_message_service=None
    ) -> None:
        """初始化 Feed 处理器

        Args:
            database: 数据库实例
            thread_manager: Thread 管理器（可选，用于处理 PATCH 卡片和 REPLY）
            feed_message_service: Feed 消息服务（可选，用于处理 PATCH 和 REPLY）
        """
        self.database = database
        self.thread_manager = thread_manager
        self.feed_message_service = feed_message_service

        # 初始化 last_update_dt
        # 优先使用环境变量覆盖（用于调试/开发）
        cfg = get_config()
        override_iso = getattr(cfg, "last_update_dt_override_iso", None)
        if override_iso is not None:
            # 使用 ISO8601 字符串覆盖（支持结尾 Z）
            iso_str = str(override_iso).strip()
            try:
                if iso_str.endswith("Z"):
                    iso_str = iso_str[:-1] + "+00:00"
                self.last_update_dt = datetime.fromisoformat(iso_str)
                # 确保为 aware；若解析为 naive，则设为 UTC
                if self.last_update_dt.tzinfo is None:
                    self.last_update_dt = self.last_update_dt.replace(
                        tzinfo=timezone.utc
                    )
                logger.info(
                    f"Using LKML_LAST_UPDATE_AT override: {self.last_update_dt}"
                )
            except (ValueError, AttributeError, TypeError):
                logger.warning(
                    f"Invalid LKML_LAST_UPDATE_AT format: {override_iso}, using database query"
                )
                self.last_update_dt = None  # 标记需要从数据库查询
        else:
            self.last_update_dt = None  # 标记需要从数据库查询

    def _handle_feed_status(self, feed_status: Optional[int], feed_url: str) -> bool:
        """处理 feed 状态码，返回是否应该继续处理"""
        if not feed_status:
            return True
        if feed_status == 404:
            logger.error(
                f"Feed not found (404) for {feed_url}. "
                "Possibly invalid subsystem or URL."
            )
            return False
        if feed_status >= 400:
            logger.error(f"HTTP error {feed_status} when fetching {feed_url}.")
            return False
        if feed_status != 200:
            logger.warning(
                f"Unexpected HTTP status {feed_status} for {feed_url}, "
                "continue parsing."
            )
        return True

    def _handle_feed_bozo(self, feed: FeedParserDict, feed_url: str) -> bool:
        """处理 feed 解析警告，返回是否应该继续处理"""
        if not feed.bozo:
            return True
        bozo_exception = feed.bozo_exception
        bozo_message = (
            str(bozo_exception) if bozo_exception else "Unknown parsing error"
        )
        logger.warning(f"Feed parsing warning for {feed_url}: {bozo_message}")
        if not feed.entries:
            logger.error(
                f"Feed parsing failed for {feed_url}: {bozo_message}. No entries."
            )
            return False
        return True

    def _filter_entries_by_date(
        self, feed_entries: List[FeedParserDict]
    ) -> List[FeedParserDict]:
        """根据日期筛选新条目"""
        entries: List[FeedParserDict] = []
        for entry in feed_entries:
            if hasattr(entry, "updated_parsed") and entry.updated_parsed:
                entry_dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            else:
                # 没有时间信息则认为是新条目（保守处理）
                entries.append(entry)
                continue

            if entry_dt > self.last_update_dt:
                entries.append(entry)
            else:
                break
        return entries

    def get_feed_entries(self, feed_url: str) -> List[FeedParserDict]:
        """拉取并筛选新条目（带指数退避重试）"""
        start_ts = time.time()
        logger.info(f"Fetching feed from {feed_url}")

        max_attempts = 3
        delay = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                feed: FeedParserDict = feedparser.parse(feed_url)
            except (OSError, ValueError, KeyError) as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed to fetch feed: "
                    f"{type(e).__name__}: {e}"
                )
                if attempt < max_attempts:
                    time.sleep(delay)
                    delay *= 2
                    continue
                logger.error(
                    f"Failed to fetch feed from {feed_url} after {max_attempts} attempts: {e}",
                    exc_info=True,
                )
                return []

            feed_status = getattr(feed, "status", None)
            if not self._handle_feed_status(feed_status, feed_url):
                return []

            if not self._handle_feed_bozo(feed, feed_url):
                return []

            entries = self._filter_entries_by_date(feed.entries)

            if feed.bozo and entries:
                logger.info(
                    f"Feed parsed with warnings for {feed_url}, extracted {len(entries)} entries"
                )

            elapsed_ms = int((time.time() - start_ts) * 1000)
            logger.info(
                f"Fetched {len(entries)} entries from {feed_url} in {elapsed_ms} ms"
            )
            return entries

    def extract_email_from_author(self, author: str) -> Optional[str]:
        """从作者信息中提取邮箱地址

        Args:
            author: 作者信息字符串，可能包含姓名和邮箱

        Returns:
            提取出的邮箱地址，如果提取失败则返回 None
        """
        try:
            email_match = re.search(
                r"[<\(]([^<>\(\)]+@[^<>\(\)]+\.[^<>\(\)]+)[>\)]", author
            )
            if email_match:
                return email_match.group(1)

            email_match = re.search(
                r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", author
            )
            if email_match:
                return email_match.group(1)

            return None
        except (AttributeError, TypeError) as e:
            logger.error(f"Failed to extract email from author '{author}': {e}")
            return None

    def is_reply_message(self, title: str) -> bool:
        """判断是否为回复消息

        Args:
            title: 邮件主题

        Returns:
            如果主题以小写 "re:" 开头则返回 True，否则返回 False
        """
        return title.lower().startswith("re:")

    def is_patch_message(self, title: str) -> bool:
        """判断是否为 PATCH 邮件

        常见格式如: [PATCH], [PATCH v2], [RFC PATCH], [PATCH 0/5] 等
        """
        lowered = title.lower()
        return "[patch" in lowered or lowered.startswith("patch:")

    def _extract_received_at(self, entry: FeedParserDict) -> datetime:
        """从条目中提取接收时间"""
        try:
            if hasattr(entry, "updated_parsed") and entry.updated_parsed:
                return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            return datetime.now(timezone.utc)
        except (ValueError, TypeError, IndexError) as e:
            logger.warning(f"Failed to parse date for entry {entry.title}: {e}")
            return datetime.now(timezone.utc)

    def _generate_message_id(
        self, entry: FeedParserDict, subsystem: Subsystem, received_at: datetime
    ) -> str:
        """生成稳定的 message_id"""
        message_id = entry.get("id") or entry.link
        if not message_id:
            base = f"{subsystem.name}|{entry.title}|{int(received_at.timestamp())}"
            message_id = hashlib.sha256(base.encode("utf-8")).hexdigest()[:40]
        return message_id

    def _extract_message_id_header(self, entry: FeedParserDict) -> Optional[str]:
        """从链接中提取 message_id_header"""
        if not hasattr(entry, "link") or not entry.link:
            return None
        try:
            parsed_url = urlparse(entry.link)
            path = parsed_url.path.strip("/")
            if path:
                parts = path.split("/")
                if len(parts) >= 2:
                    return parts[-1]
        except (ValueError, AttributeError) as e:
            logger.debug(f"Failed to extract message_id from link {entry.link}: {e}")
        return None

    def _extract_in_reply_to_header(self, entry: FeedParserDict) -> Optional[str]:
        """从条目中提取 in_reply_to_header

        从 thr:in-reply-to 的 href 属性提取父邮件的 URL，
        然后解析出真正的 Message-ID。
        """
        try:
            thr = entry.get("thr_in-reply-to") or entry.get("thr:in-reply-to")
            if isinstance(thr, dict):
                # 优先从 href 提取（包含真正的邮件 URL）
                href = thr.get("href")
                if isinstance(href, str) and href:
                    # 从 URL 中提取 Message-ID
                    # 例如: https://lore.kernel.org/rust-for-linux/msg-id@domain.com/
                    parsed_url = urlparse(href)
                    path = parsed_url.path.strip("/")
                    if path:
                        parts = path.split("/")
                        if len(parts) >= 2:
                            return parts[-1]  # 返回 msg-id@domain.com

                # 如果 href 不存在或提取失败，尝试使用 ref（可能是 UUID）
                ref = thr.get("ref")
                if isinstance(ref, str):
                    # 如果是 UUID 格式，记录警告
                    if ref.startswith("urn:uuid:"):
                        logger.debug(
                            f"In-Reply-To is UUID format: {ref}, may not work correctly"
                        )
                    return ref
        except (AttributeError, TypeError, ValueError) as e:
            logger.debug(f"Failed to extract in_reply_to_header: {e}")
        return None

    def _extract_feed_message_data(
        self, entry: FeedParserDict, subsystem: Subsystem
    ) -> Tuple[str, datetime, str, str, str]:
        """提取 Feed 消息的基本数据

        Returns:
            (email, received_at, message_id, message_id_header, in_reply_to_header)
        """
        email = self.extract_email_from_author(entry.author)
        received_at = self._extract_received_at(entry)
        message_id = self._generate_message_id(entry, subsystem, received_at)
        message_id_header = self._extract_message_id_header(entry)
        in_reply_to_header = self._extract_in_reply_to_header(entry)
        return (email, received_at, message_id, message_id_header, in_reply_to_header)

    def _convert_repo_to_service_feed_message(
        self, repo_data: "FeedMessageData"
    ) -> FeedMessage:
        """将 Repository 层的 FeedMessageData 转换为 Service 层的 FeedMessage"""
        from ..service.helpers import extract_common_feed_message_fields

        common_fields = extract_common_feed_message_fields(repo_data)
        return FeedMessage(**common_fields)

    async def _save_service_feed_message_to_repo(
        self, feed_message_repo, service_feed_message_data
    ):
        """将 Service 层的 FeedMessage 转换为 Repo 层数据并保存"""
        from ..db.repo import FeedMessageData as RepoFeedMessageData

        from ..service.helpers import extract_common_feed_message_fields

        common_fields = extract_common_feed_message_fields(service_feed_message_data)
        repo_feed_message_data = RepoFeedMessageData(**common_fields)

        return await feed_message_repo.create_or_update(data=repo_feed_message_data)

    def _build_service_feed_message(  # pylint: disable=too-many-arguments
        self,
        entry: FeedParserDict,
        subsystem: Subsystem,
        email: str,
        received_at: datetime,
        message_id: str,
        message_id_header: str,
        in_reply_to_header: str,
        classification,
    ) -> FeedMessage:
        """构建 Service 层的 FeedMessage 对象"""
        patch_info = classification.patch_info
        return FeedMessage(
            subsystem_name=subsystem.name,
            message_id=message_id,
            message_id_header=message_id_header or message_id,
            in_reply_to_header=in_reply_to_header,
            subject=entry.title,
            author=entry.author,
            author_email=email or "unknown@example.com",
            content=entry.get("summary", "") or entry.get("description", ""),
            url=entry.link,
            received_at=received_at,
            is_patch=classification.is_patch,
            is_reply=classification.is_reply,
            is_series_patch=classification.is_series_patch,
            patch_version=patch_info.version if patch_info else None,
            patch_index=patch_info.index if patch_info else None,
            patch_total=patch_info.total if patch_info else None,
            is_cover_letter=patch_info.is_cover_letter if patch_info else False,
            series_message_id=classification.series_message_id,
        )

    async def save_feed_message(
        self, session, entry: FeedParserDict, subsystem: Subsystem
    ):
        """保存 Feed 消息到数据库

        Args:
            session: 数据库会话
            entry: Feed 解析条目
            subsystem: 子系统对象

        Returns:
            保存的 Feed 消息对象
        """
        # 提取基本数据
        email, received_at, message_id, message_id_header, in_reply_to_header = (
            self._extract_feed_message_data(entry, subsystem)
        )

        # 创建 Repository 实例
        feed_message_repo = FeedMessageRepository(session)

        # 检查是否已存在
        if message_id_header:
            existing_message_data = await feed_message_repo.find_by_message_id_header(
                message_id_header
            )
            if existing_message_data:
                logger.debug(f"Feed message already exists: {message_id_header}")
                # 即使消息已存在，也需要分类并附加 _classification，以便后续处理 REPLY
                classification = classify_message(
                    subject=entry.title,
                    in_reply_to_header=in_reply_to_header,
                    message_id_header=message_id_header,
                )
                converted_message = self._convert_repo_to_service_feed_message(
                    existing_message_data
                )
                # 附加分类信息以便后续处理
                # pylint: disable=protected-access
                converted_message._classification = classification  # type: ignore
                return converted_message

        # 使用标准化的消息分类器判断消息类型
        classification = classify_message(
            subject=entry.title,
            in_reply_to_header=in_reply_to_header,
            message_id_header=message_id_header,
        )

        # 调试日志：记录 Series Patch 的分类信息
        if classification.is_series_patch and classification.patch_info:
            logger.debug(
                f"Series PATCH classified: subject={entry.title[:80]}, "
                f"patch_index={classification.patch_info.index}/{classification.patch_info.total}, "
                f"is_cover_letter={classification.patch_info.is_cover_letter}, "
                f"series_message_id={classification.series_message_id[:50] if classification.series_message_id else None}"  # pylint: disable=line-too-long
            )

        # 构建 Service 层的 FeedMessage 对象
        service_feed_message_data = self._build_service_feed_message(
            entry,
            subsystem,
            email,
            received_at,
            message_id,
            message_id_header,
            in_reply_to_header,
            classification,
        )

        # 转换为 repo 层数据并保存
        feed_message_data = await self._save_service_feed_message_to_repo(
            feed_message_repo, service_feed_message_data
        )

        # 将分类结果附加到 feed_message_data 对象（用于后续处理）
        # pylint: disable=protected-access
        # _classification is used for internal processing, not part of public API
        feed_message_data._classification = classification  # type: ignore

        return feed_message_data

    def _create_feed_entry(self, feed_message_data) -> FeedEntry:
        """创建 FeedEntry 对象

        Args:
            feed_message_data: FeedMessageData 或 FeedMessage 对象
        """

        # 处理 received_at，可能是 datetime 对象或 None
        received_at_str = ""
        if feed_message_data.received_at:
            if isinstance(feed_message_data.received_at, datetime):
                received_at_str = feed_message_data.received_at.isoformat()
            else:
                received_at_str = str(feed_message_data.received_at)

        content = FeedEntryContent(
            summary=feed_message_data.content or "",
            received_at=received_at_str,
            is_reply=feed_message_data.is_reply,
            is_patch=feed_message_data.is_patch,
        )

        # 构建元数据
        metadata = FeedEntryMetadata(
            message_id=feed_message_data.message_id_header,
            in_reply_to=feed_message_data.in_reply_to_header,
        )

        return FeedEntry(
            id=feed_message_data.id if hasattr(feed_message_data, "id") else None,
            subject=feed_message_data.subject,
            author=feed_message_data.author,
            email=feed_message_data.author_email,
            url=feed_message_data.url,
            content=content,
            metadata=metadata,
        )

    async def _process_entries(
        self, session, entries: List[FeedParserDict], subsystem: Subsystem
    ) -> Tuple[int, int, List[FeedEntry]]:
        """处理条目并返回统计信息

        分两个阶段：
        1. 先将所有 feed_message 入库
        2. 再批量处理（创建 Patch Card、处理 Reply）

        这样可以避免 Cover Letter 先到达时，子 PATCH 还未入库的时序问题。
        """
        new_count = 0
        reply_count = 0
        processed_entries: List[FeedEntry] = []

        # 阶段 1: 保存所有 feed_message 到数据库
        saved_messages = []
        for entry in entries:
            feed_message = await self.save_feed_message(session, entry, subsystem)
            saved_messages.append((feed_message, entry))

            # 统计消息类型
            if feed_message.is_reply:
                reply_count += 1
            else:
                new_count += 1

        # 阶段 2: 批量处理所有 feed_message
        for feed_message, entry in saved_messages:
            # 处理 PATCH 卡片生成和 REPLY 逻辑
            # 使用附加的分类信息（不存储在模型中）
            if hasattr(feed_message, "_classification") and self.feed_message_service:
                # pylint: disable=protected-access
                # _classification is used for internal processing, not part of public API
                classification = feed_message._classification  # type: ignore
                try:
                    await self.feed_message_service.process_email_message(
                        session, feed_message, classification
                    )
                except (RuntimeError, ValueError, AttributeError) as e:
                    logger.error(
                        f"Failed to process feed message: {e}",
                        exc_info=True,
                    )

            processed_entries.append(self._create_feed_entry(feed_message))

        return (new_count, reply_count, processed_entries)

    def _update_last_update_time(self, entries: List[FeedParserDict]) -> None:
        """更新最后更新时间"""
        if not entries:
            return
        latest_entry = entries[0]
        if hasattr(latest_entry, "updated_parsed") and latest_entry.updated_parsed:
            self.last_update_dt = datetime(
                *latest_entry.updated_parsed[:6], tzinfo=timezone.utc
            )

    async def _initialize_last_update_dt(self, subsystem_name: str) -> None:
        """从数据库初始化 last_update_dt

        如果 last_update_dt 为 None，从数据库中查询该子系统最新的 received_at

        Args:
            subsystem_name: 子系统名称
        """
        if self.last_update_dt is not None:
            return  # 已经初始化（使用环境变量覆盖）

        try:
            async with self.database.get_db_session() as session:
                from sqlalchemy import select, func
                from ..db.models import FeedMessageModel

                # 查询该子系统最新的 received_at
                result = await session.execute(
                    select(func.max(FeedMessageModel.received_at)).where(
                        FeedMessageModel.subsystem_name == subsystem_name
                    )
                )
                max_received_at = result.scalar()

                if max_received_at:
                    # 确保为 aware datetime
                    if max_received_at.tzinfo is None:
                        self.last_update_dt = max_received_at.replace(
                            tzinfo=timezone.utc
                        )
                    else:
                        self.last_update_dt = max_received_at
                    logger.info(
                        f"Initialized last_update_dt from database for {subsystem_name}: "
                        f"{self.last_update_dt}"
                    )
                else:
                    # 没有历史数据，使用当前时间
                    self.last_update_dt = datetime.now(timezone.utc)
                    logger.info(
                        f"No historical data for {subsystem_name}, using current time: "
                        f"{self.last_update_dt}"
                    )
        except (RuntimeError, ValueError) as e:
            logger.warning(
                f"Failed to initialize last_update_dt from database: {e}, "
                f"using current time"
            )
            self.last_update_dt = datetime.now(timezone.utc)

    async def process_feed(
        self, subsystem_name: str, feed_url: str
    ) -> FeedProcessResult:
        """处理单个子系统 feed 并返回统计结果

        Args:
            subsystem_name: 子系统名称
            feed_url: Feed URL

        Returns:
            Feed 处理结果，包含新增数量、回复数量和条目列表
        """
        logger.info(f"Processing feed for subsystem: {subsystem_name}")

        # 初始化 last_update_dt（如果还没有初始化）
        await self._initialize_last_update_dt(subsystem_name)

        proc_start = time.time()

        entries = self.get_feed_entries(feed_url)
        if not entries:
            logger.info(f"No new entries found for {subsystem_name}")
            return FeedProcessResult(
                subsystem=subsystem_name, new_count=0, reply_count=0, entries=[]
            )

        async with self.database.get_db_session() as session:
            subsystem = await SUBSYSTEM_REPO.get_or_create(session, subsystem_name)
            new_count, reply_count, processed_entries = await self._process_entries(
                session, entries, subsystem
            )
            await session.commit()

        self._update_last_update_time(entries)

        proc_ms = int((time.time() - proc_start) * 1000)
        logger.info(
            f"Processed {len(entries)} entries for {subsystem_name}: "
            f"{new_count} new, {reply_count} replies, took {proc_ms} ms"
        )

        return FeedProcessResult(
            subsystem=subsystem_name,
            new_count=new_count,
            reply_count=reply_count,
            entries=processed_entries,
        )
