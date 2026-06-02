#!/usr/bin/env python3
"""
DeepSeek API Usage Data Downloader (Optimized)

直接调用 platform 内部 API，无需 Playwright 浏览器。

一次性设置（需浏览器界面）：
    python dataDownload.py --save-state-only     # 登录并保存 cookies+token

日常导出（瞬间完成）：
    python dataDownload.py                       # 读取 token，直接下载
    python dataDownload.py -m 5 -y 2026          # 下载指定月份
    python dataDownload.py -m 5 -y 2026 --api    # 也下载当月 API 模式用量

发现 API 地址（已内置，无需调试）：
    无头模式下自动拦截 token，无需 --discover-endpoint
"""

import argparse
import csv
import io
import json
import time
import zipfile
from datetime import datetime
from pathlib import Path

import requests

# --- 耗时统计 ---
_timings = []


def _log_step(name):
    now = time.perf_counter()
    if _timings:
        elapsed = now - _timings[-1][1]
        print(f"  [{name}] {elapsed:.1f}s")
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
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = str(SCRIPT_DIR / "config.json")
STORAGE_STATE_FILE = str(SCRIPT_DIR / "deepseek_storage_state.json")
PLATFORM_BASE = "https://platform.deepseek.com"
TIMEOUT = 15


# ============================================================
# 配置管理
# ============================================================

def _load_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # 相对路径 → 基于脚本目录
    for key in ("storage_state", "output_dir"):
        val = cfg.get(key)
        if val and not Path(val).is_absolute():
            cfg[key] = str(SCRIPT_DIR / val)
    return cfg


def _save_config(config: dict, config_path: Path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
    print(f"配置已保存: {config_path}")


# ============================================================
# Token 提取
# ============================================================

def _get_bearer_token(storage_state_path: Path) -> str | None:
    """从 Playwright storage state 的 localStorage 提取 userToken"""
    if not storage_state_path.exists():
        return None
    state = json.loads(storage_state_path.read_text("utf-8"))
    for o in state.get("origins", []):
        if "platform.deepseek.com" in o.get("origin", ""):
            for ls in o.get("localStorage", []):
                if ls["name"] == "userToken":
                    val = json.loads(ls["value"])
                    return val["value"]
    return None


def _extract_cookies(storage_state_path: Path) -> dict:
    """从 Playwright storage state 提取 cookies"""
    if not storage_state_path.exists():
        return {}
    state = json.loads(storage_state_path.read_text("utf-8"))
    cookies = {}
    for c in state.get("cookies", []):
        if "deepseek.com" in c.get("domain", ""):
            cookies[c["name"]] = c["value"]
    return cookies


# ============================================================
# API 调用
# ============================================================

def _api_get(path: str, token: str) -> dict:
    """调用 platform.deepseek.com 内部 API"""
    url = PLATFORM_BASE + path
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "Mozilla/5.0",
            "X-App-Version": "1.0.0",
            "Accept": "*/*",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"API error: {data.get('msg', 'unknown')} (code={data.get('code')})")
    return data["data"]["biz_data"]


# ============================================================
# 数据转换：JSON → CSV
# ============================================================

FLAT_TYPE_MAP = {
    "REQUEST": "request_count",
    "PROMPT_TOKEN": "input_cache_miss_tokens",     # prompt 无缓存时也算 miss
    "PROMPT_CACHE_HIT_TOKEN": "input_cache_hit_tokens",
    "PROMPT_CACHE_MISS_TOKEN": "input_cache_miss_tokens",
    "RESPONSE_TOKEN": "output_tokens",
}



def _amount_json_to_csv_rows(biz_data: dict) -> list[tuple]:
    """amount API 的 JSON → CSV rows for data_Process.py"""
    SKIP_TYPES = {"PROMPT_TOKEN"}  # 总为 0（已被 hit/miss 拆分替代）
    SKIP_MODELS = {"deepseek-chat & deepseek-reasoner"}  # 已下架模型
    rows = []
    for day in biz_data.get("days", []):
        date = day["date"]
        for entry in day["data"]:
            model = entry["model"]
            if model in SKIP_MODELS:
                continue
            for usage in entry.get("usage", []):
                utype = usage["type"]
                if utype in SKIP_TYPES:
                    continue
                amount = usage["amount"]
                flat_type = FLAT_TYPE_MAP.get(utype, utype)
                rows.append((model, date, flat_type, amount, "default"))
    return rows


def _cost_json_to_csv_rows(biz_data: list | dict) -> list[tuple]:
    """cost API 的 JSON → CSV rows"""
    # cost 接口的 biz_data 是列表（包含一个元素），amount 是直接 dict
    if isinstance(biz_data, list):
        biz_data = biz_data[0] if biz_data else {}
    SKIP_TYPES = {"PROMPT_TOKEN"}
    SKIP_MODELS = {"deepseek-chat & deepseek-reasoner"}
    rows = []
    for day in biz_data.get("days", []):
        date = day["date"]
        for entry in day["data"]:
            model = entry["model"]
            if model in SKIP_MODELS:
                continue
            for usage in entry.get("usage", []):
                utype = usage["type"]
                if utype in SKIP_TYPES:
                    continue
                cost = usage["amount"]
                flat_type = FLAT_TYPE_MAP.get(utype, utype)
                rows.append((model, date, flat_type, cost))
    return rows


