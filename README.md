# KiraAI-AIHTML

> KiraAI 的一个插件:让 AI 生成 HTML 页面,自动渲染为图片并发送到当前会话。

基于 [KiraAI](https://github.com/OldTangyuan/KiraAI) 的插件系统开发。当用户希望以可视化方式查看内容时,AI 模型会生成一段简洁的 HTML 代码,本插件通过 **Playwright** 调用系统浏览器将其渲染为 PNG 截图,再通过适配器直接发送到会话中——整个过程对用户透明,就像 AI 直接"画"出了一张图。

## 功能特性

- 🖼️ **AI 生成网页,一键渲染成图**:模型生成的 HTML 被自动截图并以图片形式推送到会话
- 🌐 **智能复用系统浏览器**:优先使用本机 Chrome / Edge / Chromium,无需额外安装;若均不存在则自动后台下载内置 Chromium
- 🧠 **免生图,可交互式调整**:页面以静态图片呈现,无需额外调用生图模型;可通过文本对话让 AI 反复调整 HTML,实现类似"点击网页"的迭代效果
- 📁 **自动保存产物**:截图 PNG、原始 HTML、错误日志都会持久化到插件数据目录,便于排查与复用
- 🔌 **开箱即用**:以 LLM 工具 (Tool Call) 形式接入,主模型自动调用,无需人工干预

## 环境要求

| 依赖 | 说明 |
| --- | --- |
| Python 3.8+ | 运行时 |
| [KiraAI](https://github.com/OldTangyuan/KiraAI) | 插件宿主框架,提供 `core.plugin` / `core.chat` 模块 |
| `playwright>=1.60.0` | 浏览器自动化渲染 |
| Chrome / Chromium / Edge | 建议安装(任意一种),否则首次渲染会触发内置 Chromium 下载 |

> 💡 建议在自带浏览器的设备上运行,可跳过 Chromium 下载,首次使用更快。

## 安装与配置

1. 将本插件目录放入 KiraAI 的插件加载目录。
2. 安装依赖:

   ```bash
   pip install -r requirements.txt
   ```

3. (可选)若本机没有可用的系统浏览器,可手动预装 Playwright 内置 Chromium:

   ```bash
   python -m playwright install chromium
   ```

4. 启动 KiraAI,插件加载时会后台检测浏览器,日志中出现 `AIHTML 插件加载完成!` 即表示注册成功。

## 使用说明

本插件通过 LLM 工具调用自动触发,无需手动指令。用户在对话中提出需要可视化展示的需求(如"把这段数据做成图表发给我"),AI 会自动:

1. 生成简洁美观的 HTML 代码(含 `<!DOCTYPE html>`,不含复杂 JS 交互)
2. 调用 `generate_and_save_webpage` 工具
3. 插件渲染截图并直接发送图片到当前会话
4. 工具返回结果给模型,模型可继续基于对话调整 HTML

### 工具参数

`generate_and_save_webpage`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `description` | string | 是 | 网页界面需求的简要描述,用于日志记录 |
| `html_code` | string | 是 | 完整的 HTML 代码,必须包含 `<!DOCTYPE html>` |

### 渲染约束

- 页面以**静态图片**形式展示,因此不应包含 JS 交互或复杂动画
- 建议保持简洁清晰、色彩搭配舒适,以适配 1280×800 视口与整页截图

## 工作原理

```
用户需求 → 主模型生成 HTML → 插件渲染工具
        → 复用系统浏览器 (Chrome/Edge/Chromium) 或内置 Chromium
        → Playwright 全页截图 (1280×800) → 通过适配器发送图片到会话
```

- 浏览器检测在插件初始化时于**后台**进行,不阻塞主程序启动
- 渲染前会自动等待浏览器就绪;若系统浏览器缺失,会自动下载内置 Chromium
- 截图失败时会降级尝试视口截图,并记录错误日志

## 项目结构

```
KiraAI_ai_html/
├── main.py        # 插件入口:生命周期、流程编排、LLM 工具注册
├── browser.py     # 浏览器环境:检测系统浏览器 / 自动下载内置 Chromium
├── renderer.py    # 渲染器:Playwright 将 HTML 渲染为 PNG 截图
├── html_utils.py  # 纯函数:HTML 校验与 markdown 代码块清理
├── manifest.json  # 插件清单
├── requirements.txt
└── README.md
```

- `browser.py` / `renderer.py` 以插件包内相对导入方式被 `main.py` 引用,加载方式与 KiraAI 内置插件(如 `kira-ai`)一致。
- `html_utils.py` 不依赖框架与 Playwright,便于单独单元测试。

## 文件产物

渲染后产物保存在插件数据目录的 `output/` 子目录,以时间戳命名:

| 文件 | 内容 |
| --- | --- |
| `webpage_<时间戳>.png` | 渲染出的网页截图 |
| `webpage_<时间戳>.html` | 原始 HTML(调试保存) |
| `webpage_<时间戳>.error.log` | 渲染失败时的错误信息与描述 |

## 常见问题

**首次渲染很慢?**
首次使用且本机无系统浏览器时,插件会后台下载内置 Chromium,需要几分钟。建议预装浏览器或手动执行 `python -m playwright install chromium`。

**渲染失败,提示浏览器无法启动?**
请确认本机安装了 Chrome / Chromium / Edge 中的任意一种,或安装 Playwright 内置 Chromium 后重启插件。

**生成的图片是空白?**
HTML 可能未渲染出有效内容(如 body 高度为 0)。请让模型提供更完整的 HTML,并确保包含基本的页面结构与内容。

**图片没发送出来?**
请检查对应适配器是否已正确注册,以及当前会话类型(群聊/私聊)是否支持图片消息发送。

## 版本记录

| 版本 | 说明 |
| --- | --- |
| 1.0 | 首个版本:HTML 渲染截图并发送到会话 |

## 许可证

本项目基于 [GNU Affero General Public License v3.0](LICENSE) 开源。
