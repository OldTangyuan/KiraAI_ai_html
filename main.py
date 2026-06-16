from core.plugin import BasePlugin, PluginContext, get_logger
from core.plugin import register
from core.chat import MessageChain, KiraMessageBatchEvent
from core.chat.message_elements import Image

import asyncio
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright

logger = get_logger('plugin-AIHTML', 'orange')

# ---------- 常量 ----------
SCREENSHOT_WIDTH = 1280
SCREENSHOT_HEIGHT = 800
DEBUG_SAVE_HTML = True


async def find_system_browser():
    """
    检测系统中可用的 Chrome/Chromium/Edge 浏览器。
    返回 (channel_name, 显示名称)，若都不可用返回 None。
    """
    candidates = [
        ("chrome",  "Google Chrome"),
        ("msedge",  "Microsoft Edge"),
        ("chromium", "Chromium"),
    ]

    for channel, display_name in candidates:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(channel=channel, headless=True)
                await browser.close()
            logger.info(f"检测到系统浏览器: {display_name}")
            return channel
        except Exception:
            continue

    # 最后尝试无 channel（Playwright 内置 Chromium）
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
        logger.info("未检测到系统浏览器，使用 Playwright 内置 Chromium。")
        return None
    except Exception:
        return None


class AIHTML(BasePlugin):
    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)
        self.data_dir: Path = None
        self.output_dir: Path = None
        self._browser_ready = asyncio.Event()
        self._browser_channel = None

    async def initialize(self):
        """插件加载时调用，在此初始化资源、注册事件等"""
        # 系统浏览器检测放在后台，不阻塞主程序启动
        asyncio.ensure_future(self._init_browser())
        self.data_dir = self.ctx.get_plugin_data_dir()
        self.output_dir = self.data_dir / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info('AIHTML 插件加载完成！（浏览器检测将在后台进行）')

    async def _init_browser(self):
        """后台检测系统中可用的 Chrome/Chromium/Edge 浏览器。"""
        try:
            channel = await find_system_browser()
            self._browser_channel = channel
            if channel:
                logger.info(f"将使用系统浏览器 (channel={channel}) 渲染截图。")
            else:
                logger.warning("未找到任何可用的浏览器，插件渲染功能不可用。")
        except Exception as e:
            logger.error(f"浏览器检测失败: {e}")
        finally:
            self._browser_ready.set()

    async def terminate(self):
        pass

    # ==================== 核心逻辑 ====================

    async def _render_html_to_image(self, html_content: str, output_path: str):
        """
        使用系统中已安装的 Chrome/Chromium/Edge 将 HTML 渲染为 PNG 截图。
        在浏览器就绪前会自动等待。
        """
        if not html_content or len(html_content) < 30:
            raise ValueError("HTML 内容为空或过短，无法渲染。")

        # 等待浏览器检测完成
        await self._browser_ready.wait()

        async with async_playwright() as p:
            launch_kwargs = {"headless": True}
            if self._browser_channel:
                launch_kwargs["channel"] = self._browser_channel

            try:
                browser = await p.chromium.launch(**launch_kwargs)
            except Exception as e:
                raise RuntimeError(
                    f"浏览器启动失败: {e}\n"
                    f"请确保系统已安装 Chrome/Chromium/Edge。"
                )

            page = await browser.new_page(
                viewport={"width": SCREENSHOT_WIDTH, "height": SCREENSHOT_HEIGHT}
            )

            try:
                await page.set_content(
                    html_content, wait_until="domcontentloaded", timeout=10000
                )
            except Exception as e:
                await browser.close()
                raise RuntimeError(f"Playwright 加载 HTML 失败: {e}")

            await page.wait_for_timeout(1500)
            try:
                await page.wait_for_function(
                    "document.body && document.body.scrollHeight > 10",
                    timeout=3000
                )
            except Exception:
                logger.warning("检测到 body 高度可能为 0，页面可能空白。")

            try:
                await page.screenshot(path=output_path, full_page=True)
            except Exception:
                logger.warning("full_page 截图失败，尝试视口截图...")
                await page.screenshot(path=output_path, full_page=False)
            finally:
                await browser.close()

        logger.info(f"截图已保存至: {output_path}")

    async def _generate_and_save_webpage(
        self, description: str, html_code: str, event: KiraMessageBatchEvent = None
    ) -> str:
        """
        核心整合逻辑：
          1. 校验并保存 LLM 主模型传入的 HTML 代码
          2. 用 Playwright 渲染截图
          3. 通过 publish_notice 发送图片到会话
          4. 返回文字结果回 LLM
        """
        if not description or len(description.strip()) < 3:
            return "错误：网页描述为空或过短，无法生成。"
        if not html_code or len(html_code.strip()) < 30:
            return "错误：HTML 代码为空或过短，请生成有效的 HTML 页面。"

        # 清理可能的 markdown 包装
        html = html_code.strip()
        if html.startswith("```html"):
            html = html[7:]
        if html.endswith("```"):
            html = html[:-3]
        html = html.strip()

        timestamp = int(time.time())
        png_path = self.output_dir / f"webpage_{timestamp}.png"

        try:
            logger.info(f"开始渲染网页，描述：{description}")

            # 调试保存 HTML
            if DEBUG_SAVE_HTML:
                html_path = png_path.with_suffix(".html")
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info(f"HTML 已保存至: {html_path}")

            # 渲染截图
            logger.info("开始渲染截图...")
            await self._render_html_to_image(html, str(png_path))

            # 通过 notice 发送图片到会话
            if event:
                img = Image(image=str(png_path))
                chain = MessageChain([img])
                await self.ctx.publish_notice(
                    session=event.session.session_id,
                    chain=chain,
                    is_mentioned=True
                )

            return f"成功！网页截图已保存至：{png_path}"

        except Exception as e:
            error_msg = f"渲染失败：{e}"
            logger.error(error_msg)
            error_file = png_path.with_suffix(".error.log")
            with open(error_file, "w", encoding="utf-8") as f:
                f.write(f"{error_msg}\n描述：{description}\n")
            return f"错误：{error_msg}，详情已写入 {error_file}"

    # ==================== 注册为 LLM 可调用工具 ====================

    @register.tool(
        name="generate_and_save_webpage",
        description="将你已生成的 HTML 代码渲染为网页截图并发送到当前会话。"
                    "调用前请先生成简洁美观的 HTML 代码（含 <!DOCTYPE html>），"
                    "注意：不要包含 JavaScript 交互代码或复杂动画，"
                    "因为页面会以静态图片形式展示给用户。页面设计应简洁清晰、色彩搭配舒适。",
        params={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "对网页界面需求的简要描述，用于日志记录。",
                },
                "html_code": {
                    "type": "string",
                    "description": "您生成的完整 HTML 代码，必须包含 <!DOCTYPE html>。"
                                   "页面应简洁美观，无需 JS 交互逻辑。",
                },
            },
            "required": ["description", "html_code"],
        }
    )
    async def tool_generate_webpage(
        self, event: KiraMessageBatchEvent, description: str, html_code: str
    ):
        """
        LLM tool call 入口。
        主模型生成 HTML 后传入此工具进行渲染和发送。
        """
        logger.info(
            f"Tool called: generate_and_save_webpage, description={description}"
        )
        result = await self._generate_and_save_webpage(description, html_code, event)
        return result



