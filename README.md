# DeepSeek API 用量数据下载器 & 桌面看板

自动从 DeepSeek 平台获取 API 用量数据（Token 消耗、费用），并用桌面磁贴看板可视化展示。

## 环境要求与安装

### 必需的 Python 包

```bash
pip install pandas matplotlib requests tabulate
```

### 创建虚拟环境（推荐）

```bash
conda create -n dsapi python=3.12
conda activate dsapi
pip install pandas matplotlib requests tabulate
```

Playwright 仅在首次登录时需要（`--save-state-only`），日常下载不依赖浏览器。

## 功能

- 一键导出 DeepSeek API 用量数据（调用次数、Token 消耗、费用）
- 支持指定月份导出历史数据
- 仅需一次登录，后续导出无需重复登录
- 导出过程无需浏览器，1-3 秒完成
- 桌面磁贴看板：5 张图表（请求趋势、Token 消耗、成本分布、Token 排名、缓存命中率）
- 暗色/白色主题切换、自动刷新

## 工作原理

### 数据下载

```text
┌──────────────────────────────────────────────────────────┐
│                  首次设置（仅一次）                         │
│  python dataDownload.py --save-state-only                │
│  ┌──────────┐    ┌───────────┐    ┌──────────────────┐  │
│  │ Edge 打开 │ -> │ 用户登录  │ -> │ 保存 cookies +   │  │
│  │ (有界面)  │    │ DeepSeek  │    │ localStorage     │  │
│  └──────────┘    └───────────┘    │ (含 userToken)    │  │
│                                   └──────────────────┘  │
└──────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                  日常导出（无浏览器，~1s）                   │
│  python dataDownload.py                                  │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────┐  │
│  │ 从 storage  │ -> │ 直接 HTTP 调用   │ -> │ 保存为  │  │
│  │ state 提取  │    │ platform 内部 API │    │ ZIP 文件 │  │
│  │ userToken   │    │ (无需 Playwright) │    │         │  │
│  └─────────────┘    └──────────────────┘    └─────────┘  │
└──────────────────────────────────────────────────────────┘
```

脚本直接调用 DeepSeek platform 的内部 REST API（通过 Playwright
storage state 中保存的 `userToken` 认证），无需启动浏览器。

调用接口：

| 端点 | 说明 |
|---|---|
| `/api/v0/usage/amount?month={m}&year={y}` | Token 用量（日粒度，分 model/type） |
| `/api/v0/usage/cost?month={m}&year={y}` | 费用（日粒度） |
| `/api/v0/users/get_user_summary` | 账户汇总（余额、月度用量） |

### 桌面看板

```text
ZIP (usage_data_{year}_{month}.zip)
  → pandas 读取 CSV
    → data_Process.py 中 groupby 聚合
      → draw.py 中 matplotlib 嵌入 5 张图表（2×3 网格）
```

## 使用命令

### 下载数据

```bash
# 下载当前月份数据（日常使用）
python dataDownload.py

# 下载指定月份
python dataDownload.py -m 5 -y 2026

# 指定输出目录
python dataDownload.py -o ./exports
```

### 首次设置（登录保存会话）

```bash
python dataDownload.py --save-state-only
```

浏览器窗口打开，手动登录 DeepSeek。登录后 cookies 和 userToken 自动保存。
日常下载无需再次登录。

### 启动看板

```bash
python draw.py
```

## 配置文件

`config.json` 在项目目录下，可手动修改：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `output_dir` | `"."` | 文件保存目录 |
| `storage_state` | `"deepseek_storage_state.json"` | 登录状态文件路径 |
| `download_timeout` | `60000` | 下载超时（毫秒，旧 Playwright 模式用） |
| `api_key` | — | DeepSeek API Key（用于看板余额显示） |

## 项目结构

```
dsapi_visual_desktop/
├── draw.py              # 主看板（5 张图表、主题切换、自动刷新）
├── data_Process.py      # 数据处理（pandas 聚合）
├── dataDownload.py      # 数据下载（直接 HTTP 调内部 API）
├── main.py              # 启动入口
├── config.json          # API Key 等配置
└── usage_data_*.zip     # 每月用量压缩包
```

## 常见问题

**Q: Token 过期了怎么办？**

重新运行 `python dataDownload.py --save-state-only` 登录一次即可。

**Q: 首次设置时浏览器打开后没反应？**

关闭所有 Edge 窗口再重试。

**Q: 下载的数据文件在哪？**

默认为当前目录下的 `usage_data_{year}_{month}.zip`，包含 `cost.csv` 和 `amount.csv`。

**Q: 在其他电脑上使用需要复制哪些文件？**

- `dataDownload.py`
- `config.json`（可选）
- 然后运行 `python dataDownload.py --save-state-only` 登录
