"""PATCH 卡片过滤规则命令模块"""

from nonebot import on_message
from nonebot.adapters import Event, Message
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.params import EventMessage
from nonebot.rule import to_me

from lkml.db.repo import (
    PatchCardFilterRepository,
    PatchCardRepository,
    FilterConfigRepository,
)
from lkml.service.patch_card_filter_service import PatchCardFilterService
from ..shared import (
    extract_command,
    get_user_info,
    register_command,
    check_admin,
    get_database,
    send_embed_message,
)

# 仅当消息 @ 到机器人，并且以 "/filter" 开头时处理
FilterCmd = on_message(rule=to_me(), priority=50, block=False)


def _convert_scalar(s: str):
    """转换标量值，处理引号"""
    try:
        return int(s)
    except ValueError:
        # 去除首尾的引号（单引号或双引号）
        s = s.strip()
        if (s.startswith('"') and s.endswith('"')) or (
            s.startswith("'") and s.endswith("'")
        ):
            s = s[1:-1]
        return s


def _build_help_embed() -> dict:
    """构建帮助信息的 embed 字典"""
    description = """**命令格式**
```
/filter rule <command> [参数...]
```
**规则组管理**
• `rule add <name> <type>=<pattern> [...]` - 创建或更新规则组（如果规则组和类型已存在，则添加条件值）
• `rule list` - 列出所有规则组
• `rule show <name>` - 显示规则组详情
• `rule del <name>` - 删除整个规则组
• `rule del <name> <type>` - 删除规则组中的类型
• `rule del <name> <type>=<pattern>` - 删除规则组中类型的某个条件值
• `rule enable <name>` - 启用规则组
• `rule disable <name>` - 禁用规则组

**类型管理**
• `rule type list` - 查看支持的过滤类型

**配置管理**
• `config exclusive <on|off>` - 设置独占模式（全局配置）

**示例**
```
/filter config exclusive on
/filter rule add riscv-rust subsys=riscv subject=rust-for-linux
/filter rule add riscv-rust subject=rust  # 添加条件值到已存在的类型
/filter rule del riscv-rust author_email  # 删除类型
/filter rule del riscv-rust subject=rust  # 删除类型的某个条件值
/filter rule type list
```"""

    return {
        "title": "Filter 命令帮助",
        "description": description,
        "color": 0x5865F2,  # Discord 蓝色
        "footer": {"text": "LKML Bot"},
    }


async def _send_help_embed(event: Event) -> None:
    """发送帮助信息的 embed"""
    embed = _build_help_embed()
    await send_embed_message(event, embed["title"], embed["description"], FilterCmd)


async def _send_embed_response(
    event: Event, title: str, description: str, color: int = 0x5865F2
) -> None:
    """发送 embed 格式的响应（辅助函数）

    Args:
        event: 事件对象
        title: embed 标题
        description: embed 描述
        color: embed 颜色，默认 Discord 蓝色
    """
    await send_embed_message(event, title, description, FilterCmd, color)


def _handle_type() -> str:
    """处理显示支持的过滤类型命令"""
    filter_types = PatchCardFilterService.get_supported_filter_types()

    lines = ["过滤类型:\n"]
    for filter_type, description in filter_types.items():
        lines.append(f"• {filter_type}: {description}")

    lines.append("\n模式格式:")
    lines.append("• 普通文本: 精确/包含匹配（大小写不敏感）")
    lines.append("• /regex/: 正则匹配（区分大小写，默认）")
    lines.append("• /regex/i: 正则匹配（不区分大小写，标准 i 标志）")
    lines.append("• 列表: 逗号分隔，表示 OR 逻辑（任一匹配即可）")

    return "\n".join(lines)


def _format_rule_group_response(name: str, filter_data) -> str:
    """格式化规则组响应消息"""
    lines = [
        f"✅ 已添加规则组: {name}",
        f"ID: {filter_data.id}",
        "\n条件:",
    ]
    for filter_type, pattern in filter_data.filter_conditions.items():
        pattern_list = pattern if isinstance(pattern, list) else [pattern]
        pattern_str = (
            "["
            + ", ".join(
                f"'{p}'" if isinstance(p, str) else str(p) for p in pattern_list
            )
            + "]"
        )
        lines.append(f"  {filter_type}: {pattern_str}")
    return "\n".join(lines)


