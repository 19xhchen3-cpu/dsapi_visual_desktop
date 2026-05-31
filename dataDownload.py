#!/usr/bin/env python3
"""
DeepSeek API Usage Data Downloader

自动化下载 DeepSeek 用量数据。

一次性设置（需浏览器界面）：
    python dataDownload.py --save-state-only     # 登录并保存 cookies

日常导出（无浏览器窗口，Playwright 无头模式）：
    python dataDownload.py                       # 读取配置，直接下载
    python dataDownload.py --output-dir ./数据   # 指定输出目录

发现 API 地址（调试用）：
    python dataDownload.py --discover-endpoint   # 捕获导出按钮的网络请求
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# --- 耗时统计 ---
_timings = []

def _log_step(name):
    now = time.perf_counter()
    if _timings:
        elapsed = now - _timings[-1][1]
        print(f"  [{name}] 耗时 {elapsed:.1f}s")
    else:
        print(f"  [{name}]")
    _timings.append((name, now))


def _print_total_time():
    if len(_timings) < 2:
        return
    total = _timings[-1][1] - _timings[0][1]
    print(f"  ------")
    print(f"  总耗时: {total:.1f}s")


# --- 常量 ---
CONFIG_FILE = "config.json"
STORAGE_STATE_FILE = "deepseek_storage_state.json"
USAGE_URL = "https://platform.deepseek.com/usage"
EXPORT_BUTTON_TEXT = "导出"

# 超时设置
NAV_LOAD_TIMEOUT = 30_000       # 页面加载
ELEMENT_TIMEOUT = 20_000        # 元素等待
DOWNLOAD_TIMEOUT = 60_000       # 下载等待
LOGIN_WAIT_TIMEOUT = 180_000    # 手动登录等待


# ============================================================
# 配置管理
# ============================================================

def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return _default_config()
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _default_config() -> dict:
    return {
        "_version": 1,
        "output_dir": ".",
        "storage_state": STORAGE_STATE_FILE,
        "element_timeout": ELEMENT_TIMEOUT,
        "download_timeout": DOWNLOAD_TIMEOUT,
    }


def _save_config(config: dict, config_path: Path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
    print(f"配置已保存: {config_path}")


# ============================================================
# 查找导出按钮（多策略）
# ============================================================

async def _find_export_button(page):
    """多策略查找导出按钮"""
    # 策略1: ds-button 类 + 文本
    btn = page.locator("button.ds-button").filter(has_text=EXPORT_BUTTON_TEXT)
    if await btn.count() > 0:
        return btn.first

    # 策略2: 按文本查找按钮
    btn = page.get_by_role("button", name=EXPORT_BUTTON_TEXT)
    if await btn.count() > 0:
        return btn.first

    # 策略3: 包含文本的任何可点击元素
    btn = page.get_by_text(EXPORT_BUTTON_TEXT, exact=False).first
    if await btn.count() > 0:
        return btn

    return None


async def _wait_for_export_button(page, timeout=10000):
    """轮询等待导出按钮出现（替代固定 timeout）"""
    deadline = time.perf_counter() + timeout / 1000
    while time.perf_counter() < deadline:
        btn = await _find_export_button(page)
        if btn:
            return btn
        await page.wait_for_timeout(500)
    return None


# ============================================================
# 设置模式：保存登录状态（有界面）
# ============================================================

async def _do_save_state(storage_state_path: Path):
    """启动浏览器 → 登录 → 保存 cookies（有界面，仅一次）"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("=" * 60)
        print("浏览器已打开，请在页面中登录 DeepSeek。")
        print(f"地址: {USAGE_URL}")
        print("登录后会自动跳转到用量页面，脚本会继续。")
        print("=" * 60)

        await page.goto(USAGE_URL, wait_until="networkidle", timeout=NAV_LOAD_TIMEOUT)

        try:
            await page.wait_for_url("**/usage", timeout=LOGIN_WAIT_TIMEOUT)
        except PlaywrightTimeout:
            print("登录超时，请重新运行。")
            return

        # 等待页面完全渲染
        await page.wait_for_load_state("networkidle", timeout=ELEMENT_TIMEOUT)
        await page.wait_for_timeout(2000)  # 额外等待前端渲染

        await context.storage_state(path=str(storage_state_path))
        print(f"登录状态已保存: {storage_state_path}")

        await context.close()
        await browser.close()


# ============================================================
# 设置模式：发现导出 API（有界面调试）
# ============================================================

