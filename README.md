<<<<<<< HEAD
# dsapi_visual_desktop
dsapi_visual
=======
# DeepSeek API 用量数据下载器

自动从 DeepSeek 用量页面（`https://platform.deepseek.com/usage`）导出用量数据并保存到本地。

## 功能

- 一键导出 DeepSeek API 的用量数据（调用次数、Token 消耗等）
- 支持自定义输出目录
- 仅需一次登录，后续导出无需重复登录
- 导出过程无浏览器窗口弹出

## 工作原理

```
┌─────────────────────────────────────────────────────┐
│                  首次设置（仅一次）                    │
│  python dataDownload.py --save-state-only           │
│  ┌──────────┐    ┌───────────┐    ┌──────────────┐ │
│  │ Edge 打开 │ -> │ 用户登录  │ -> │ 保存 cookies  │ │
│  │ (有界面)  │    │ DeepSeek  │    │ 到 JSON 文件  │ │
│  └──────────┘    └───────────┘    └──────────────┘ │
└─────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                  日常导出（无窗口）                    │
│  python dataDownload.py                             │
│  ┌──────────────┐    ┌───────────┐    ┌────────────┐│
│  │ Playwright   │ -> │ 打开用量  │ -> │ 点击导出   ││
│  │ 无头浏览器   │    │ 页面      │    │ 下载文件   ││
│  │ (无窗口)     │    │           │    │            ││
│  └──────────────┘    └───────────┘    └────────────┘│
└─────────────────────────────────────────────────────┘
```

脚本使用 **Playwright** 控制浏览器完成操作：

1. **首次设置**：启动有界面的 Edge 浏览器，你在页面中手动登录 DeepSeek。登录成功后，脚本将登录态（cookies）保存到 `deepseek_storage_state.json`。
2. **日常导出**：使用 Playwright 的无头模式（headless，即没有可见窗口的浏览器）加载保存的 cookies，自动打开用量页面，定位"导出"按钮并点击，将下载的文件保存到本地。

> 为什么不直接调用 API？DeepSeek 平台有 WAF 防护，Python 的 `requests` 库会被拦截。使用 Playwright 的真实浏览器引擎可以正常通过。

## 使用命令

### 查看帮助

```bash
python dataDownload.py --help
```

### 首次设置（登录并保存会话）

```bash
python dataDownload.py --save-state-only
```

浏览器窗口会打开，手动登录 DeepSeek。登录成功后 cookies 自动保存，后续导出无需再次登录。

### 日常导出

```bash
python dataDownload.py
```

Playwright 以无头模式启动，自动完成导出，全程无可见窗口。

### 指定输出目录

```bash
python dataDownload.py --output-dir ./exports
```

或修改 `config.json` 中的 `output_dir` 字段永久生效。

### 调整下载超时

```bash
python dataDownload.py --timeout 120
```

默认 60 秒，对于数据量大的导出可适当增加。

### 调试：发现导出按钮的 API 地址

```bash
python dataDownload.py --discover-endpoint
```

以有界面模式打开页面，点击导出并捕获网络请求。用于排查页面结构变化或按钮定位问题。

## 配置文件

`config.json` 在项目根目录，可手动修改：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `output_dir` | `"."` | 文件保存目录 |
| `storage_state` | `"deepseek_storage_state.json"` | 登录状态文件路径 |
| `download_timeout` | `60000` | 下载超时（毫秒） |

## 在其他电脑上首次使用

### 1. 安装依赖

```bash
# 创建并激活 conda 虚拟环境（可选）
conda create -n flicker python=3.12
conda activate flicker

# 安装 Playwright
pip install playwright
```

### 2. 下载脚本文件

将以下文件复制到目标电脑的同一目录下：

- `dataDownload.py` — 主脚本
- `config.json` — 配置文件（可选，脚本会自动生成默认配置）

### 3. 首次登录设置

```bash
python dataDownload.py --save-state-only
```

浏览器窗口会打开，登录你的 DeepSeek 账号。登录后 cookies 保存到本地，窗口自动关闭。

### 4. 开始使用

```bash
python dataDownload.py
```

每次运行都会自动导出最新的用量数据，保存到当前目录。

### 5. （可选）修改输出目录

编辑 `config.json`，修改 `output_dir` 字段：

```json
{
    "output_dir": "D:/我的数据/deepseek用量"
}
```

## 常见问题

**Q: `--save-state-only` 打开浏览器后没有任何反应？**

可能是因为 Edge 浏览器正在运行导致配置目录冲突。请先关闭所有 Edge 窗口再重试。

**Q: 导出时提示"找不到导出按钮"**

DeepSeek 的前端页面可能已更新。尝试运行 `--discover-endpoint` 排查，或检查页面是否正常加载。

**Q: 下载的文件名是什么？**

由服务器端决定，通常是带有时间信息的 CSV 文件。同名文件会自动添加数字后缀避免覆盖。

**Q: 登录状态多久失效？**

取决于 DeepSeek 的会话策略，通常为数周。失效后重新运行 `--save-state-only` 即可。
>>>>>>> 828950b (初始化提交：DeepSeek API 使用数据桌面磁贴看板)