def _write_csv_to_zip(zf: zipfile.ZipFile, filename: str, rows: list[tuple], headers: list[str]):
    """将行数据写入 ZIP 内的 CSV 文件"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    zf.writestr(filename, buf.getvalue().encode("utf-8"))


# ============================================================
# 设置模式：保存登录状态（有界面）
# ============================================================

async def _do_save_state(storage_state_path: Path):
    """启动浏览器 → 登录 → 保存 cookies+localStorage（有界面，仅一次）"""
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

    USAGE_URL = "https://platform.deepseek.com/usage"
    NAV_LOAD_TIMEOUT = 30_000
    ELEMENT_TIMEOUT = 20_000
    LOGIN_WAIT_TIMEOUT = 180_000

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

        await page.wait_for_load_state("networkidle", timeout=ELEMENT_TIMEOUT)
        await page.wait_for_timeout(2000)

        await context.storage_state(path=str(storage_state_path))
        print(f"登录状态已保存: {storage_state_path}")

        await context.close()
        await browser.close()


# ============================================================
# 默认模式：直接 HTTP 下载（无浏览器）
# ============================================================

def _download_month(
    token: str,
    year: int,
    month: int,
    output_dir: Path,
) -> tuple[list[tuple], list[tuple]]:
    """下载指定月份的数据，返回 (amount_rows, cost_rows)"""
    path_amount = f"/api/v0/usage/amount?month={month}&year={year}"
    path_cost = f"/api/v0/usage/cost?month={month}&year={year}"

    print(f"正在获取 {year}年{month}月 用量数据...")
    amount_data = _api_get(path_amount, token)
    print(f"  用量数据: {len(amount_data.get('days', []))} 天")
    _log_step("用量数据")

    print(f"正在获取 {year}年{month}月 费用数据...")
    cost_data = _api_get(path_cost, token)
    cost_days = cost_data[0].get('days', []) if isinstance(cost_data, list) else cost_data.get('days', [])
    print(f"  费用数据: {len(cost_days)} 天")
    _log_step("费用数据")

    # 转 CSV
    amount_rows = _amount_json_to_csv_rows(amount_data)
    cost_rows = _cost_json_to_csv_rows(cost_data)
    return amount_rows, cost_rows


def _do_export(config: dict, output_dir: Path, year: int, month: int):
    """直接 HTTP 下载并保存为 ZIP"""
    storage_state_path = Path(config.get("storage_state", STORAGE_STATE_FILE))
    if not storage_state_path.exists():
        print(f"错误: 登录状态文件不存在 ({storage_state_path})")
        print("请先运行: python dataDownload.py --save-state-only")
        return

    _timings.clear()
    _log_step("开始")

    # 1. 提取 Token
    token = _get_bearer_token(storage_state_path)
    if not token:
        print("错误: 未找到 userToken，请重新运行 --save-state-only")
        return
    print(f"Token 已加载 ({len(token)} 字符)")
    _log_step("Token 提取")

    # 2. 下载数据
    try:
        amount_rows, cost_rows = _download_month(token, year, month, output_dir)
    except requests.HTTPError as e:
        resp = e.response
        if resp.status_code == 401:
            print("错误: Token 已过期，请重新运行 --save-state-only")
        else:
            print(f"错误: HTTP {resp.status_code}")
        return

    # 3. 写入 ZIP
    zip_name = f"usage_data_{year}_{month}.zip"
    save_path = output_dir / zip_name
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 注意写入顺序：data_Process.read_csv_from_zip 按 CSV 在 ZIP 里的顺序读取
        # 第 1 个 CSV → cost，第 2 个 → amount
        _write_csv_to_zip(
            zf, "cost.csv", cost_rows,
            ["model", "utc_date", "type", "cost"],
        )
        _write_csv_to_zip(
            zf, "amount.csv", amount_rows,
            ["model", "utc_date", "type", "amount", "api_key_name"],
        )

    print(f"下载成功: {save_path}")
    print(f"  amount.csv: {len(amount_rows)} 行")
    print(f"  cost.csv:   {len(cost_rows)} 行")
    _log_step("文件保存")


# ============================================================
# CLI 入口
# ============================================================

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="下载 DeepSeek API 用量数据")

    # 操作模式
    parser.add_argument(
        "--save-state-only", action="store_true",
        help="启动浏览器登录并保存 cookies/token（一次性设置）",
    )

    # 月份参数
    parser.add_argument(
        "-m", "--month", type=int, default=None,
        help="月份 (1-12，默认当前月份)",
    )
    parser.add_argument(
        "-y", "--year", type=int, default=None,
        help="年份 (默认当前年份)",
    )

    # 输出
    parser.add_argument(
        "--output-dir", "-o", default=None,
        help="文件保存目录（覆盖 config.json）",
    )

    return parser


def main():
    args = create_parser().parse_args()

    config_path = Path(CONFIG_FILE)
    config = _load_config(config_path)

    # --- 保存登录状态 ---
    if args.save_state_only:
        storage = Path(config.get("storage_state", STORAGE_STATE_FILE))
        import asyncio
        asyncio.run(_do_save_state(storage))
        return

    # --- 默认导出 ---
    now = datetime.now()
    year = args.year or now.year
    month = args.month or now.month
    output_dir = Path(args.output_dir or config.get("output_dir", "."))

    _do_export(config, output_dir, year, month)
    _print_total_time()


if __name__ == "__main__":
    main()
