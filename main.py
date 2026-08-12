from core.plugin import BasePlugin, PluginContext, get_logger
from core.plugin import register
from core.chat import MessageChain, KiraMessageBatchEvent
from core.chat.message_elements import Image

import asyncio
import time
from pathlib import Path

from .browser import BrowserManager
from .renderer import HtmlRenderer
from .html_utils import clean_markdown_fence, validate_input

logger = get_logger('plugin-AIHTML', 'orange')

# ---------- 常量 ----------
DEBUG_SAVE_HTML = True


class AIHTML(BasePlugin):
    """
    AIHTML 插件：将 AI 生成的 HTML 渲染为网页截图并发送到当前会话。

    核心流程：
      1. LLM 生成 HTML 代码（不含复杂 JS 交互）
      2. 调用 generate_and_save_webpage 工具，用浏览器渲染为 PNG
      3. 通过 adapter 将图片直接发送到会话（群聊 / 私聊）
    """

    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)
        self.data_dir: Path = None
        self.output_dir: Path = None
        self._browser = BrowserManager()
        self._renderer = HtmlRenderer()

    async def initialize(self):
        """插件加载时调用，在此初始化资源、注册事件等"""
        # 系统浏览器检测放在后台，不阻塞主程序启动
        asyncio.ensure_future(self._browser.initialize())
        self.data_dir = self.ctx.get_plugin_data_dir()
        self.output_dir = self.data_dir / "output"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info('AIHTML 插件加载完成！（浏览器检测将在后台进行）')

    async def terminate(self):
        pass

    # ==================== 核心逻辑 ====================

    async def _generate_and_save_webpage(
        self, description: str, html_code: str, event: KiraMessageBatchEvent = None
    ) -> str:
        """
        核心整合逻辑：
          1. 校验并保存 LLM 主模型传入的 HTML 代码
          2. 用 Playwright 渲染截图
          3. 通过 adapter 直接发送图片到会话
          4. 返回文字结果回 LLM
        """
        # 校验输入
        error = validate_input(description, html_code)
        if error:
            return error

        # 清理可能的 markdown 包装
        html = clean_markdown_fence(html_code)

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
            await self._renderer.render(
                html,
                str(png_path),
                browser_channel=self._browser.channel,
                browser_ready=self._browser.ready,
            )

            # 通过 adapter 直接发送图片
            if event:
                ada = self.ctx.adapter_mgr.get_adapter(event.session.adapter_name)
                if ada:
                    img = Image(image=str(png_path))
                    chain = MessageChain([img])
                    if event.is_group_message():
                        await ada.send_group_message(
                            group_id=event.session.session_id,
                            send_message_obj=chain
                        )
                    else:
                        await ada.send_direct_message(
                            user_id=event.session.session_id,
                            send_message_obj=chain
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
                    "因为页面会以静态图片形式展示给用户，且图片会被系统自动发送给用户，因此你不需要额外生图。页面设计应简洁清晰、色彩搭配舒适。",
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
                                   "页面应简洁美观，无需 JS 交互逻辑。理论上你可以通过 HTML 生成一切内容，或与用户进行文本对话来进一步调整 HTML 来实现类似直接在网页点击的交互效果。",
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