async def _do_discover_endpoint(config: dict, config_path: Path):
    """有界面 → 打开页面 → 点击导出 → 拦截请求 → 保存 API 地址"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # 拦截网络请求
        export_urls = set()

        def on_request(request):
            url = request.url
            if any(kw in url.lower() for kw in ["export", "download", "usage/csv", "usage/file"]):
                if ".deepseek.com" in url:
                    export_urls.add(url)

        page.on("request", on_request)

        print(f"正在打开页面: {USAGE_URL}")
        await page.goto(USAGE_URL, wait_until="networkidle", timeout=NAV_LOAD_TIMEOUT)

        if "/login" in page.url.lower():
            print("请先在浏览器中登录...")
            try:
                await page.wait_for_url("**/usage", timeout=LOGIN_WAIT_TIMEOUT)
            except PlaywrightTimeout:
                print("登录超时")
                return

        print("正在查找导出按钮...")
        btn = await _find_export_button(page)
        if btn is None:
            await page.screenshot(path="debug_discover.png")
            print("未找到导出按钮，已保存截图 debug_discover.png")
            await context.close()
            await browser.close()
            return

        print("正在点击导出，捕获 API 地址...")
        async with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as dl_info:
            await btn.click()
        await dl_info.value

        if export_urls:
            discovered = list(export_urls)
            print(f"\n发现 {len(discovered)} 个请求:")
            for i, url in enumerate(discovered, 1):
                print(f"  {i}. {url}")
            chosen = discovered[-1]
            config["export_api_url"] = chosen
            _save_config(config, config_path)
            print(f"\n已写入 config.json: export_api_url = {chosen}")
        else:
            print("未捕获到导出请求，请检查浏览器 DevTools 的 Network 面板。")

        await context.close()
        await browser.close()


# ============================================================
# 默认模式：Playwright 无头导出（无窗口）
# ============================================================

async def _do_export(config: dict, output_dir: Path, timeout: int):
    """
    Playwright 无头模式 → 加载登录态 → 打开页面 → 点击导出 → 保存文件
    全程无可见浏览器窗口。
    """
    storage_state_path = Path(config.get("storage_state", STORAGE_STATE_FILE))
    if not storage_state_path.exists():
        print(f"错误: 登录状态文件不存在 ({storage_state_path})")
        print("请先运行: python dataDownload.py --save-state-only")
        return

    _timings.clear()
    async with async_playwright() as p:
        browser = None
        context = None
        try:
            # 1. 启动无头浏览器
            print("正在启动浏览器（无头模式）...")
            browser = await p.chromium.launch(
                channel="msedge",
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            _log_step("浏览器启动")

            # 2. 加载已保存的登录状态
            with open(storage_state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            context = await browser.new_context(storage_state=state)
            page = await context.new_page()

            # 3. 打开用量页面（domcontentloaded 比 networkidle 快得多）
            print(f"正在打开页面: {USAGE_URL}")
            await page.goto(USAGE_URL, wait_until="domcontentloaded", timeout=NAV_LOAD_TIMEOUT)
            _log_step("页面加载")

            # 4. 检查是否被重定向到登录页
            if "/login" in page.url.lower():
                print("登录状态已失效，请重新运行 --save-state-only")
                return

            # 5. 等待渲染完成且导出按钮可点（替代固定 3s 等待）
            await page.wait_for_load_state("networkidle", timeout=ELEMENT_TIMEOUT)
            btn = await _wait_for_export_button(page, timeout=10000)
            if btn is None:
                await page.screenshot(path="debug_export.png")
                raise RuntimeError(
                    f"找不到导出按钮，已保存截图 debug_export.png\n"
                    f"请尝试运行 --discover-endpoint 排查页面结构"
                )
            _log_step("页面渲染")

            # 6. 点击并下载
            print(f"正在点击「{EXPORT_BUTTON_TEXT}」按钮...")
            async with page.expect_download(timeout=timeout) as dl_info:
                await btn.click()

            download = await dl_info.value
            _log_step("下载完成")

            # 7. 保存文件
            suggested = download.suggested_filename
            if not suggested:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                suggested = f"deepseek_usage_{timestamp}.csv"

            save_path = output_dir / suggested

            output_dir.mkdir(parents=True, exist_ok=True)
            await download.save_as(str(save_path))
            print(f"下载成功: {save_path}")
            _log_step("文件保存")

        except PlaywrightTimeout as e:
            print(f"错误: 操作超时 - {e}")
        except Exception as e:
            print(f"错误: {e}")
            raise
        finally:
            if context:
                await context.close()
            if browser:
                await browser.close()


# ============================================================
# CLI 入口
# ============================================================

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="下载 DeepSeek API 用量数据")

    # 操作模式
    parser.add_argument(
        "--save-state-only", action="store_true",
        help="启动浏览器登录并保存 cookies（一次性设置）",
    )
    parser.add_argument(
        "--discover-endpoint", action="store_true",
        help="有界面模式下发现导出 API 地址（调试用）",
    )

    # 导出参数
    parser.add_argument(
        "--output-dir", "-o", default=None,
        help="文件保存目录（覆盖 config.json）",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="下载等待超时秒数（默认 60）",
    )

    return parser


def main():
    args = create_parser().parse_args()

    config_path = Path(CONFIG_FILE)
    config = _load_config(config_path)

    # --- 保存登录状态 ---
    if args.save_state_only:
        storage = Path(config.get("storage_state", STORAGE_STATE_FILE))
        asyncio.run(_do_save_state(storage))
        return

    # --- 发现 API 地址 ---
    if args.discover_endpoint:
        asyncio.run(_do_discover_endpoint(config, config_path))
        return

    # --- 默认导出 ---
    output_dir = Path(args.output_dir or config.get("output_dir", "."))
    timeout = (args.timeout or config.get("download_timeout", DOWNLOAD_TIMEOUT))
    asyncio.run(_do_export(config, output_dir, timeout))
    _print_total_time()


if __name__ == "__main__":
    main()
