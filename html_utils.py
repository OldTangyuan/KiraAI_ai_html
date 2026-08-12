"""
HTML 输入相关的纯函数：校验与格式化。
不依赖 KiraAI 框架与 Playwright，便于单独单元测试。
"""
from typing import Optional


def validate_input(description: str, html_code: str) -> Optional[str]:
    """
    校验 LLM 传入的描述与 HTML 代码是否合法。
    返回错误信息字符串；输入合法时返回 None。
    """
    if not description or len(description.strip()) < 3:
        return "错误：网页描述为空或过短，无法生成。"
    if not html_code or len(html_code.strip()) < 30:
        return "错误：HTML 代码为空或过短，请生成有效的 HTML 页面。"
    return None


def clean_markdown_fence(html_code: str) -> str:
    """
    清理 LLM 输出中常见的 markdown 代码块包装（```html ... ```）。
    """
    html = html_code.strip()
    if html.startswith("```html"):
        html = html[7:]
    if html.endswith("```"):
        html = html[:-3]
    return html.strip()