def _create_filter_service(session) -> PatchCardFilterService:
    """创建过滤服务实例"""
    filter_repo = PatchCardFilterRepository(session)
    patch_card_repo = PatchCardRepository(session)
    filter_config_repo = FilterConfigRepository(session)
    return PatchCardFilterService(filter_repo, patch_card_repo, filter_config_repo)


async def _handle_config_command(
    event: Event, filter_service: PatchCardFilterService, parts: list
) -> None:
    """处理 config 子命令"""
    try:
        user_id, user_name = get_user_info(event)
    except (AttributeError, ValueError, TypeError):
        await _send_embed_response(event, "❌ 错误", "无法获取用户信息", 0xE74C3C)
        return
    resp_msg = await _handle_config(filter_service, parts, user_id, user_name)
    if resp_msg:
        color = 0x2ECC71 if resp_msg.startswith("✅") else 0xE74C3C
        title = "配置结果" if resp_msg.startswith("✅") else "❌ 错误"
        await _send_embed_response(event, title, resp_msg, color)


async def _handle_type_command(event: Event, parts: list) -> None:
    """处理 type 子命令"""
    if len(parts) >= 4 and parts[3].lower() == "list":
        resp_msg = _handle_type()
        if resp_msg:
            await _send_embed_response(event, "📋 支持的过滤类型", resp_msg)
        return
    await _send_embed_response(
        event, "❌ 用法错误", "用法: /filter rule type list", 0xE74C3C
    )


def _get_response_color_and_title(resp_msg: str) -> tuple[int, str]:
    """根据响应消息获取颜色和标题"""
    if resp_msg.startswith("✅"):
        return (0x2ECC71, "操作成功")
    if resp_msg.startswith("❌"):
        return (0xE74C3C, "❌ 错误")
    return (0x5865F2, "信息")


async def _execute_rule_command(
    rule_cmd: str, filter_service: PatchCardFilterService, parts: list, event: Event
) -> str:
    """执行 rule 子命令并返回响应消息"""
    if rule_cmd == "add":
        try:
            user_id, user_name = get_user_info(event)
        except (AttributeError, ValueError, TypeError):
            await _send_embed_response(event, "❌ 错误", "无法获取用户信息", 0xE74C3C)
            return ""
        return await _handle_rule_add(filter_service, parts, user_id, user_name)

    handlers = {
        "list": lambda: _handle_rule_list(filter_service),
        "show": lambda: _handle_rule_show(filter_service, parts),
        "del": lambda: _handle_rule_del(filter_service, parts),
        "enable": lambda: _handle_rule_enable(filter_service, parts),
        "disable": lambda: _handle_rule_disable(filter_service, parts),
    }

    handler = handlers.get(rule_cmd)
    if handler:
        return await handler()
    return f"❌ 未知的 rule 子命令: {rule_cmd}"


async def _handle_rule_command(
    event: Event, filter_service: PatchCardFilterService, parts: list
) -> None:
    """处理 rule 子命令"""
    if len(parts) < 3:
        await _send_embed_response(
            event,
            "❌ 用法错误",
            "用法: /filter rule <add|list|show|del|enable|disable|type> [参数...]",
            0xE74C3C,
        )
        return

    rule_cmd = parts[2].lower()
    resp_msg = await _execute_rule_command(rule_cmd, filter_service, parts, event)

    if resp_msg:
        color, title = _get_response_color_and_title(resp_msg)
        await _send_embed_response(event, title, resp_msg, color)


