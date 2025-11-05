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
from nonebot.log import logger

from ..config import get_config
from ..db.models import EmailMessage, Subsystem
from ..db.repo import EMAIL_MESSAGE_REPO, EmailMessageData, SUBSYSTEM_REPO
from .types import FeedEntry, FeedEntryContent, FeedProcessResult


class FeedProcessor:
    """处理单个子系统的 feed：抓取、解析、入库、统计

    负责从指定 URL 抓取 Atom feed，解析邮件条目，去重后存储到数据库。
    """

    def __init__(self, *, database) -> None:
        """初始化 Feed 处理器

        Args:
            database: 数据库实例
        """
        # 使用 aware datetime（UTC）
        cfg = get_config()
        override_iso = getattr(cfg, "last_update_dt_override_iso", None)
        logger.info(f"override_iso: {override_iso}")
        if override_iso is not None:
            # 优先使用 ISO8601 字符串覆盖（支持结尾 Z）
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
            except (ValueError, AttributeError, TypeError):
                self.last_update_dt = datetime.now(timezone.utc)
        else:
            self.last_update_dt = datetime.now(timezone.utc)

        self.database = database

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
        """从条目中提取 in_reply_to_header"""
        try:
            thr = entry.get("thr_in-reply-to") or entry.get("thr:in-reply-to")
            if isinstance(thr, dict):
                ref = thr.get("ref")
                if isinstance(ref, str):
                    return ref
        except (AttributeError, TypeError):
            pass
        return None

    async def save_email_message(
        self, session, entry: FeedParserDict, subsystem: Subsystem
    ) -> EmailMessage:
        """保存邮件消息到数据库

        Args:
            session: 数据库会话
            entry: Feed 解析条目
            subsystem: 子系统对象

        Returns:
            保存的邮件消息对象
        """
        email = self.extract_email_from_author(entry.author)
        received_at = self._extract_received_at(entry)
        message_id = self._generate_message_id(entry, subsystem, received_at)

        existing_message = await EMAIL_MESSAGE_REPO.find_by_message_id(
            session, message_id
        )
        if existing_message:
            logger.debug(f"Message already exists: {message_id}")
            return existing_message

        message_id_header = self._extract_message_id_header(entry)
        in_reply_to_header = self._extract_in_reply_to_header(entry)

        data = EmailMessageData(
            subsystem=subsystem,
            message_id=message_id,
            subject=entry.title,
            sender=entry.author,
            sender_email=email or "unknown@example.com",
            content=entry.get("summary", "") or entry.get("description", ""),
            url=entry.link,
            received_at=received_at,
            message_id_header=message_id_header,
            in_reply_to_header=in_reply_to_header,
        )
        return await EMAIL_MESSAGE_REPO.create(session, data=data)

    def _create_feed_entry(
        self, email_message: EmailMessage, entry: FeedParserDict
    ) -> FeedEntry:
        """创建 FeedEntry 对象"""
        is_reply = self.is_reply_message(entry.title)
        is_patch = self.is_patch_message(entry.title)
        content = FeedEntryContent(
            summary=entry.get("summary", "") or entry.get("description", ""),
            received_at=email_message.received_at.isoformat(),
            is_reply=is_reply,
            is_patch=is_patch,
        )
        return FeedEntry(
            id=email_message.id,
            subject=entry.title,
            author=entry.author,
            email=self.extract_email_from_author(entry.author),
            url=entry.link,
            content=content,
        )

    async def _process_entries(
        self, session, entries: List[FeedParserDict], subsystem: Subsystem
    ) -> Tuple[int, int, List[FeedEntry]]:
        """处理条目并返回统计信息"""
        new_count = 0
        reply_count = 0
        processed_entries: List[FeedEntry] = []

        for entry in entries:
            email_message = await self.save_email_message(session, entry, subsystem)
            is_reply = self.is_reply_message(entry.title)
            if is_reply:
                reply_count += 1
            else:
                new_count += 1
            processed_entries.append(self._create_feed_entry(email_message, entry))

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
