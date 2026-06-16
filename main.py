from core.plugin import BasePlugin, PluginContext, get_logger
from core.plugin import register
from core.chat import MessageChain, KiraMessageBatchEvent
from core.chat.message_elements import Image

import subprocess
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright

logger = get_logger('plugin-AIHTML', 'orange')

# ---------- 常量 ----------
SCREENSHOT_WIDTH = 1280
SCREENSHOT_HEIGHT = 800
DEBUG_SAVE_HTML = True


async def ensure_chromium_installed():
    """
    检查 Chromium 是否已安装并可正常运行，若未安装则自动安装。
    兼容 Windows 和 Linux 环境。
    """
    # 先尝试启动 Chromium 验证是否可用
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            await browser.close()
        logger.info("Chromium 已存在且可正常启动。")
        return
    except Exception as e:
        logger.warning(f"Chromium 启动检查失败: {e}")

    # 启动失败 → 尝试安装 Chromium
    logger.info("正在安装 Chromium（视网络情况可能需要较长时间）...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("Chromium 安装完成。")
    except Exception as install_err:
        raise RuntimeError(
            f"Chromium 自动安装失败: {install_err}\n"
            f"请尝试手动运行: {sys.executable} -m playwright install chromium"
        )

    # Linux 环境需要额外安装系统依赖；Windows/Mac 上该命令不存在，忽略即可
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install-deps", "chromium"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("Chromium 系统依赖安装完成。")
    except Exception:
        logger.info("跳过 playwright install-deps（非 Linux 环境无需此步骤）。")

    # 安装后再次验证
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            await browser.close()
        logger.info("Chromium 安装验证通过。")
    except Exception as e:
        raise RuntimeError(
            f"Chromium 安装后仍无法启动: {e}\n"
            f"当前系统可能缺少必要的运行时库，请参考 Playwright 官方文档安装依赖。"
        )


class AIHTML(BasePlugin):
    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)
        self.data_dir: Path = None
        self.output_dir: Path = None

    async def initialize(self):
        """插件加载时调用，在此初始化资源、注册事件等"""
        await ensure_chromium_installed()
        self.data_dir = self.ctx.get_plugin_data_dir()
        self.output_dir = self.data_dir / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info('AIHTML 插件加载完成！')

    async def terminate(self):
        pass

    # ==================== 核心逻辑 ====================

    @staticmethod
    async def _render_html_to_image(html_content: str, output_path: str):
        """
        使用 Playwright 将 HTML 渲染为 PNG 截图（异步函数）。
        """
        if not html_content or len(html_content) < 30:
            raise ValueError("HTML 内容为空或过短，无法渲染。")

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as e:
                raise RuntimeError(
                    f"Chromium 浏览器启动失败: {e}\n"
                    f"请确保已安装 Chromium 及系统依赖。"
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