@FilterCmd.handle()
async def handle_filter(event: Event, message: Message = EventMessage()):
    """处理过滤规则命令

    支持的子命令：
    - /filter help - 显示帮助信息
    - /filter rule add <name> <type1>=<pattern1> [<type2>=<pattern2> ...]
    - /filter config exclusive <on|off>
    - /filter rule list
    - /filter rule show <name>
    - /filter rule del <name>
    - /filter rule enable <name>
    - /filter rule disable <name>
    - /filter rule condition add <name> <type>=<pattern>
    - /filter rule condition del <name> <type>=<pattern>
    - /filter rule type list
    """
    try:
        if not check_admin(event):
            await _send_embed_response(
                event, "❌ 权限不足", "此命令仅管理员可用", 0xE74C3C
            )
            return

        text = message.extract_plain_text().strip()

        command_text = extract_command(text, "/filter")
        if command_text is None:
            return

        parts = command_text.split()
        if len(parts) < 2:
            await _send_help_embed(event)
            return

        subcommand = parts[1].lower()

        if subcommand == "help":
            await _send_help_embed(event)
            return

        database = get_database()
        if not database:
            await _send_embed_response(event, "❌ 错误", "数据库未初始化", 0xE74C3C)
            return

        async with database.get_db_session() as session:
            filter_service = _create_filter_service(session)
            if subcommand == "config":
                await _handle_config_command(event, filter_service, parts)
            elif subcommand == "rule":
                if len(parts) >= 3 and parts[2].lower() == "type":
                    await _handle_type_command(event, parts)
                else:
                    await _handle_rule_command(event, filter_service, parts)
            else:
                await _send_embed_response(
                    event,
                    "❌ 用法错误",
                    "用法: /filter rule <add|list|show|del|enable|disable|type> [参数...]\n"
                    "或: /filter config exclusive <on|off>",
                    0xE74C3C,
                )

    except FinishedException:
        raise
    except (ValueError, RuntimeError, AttributeError) as e:
        logger.error(f"Error in filter command: {e}", exc_info=True)
        await _send_embed_response(
            event, "❌ 错误", f"处理命令时发生错误: {str(e)}", 0xE74C3C
        )


def _parse_condition_value(joined: str):
    """解析条件值"""
    if "," in joined:
        items = [s.strip() for s in joined.split(",") if s.strip()]
        return [_convert_scalar(x) for x in items]
    return _convert_scalar(joined.strip())


def _merge_condition_value(existing, new_value):
    """合并条件值"""
    if isinstance(existing, list):
        if isinstance(new_value, list):
            merged_list = existing.copy()
            for nv in new_value:
                if not any(str(p).strip() == str(nv).strip() for p in merged_list):
                    merged_list.append(nv)
            return merged_list
        if not any(str(p).strip() == str(new_value).strip() for p in existing):
            return existing + [new_value]
        return existing
    if isinstance(new_value, list):
        return [existing] + new_value
    if str(existing).strip() != str(new_value).strip():
        return [existing, new_value]
    return existing


def _parse_filter_conditions(parts: list) -> dict:
    """解析过滤条件"""
    conditions = {}
    i = 4
    while i < len(parts):
        part = parts[i]
        if "=" in part:
            k, v = part.split("=", 1)
            acc = [v]
            j = i + 1
            while j < len(parts) and ("=" not in parts[j]):
                acc.append(parts[j])
                j += 1
            joined = " ".join(acc)
            new_value = _parse_condition_value(joined)

            if k in conditions:
                conditions[k] = _merge_condition_value(conditions[k], new_value)
            else:
                conditions[k] = new_value

            i = j
            continue
        i += 1
    return conditions


async def _handle_rule_add(
    filter_service: PatchCardFilterService,
    parts: list,
    user_id: str,
    user_name: str,
) -> str:
    """处理添加规则组命令

    如果规则组已存在且类型已存在，则添加条件值到该类型
    如果规则组不存在或类型不存在，则创建新的规则组或添加新类型
    """
    if len(parts) < 5:
        return (
            "❌ 用法: /filter rule add <name> <type1>=<pattern1> [<type2>=<pattern2> ...]\n"
            "示例: /filter rule add riscv-rust subsys=riscv subject=rust-for-linux"
        )

    name = parts[3]
    conditions = _parse_filter_conditions(parts)

    if not conditions:
        return (
            "❌ 条件缺失，使用 key=value 形式，例如 subsys=riscv subject=rust-for-linux"
        )

    try:
        # 使用 create_rule_group，它会自动处理合并逻辑
        # 如果规则组已存在，会合并条件；如果类型已存在，会添加条件值
        await filter_service.create_rule_group(
            name=name,
            filter_conditions=conditions,
            created_by=f"{user_name} ({user_id})",
            enabled=True,
        )

        # 重新查询获取最新数据，确保回显正确
        filter_data = await filter_service.get_rule_group(name)
        if not filter_data:
            return "❌ 创建规则组失败: 无法获取规则组数据"

        return _format_rule_group_response(name, filter_data)
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to create rule group: {e}", exc_info=True)
        return f"❌ 创建规则组失败: {str(e)}"


