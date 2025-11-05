"""NoneBot 应用入口

负责初始化 NoneBot、加载配置、注册适配器等。
"""

import os
import nonebot


driver_spec = os.getenv("DRIVER", "~fastapi+~httpx+~websockets")
nonebot.init(driver=driver_spec)

nonebot.load_from_toml("pyproject.toml")

# 手动注册适配器（作为 load_from_toml 的后备方案）
driver = nonebot.get_driver()
if not getattr(driver, "_adapters", None):
    try:
        from nonebot.adapters.discord import Adapter as DiscordAdapter

        driver.register_adapter(DiscordAdapter)
    except (ImportError, AttributeError, RuntimeError):
        pass

    try:
        from nonebot.adapters.feishu import Adapter as FeishuAdapter

        driver.register_adapter(FeishuAdapter)
    except (ImportError, AttributeError, RuntimeError):
        pass

app = nonebot.get_asgi()

if __name__ == "__main__":
    nonebot.run()
