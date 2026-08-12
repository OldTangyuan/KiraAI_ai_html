"""
HTML → PNG 截图渲染：基于 Playwright，复用系统浏览器或内置 Chromium。
"""
from playwright.async_api import async_playwright

from core.plugin import get_logger

logger = get_logger('plugin-AIHTML', 'orange')

# ---------- 常量 ----------
SCREENSHOT_WIDTH = 1280
SCREENSHOT_HEIGHT = 800


class HtmlRenderer:
    """将 HTML 内容渲染为整页 PNG 截图。"""

    async def render(
        self,
        html_content: str,
        output_path: str,
        *,
        browser_channel=None,
        browser_ready=None,
    ):
        """
        使用系统中已安装的 Chrome/Chromium/Edge 将 HTML 渲染为 PNG 截图。

        browser_channel — 系统浏览器 channel 名；None 使用内置 Chromium。
        browser_ready   — asyncio.Event，提供时渲染前会等待其置位。
        """
        if not html_content or len(html_content) < 30:
            raise ValueError("HTML 内容为空或过短，无法渲染。")

        # 等待浏览器检测完成
        if browser_ready is not None:
            await browser_ready.wait()

        async with async_playwright() as p:
            launch_kwargs = {"headless": True}
            if browser_channel:
                launch_kwargs["channel"] = browser_channel

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