async def _handle_rule_list(filter_service: PatchCardFilterService) -> str:
    """处理列出规则组命令"""
    try:
        rule_groups = await filter_service.list_rule_groups()
        if not rule_groups:
            return "📋 没有找到规则组"

        # 获取全局独占模式配置
        exclusive_mode = False
        if filter_service.filter_config_repo:
            exclusive_mode = (
                await filter_service.filter_config_repo.get_exclusive_mode()
            )

        global_mode = "🔒 独占模式" if exclusive_mode else "⭐ 高亮模式"
        lines = [f"规则组列表 (全局模式: {global_mode}):\n"]
        for group_name in rule_groups:
            filter_data = await filter_service.get_rule_group(group_name)
            if filter_data:
                status = "✅ 启用" if filter_data.enabled else "❌ 禁用"
                lines.append(f"{group_name} - {status}")
                lines.append(f"  条件数量: {len(filter_data.filter_conditions)}")
                lines.append("")

        return "\n".join(lines)
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to list rule groups: {e}", exc_info=True)
        return f"❌ 列出规则组失败: {str(e)}"


async def _handle_rule_show(filter_service: PatchCardFilterService, parts: list) -> str:
    """处理显示规则组详情命令"""
    if len(parts) < 4:
        return "❌ 用法: /filter rule show <name>"

    name = parts[3]

    try:
        filter_data = await filter_service.get_rule_group(name)
        if not filter_data:
            return f"❌ 未找到规则组: {name}"

        # 获取全局独占模式配置
        exclusive_mode = False
        if filter_service.filter_config_repo:
            exclusive_mode = (
                await filter_service.filter_config_repo.get_exclusive_mode()
            )

        status = "✅ 启用" if filter_data.enabled else "❌ 禁用"
        mode = (
            "🔒 独占模式（只允许匹配的创建）"
            if exclusive_mode
            else "⭐ 高亮模式（所有都创建但高亮匹配的）"
        )
        lines = [
            f"规则组详情: {name}",
            f"状态: {status}",
            f"全局模式: {mode}",
        ]

        if filter_data.created_by:
            lines.append(f"创建者: {filter_data.created_by}")

        lines.append("\n条件:")
        for filter_type, pattern in filter_data.filter_conditions.items():
            # 统一使用列表格式显示
            if isinstance(pattern, list):
                pattern_list = pattern
            else:
                # 单个值转为列表
                pattern_list = [pattern]
            # 列表格式：显示为 Python 列表样式
            pattern_str = (
                "["
                + ", ".join(
                    f"'{p}'" if isinstance(p, str) else str(p) for p in pattern_list
                )
                + "]"
            )
            lines.append(f"  {filter_type}: {pattern_str}")

        return "\n".join(lines)
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to show rule group: {e}", exc_info=True)
        return f"❌ 显示规则组失败: {str(e)}"


async def _handle_config(
    filter_service: PatchCardFilterService, parts: list, _user_id: str, _user_name: str
) -> str:
    """处理配置命令"""
    if len(parts) < 4:
        return "❌ 用法: /filter config exclusive <on|off>"

    config_key = parts[2].lower()
    config_value = parts[3].lower()

    if config_key != "exclusive":
        return f"❌ 未知配置项: {config_key}\n支持的配置项: exclusive"

    if config_value not in ("on", "off"):
        return "❌ 配置值必须是 on 或 off"

    if not filter_service.filter_config_repo:
        return "❌ 配置仓储未初始化"

    try:
        enabled = config_value == "on"
        await filter_service.filter_config_repo.set_exclusive_mode(enabled)
        mode_text = "独占模式" if enabled else "高亮模式"
        return f"✅ 已设置全局模式: {mode_text}"
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to set config: {e}", exc_info=True)
        return f"❌ 设置配置失败: {str(e)}"


