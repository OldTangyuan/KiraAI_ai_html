"""
浏览器环境管理：检测系统浏览器，必要时自动下载 Playwright 内置 Chromium。
"""
import asyncio
import sys

from playwright.async_api import async_playwright

from core.plugin import get_logger

logger = get_logger('plugin-AIHTML', 'orange')

# 优先尝试的系统浏览器： (channel 名, 显示名)
_BROWSER_CANDIDATES = [
    ("chrome",   "Google Chrome"),
    ("msedge",   "Microsoft Edge"),
    ("chromium", "Chromium"),
]


async def find_or_install_browser():
    """
    检测系统中可用的 Chrome/Chromium/Edge 浏览器。
    若都不存在，则异步下载 Playwright 内置 Chromium。
    返回 (channel_name: str | None)，channel=None 表示使用内置 Chromium。
    """
    for channel, display_name in _BROWSER_CANDIDATES:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel=channel, headless=True)
                await browser.close()
            logger.info(f"检测到系统浏览器: {display_name}")
            return channel
        except Exception:
            continue

    # 系统无可用浏览器 → 在后台安装 Playwright 内置 Chromium
    logger.info("未检测到系统浏览器，将在后台下载 Chromium（首次需要较长时间）...")

    # 安装 Chromium
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode() if stderr else f"退出码 {proc.returncode}")
        logger.info("Chromium 下载完成。")
    except Exception as e:
        raise RuntimeError(
            f"Chromium 自动下载失败: {e}\n"
            f"请尝试手动运行: {sys.executable} -m playwright install chromium"
        )

    # 验证安装
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
        logger.info("Chromium 安装验证通过。")
    except Exception as e:
        raise RuntimeError(
            f"Chromium 安装后仍无法启动: {e}\n"
            f"当前系统可能缺少必要的运行时库。"
        )

    return None  # None = 使用内置 Chromium（不指定 channel）


class BrowserManager:
    """
    插件浏览器环境的统一管理：
    - 后台初始化（检测系统浏览器 / 自动下载内置 Chromium）
    - 暴露渲染所需的就绪状态与 channel
    """

    def __init__(self):
        self._channel = None
        self._ready = asyncio.Event()

    @property
    def channel(self):
        """浏览器 channel 名；None 表示使用 Playwright 内置 Chromium。"""
        return self._channel

    @property
    def ready(self) -> asyncio.Event:
        """浏览器环境就绪事件，渲染前需等待。"""
        return self._ready

    async def initialize(self):
        """
        后台检测系统浏览器，若均不存在则自动下载内置 Chromium。
        完成后设置 ready 事件，供渲染逻辑等待。
        """
        try:
            channel = await find_or_install_browser()
            self._channel = channel
            if channel:
                logger.info(f"将使用系统浏览器 (channel={channel}) 渲染截图。")
            else:
                logger.info("将使用 Playwright 内置 Chromium 渲染截图。")
        except Exception as e:
            logger.error(f"浏览器初始化失败，插件渲染功能不可用: {e}")
        finally:
            self._ready.set()