async def _delete_condition_value(
    filter_service: PatchCardFilterService, name: str, filter_type: str, pattern
) -> str:
    """删除条件值"""
    await filter_service.remove_condition_from_rule_group(
        name, filter_type.strip(), pattern
    )
    updated_filter = await filter_service.get_filter(name=name)
    if not updated_filter:
        return f"❌ 规则组不存在: {name}"

    if filter_type in updated_filter.filter_conditions:
        current_conditions = updated_filter.filter_conditions[filter_type]
        pattern_list = (
            current_conditions
            if isinstance(current_conditions, list)
            else [current_conditions]
        )
        pattern_str = (
            "["
            + ", ".join(
                f"'{p}'" if isinstance(p, str) else str(p) for p in pattern_list
            )
            + "]"
        )
    else:
        pattern_str = "无"

    return (
        f"✅ 已从规则组 '{name}' 的 '{filter_type}' 类型删除条件: {pattern_str.strip()}\n"
        f"当前 {filter_type} 条件: {pattern_str}"
    )


async def _delete_filter_types(
    filter_service: PatchCardFilterService, name: str, filter_types: list
) -> str:
    """删除过滤类型"""
    await filter_service.remove_types_from_rule_group(name, filter_types)
    updated_filter = await filter_service.get_filter(name=name)
    if not updated_filter:
        return (
            f"✅ 已从规则组 '{name}' 删除类型: {', '.join(filter_types)}\n"
            "规则组已为空，已删除"
        )

    remaining_types = list(updated_filter.filter_conditions.keys())
    return (
        f"✅ 已从规则组 '{name}' 删除类型: {', '.join(filter_types)}\n"
        f"剩余类型: {', '.join(remaining_types) if remaining_types else '无'}"
    )


async def _delete_rule_group(filter_service: PatchCardFilterService, name: str) -> str:
    """删除整个规则组"""
    success = await filter_service.delete_rule_group(name)
    if success:
        return f"✅ 已删除规则组: {name}"
    return f"❌ 未找到规则组: {name}"


async def _handle_rule_del(filter_service: PatchCardFilterService, parts: list) -> str:
    """处理删除规则组命令

    支持三种形式：
    1. rule del <name> - 删除整个规则组
    2. rule del <name> <type> - 删除规则组中的类型
    3. rule del <name> <type>=<pattern> - 删除规则组中类型的某个条件值
    """
    if len(parts) < 4:
        return "❌ 用法: /filter rule del <name> [<type>|<type>=<pattern>]"

    name = parts[3]

    try:
        if len(parts) < 5:
            return await _delete_rule_group(filter_service, name)

        remaining = " ".join(parts[4:])
        if "=" in remaining:
            filter_type, pattern_str = remaining.split("=", 1)
            pattern = _convert_scalar(pattern_str.strip())
            return await _delete_condition_value(
                filter_service, name, filter_type, pattern
            )

        filter_types_str = remaining.strip()
        filter_types = [t.strip() for t in filter_types_str.split(",") if t.strip()]
        if not filter_types:
            return "❌ 请指定要删除的类型"
        return await _delete_filter_types(filter_service, name, filter_types)
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to delete rule: {e}", exc_info=True)
        return f"❌ 删除失败: {str(e)}"


async def _handle_rule_enable(
    filter_service: PatchCardFilterService, parts: list
) -> str:
    """处理启用规则组命令"""
    if len(parts) < 4:
        return "❌ 用法: /filter rule enable <name>"

    name = parts[3]

    try:
        success = await filter_service.toggle_filter(name=name, enabled=True)
        if success:
            return f"✅ 已启用规则组: {name}"
        return f"❌ 未找到规则组: {name}"
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to enable rule group: {e}", exc_info=True)
        return f"❌ 启用规则组失败: {str(e)}"


async def _handle_rule_disable(
    filter_service: PatchCardFilterService, parts: list
) -> str:
    """处理禁用规则组命令"""
    if len(parts) < 4:
        return "❌ 用法: /filter rule disable <name>"

    name = parts[3]

    try:
        success = await filter_service.toggle_filter(name=name, enabled=False)
        if success:
            return f"✅ 已禁用规则组: {name}"
        return f"❌ 未找到规则组: {name}"
    except (RuntimeError, ValueError, AttributeError) as e:
        logger.error(f"Failed to disable rule group: {e}", exc_info=True)
        return f"❌ 禁用规则组失败: {str(e)}"


# 在导入时注册命令元信息（管理员命令）
register_command(
    name="filter",
    usage="/filter <help|rule> [参数...]",
    description="管理 PATCH 卡片过滤规则组",
    admin_only=True,
)
