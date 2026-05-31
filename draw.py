"""
DeepSeek API 使用数据 — 桌面磁贴看板
======================================
功能：从 data_Process.py 读取处理好的费用（cost）和 Token 用量（amount）数据，
      以 2×2 网格展示在悬浮桌面上的磁贴窗口中，支持暗色/白色主题切换。
"""

# ── 标准库 ──────────────────────────────────────────────
import re          # 正则表达式，用于解析窗口 geometry 字符串
import threading   # 后台线程执行网络下载，不阻塞 UI
from datetime import datetime  # 状态栏显示当前刷新时间
import tkinter as tk
from tkinter import Menu

# ── 第三方库 ────────────────────────────────────────────
import matplotlib
matplotlib.use('TkAgg')  # 指定 matplotlib 后端为 tkinter
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ── 本地模块 ────────────────────────────────────────────
# dataDownload 需要 playwright，未安装时跳过下载功能，不影响本地数据展示
try:
    import dataDownload
    _HAS_DOWNLOAD = True
except ImportError:
    _HAS_DOWNLOAD = False

# 复用 data_Process.py 中的数据处理函数xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
from data_Process import (
    read_csv_from_zip, read_zip_name,
    data_samedate_cost, data_samemodel_cost,
    data_samedatemodel_tokeninfo, date_samemodelname_tokeninfo,
)

# ── 全局配置 ────────────────────────────────────────────
plt.style.use('dark_background')                                    # matplotlib 默认样式
# 中文字体支持：将中文字体添加到 sans-serif 列表最前面（放在 DejaVu Sans 之前）
# 注意：后续 _apply_theme() 中调用 plt.style.use() 会重置该列表，需要重新设置
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei'] \
                                   + plt.rcParams.get('font.sans-serif', [])
plt.rcParams['axes.unicode_minus'] = False                          # 解决负号显示问题
COLORS = ['#4ECDC4', '#FF6B6B', '#FFE66D', '#95E1D3', '#F38181', '#AA96DA']
REFRESH_MS = 60_000   # 自动刷新间隔（毫秒）
RESIZE_MARGIN = 8      # 窗口边缘缩放感应宽度（像素）

# ── 配色方案 ────────────────────────────────────────────
# dark  = 暗色主题（默认），适合弱光环境
# light = 白色主题，适合明亮环境或截图分享
_THEMES = {
    'dark': {
        'bg': '#1a1a2e', 'panel': '#16213e', 'fg': '#e0e0e0',
        'border': '#16213e', 'status_fg': '#777',
        'menu_bg': '#16213e', 'menu_fg': '#c0c0c0',
        'menu_active_bg': '#0f3460', 'menu_active_fg': '#fff',
        'mpl_style': 'dark_background',
        'fig_face': '#1a1a2e', 'ax_face': '#16213e',
        'title_fg': '#e0e0e0', 'tick_color': '#999',
        'label_color': '#999', 'legend_color': '#ddd',
    },
    'light': {
        'bg': '#f5f5f5', 'panel': '#ffffff', 'fg': '#333333',
        'border': '#d0d0d0', 'status_fg': '#888',
        'menu_bg': '#ffffff', 'menu_fg': '#333333',
        'menu_active_bg': '#e0e0e0', 'menu_active_fg': '#000',
        'mpl_style': 'default',
        'fig_face': '#f5f5f5', 'ax_face': '#ffffff',
        'title_fg': '#333333', 'tick_color': '#666',
        'label_color': '#666', 'legend_color': '#333',
    },
}


class UsageWidget:
    """桌面磁贴看板主程序：管理窗口、事件、数据加载和图表渲染"""

    def __init__(self):
        # ── 创建根窗口 ──
        self.root = tk.Tk()
        self.root.title("DeepSeek API 使用情况看板")

        # ── 窗口样式：无边框 + 置顶 ──
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg='#1a1a2e')
        self._x, self._y = 0, 0
        self._fullscreen = False
        self._refreshing = False     # 防止重复刷新

        # ── 主题配色 ──
        self._theme = 'dark'         # 当前主题名：'dark' | 'light'
        self._C = _THEMES['dark']    # 当前主题的配色字典，_embed_* 方法从中读取颜色

        # ── 窗口尺寸与初始位置（屏幕右上角） ──
        self.w_w, self.w_h = 720, 600
        sw = self.root.winfo_screenwidth()
        x = sw - self.w_w - 20
        self.root.geometry(f"{self.w_w}x{self.w_h}+{x}+60")

        # ── 数据缓存 ──
        self.cost_df = None    # 费用 DataFrame
        self.amount_df = None  # Token 用量 DataFrame

        # ── 构建界面组件 ──
        self._build_titlebar()
        self._build_chart_grid()
        self._build_statusbar()
        self._bind_events()
        self._build_menu()

        # ── 首次加载数据（不触发网络下载，由 main.py 在启动前已下载好） ──
        self._load_local()
        self.root.after(REFRESH_MS, self._auto_refresh)

    # ══════════════════════════════════════════════════════
    #  界面构建
    # ══════════════════════════════════════════════════════

    # ── 标题栏：显示应用名称 + 关闭按钮 ──
    def _build_titlebar(self):
        bar = tk.Frame(self.root, bg=self._C['panel'], height=34)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)

        lbl = tk.Label(bar, text="DeepSeek API 使用情况看板",
                       bg=self._C['panel'], fg=self._C['fg'],
                       font=('Microsoft YaHei', 10))
        lbl.pack(side=tk.LEFT, padx=12)

        btn = tk.Label(bar, text='✕', bg=self._C['panel'], fg='#ff6b6b',
                       font=('Arial', 13, 'bold'), cursor='hand2')
        btn.pack(side=tk.RIGHT, padx=10)
        btn.bind('<Button-1>', lambda e: self.root.destroy())
        # 保存引用，主题切换时更新颜色
        self._title_bar = (bar, lbl, btn)

    # ── 图表容器：2 行 × 2 列网格 ──
    def _build_chart_grid(self):
        self.main = tk.Frame(self.root, bg=self._C['bg'])
        self.main.pack(fill=tk.BOTH, expand=True, padx=6, pady=(4, 2))

        # 四个子帧分别存放折线图、柱状图、饼图、Token 柱状图
        names = ['line', 'bar', 'pie', 'token']
        self.frames = {}
        for i, name in enumerate(names):
            r, c = divmod(i, 2)
            f = tk.Frame(self.main, bg=self._C['bg'],
                         highlightbackground=self._C['border'],
                         highlightthickness=1)
            f.grid(row=r, column=c, padx=3, pady=3, sticky='nsew')
            self.frames[name] = f

        # 网格权重：四个区域等比例扩展
        self.main.grid_rowconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_columnconfigure(1, weight=1)

    # ── 底部状态栏：显示数据状态、错误信息等 ──
    def _build_statusbar(self):
        self.status = tk.Label(self.root, text='就绪',
                               bg=self._C['panel'], fg=self._C['status_fg'],
                               font=('Microsoft YaHei', 8), anchor=tk.W)
        self.status.pack(fill=tk.X, side=tk.BOTTOM, padx=8, pady=(0, 4))

    # ══════════════════════════════════════════════════════
    #  鼠标事件：拖动 + 边缘缩放 + 双击全屏
    # ══════════════════════════════════════════════════════

    def _bind_events(self):
        # <Motion> 实时检测鼠标位置，在边缘时切换缩放光标
        self.root.bind('<Motion>', self._on_motion)
        # <Button-1> 区分"在边缘 → 缩放"和"不在边缘 → 拖动"
        self.root.bind('<Button-1>', self._on_click)
        self.root.bind('<B1-Motion>', self._on_drag)
        self.root.bind('<Double-Button-1>', lambda e: self._toggle_fullscreen())

    def _detect_edge(self, e):
        """检测鼠标是否在窗口边缘 8px 范围内，返回方向或 None"""
        x, y = e.x, e.y
        on_left = x <= RESIZE_MARGIN
        on_right = x >= self.w_w - RESIZE_MARGIN
        on_top = y <= RESIZE_MARGIN
        on_bottom = y >= self.w_h - RESIZE_MARGIN

        # 四角优先判断，然后是四边
        if on_left and on_top:     return 'nw'
        if on_right and on_top:    return 'ne'
        if on_left and on_bottom:  return 'sw'
        if on_right and on_bottom: return 'se'
        if on_left:                return 'w'
        if on_right:               return 'e'
        if on_top:                 return 'n'
        if on_bottom:              return 's'
        return None

    # 边缘方向 → tkinter 光标名映射
    _CURSOR_MAP = {
        'nw': 'size_nw_se', 'ne': 'size_ne_sw',
        'sw': 'size_ne_sw', 'se': 'size_nw_se',
        'w': 'size_we',     'e': 'size_we',
        'n': 'size_ns',     's': 'size_ns',
    }

    def _on_motion(self, e):
        """鼠标移动：在边缘时切换缩放光标"""
        edge = self._detect_edge(e)
        if edge:
            self.root.config(cursor=self._CURSOR_MAP[edge])
        else:
            self.root.config(cursor='')
        self._edge = edge   # 供 _on_click 判断是否进入缩放模式

    def _on_click(self, e):
        """鼠标按下：边缘 → 缩放模式，非边缘 → 拖动模式"""
        self._drag_start_xy = (e.x_root, e.y_root)
        if self._edge:
            self._mode = 'resize'
            self._resize_start = (e.x_root, e.y_root)
            self._resize_geo = (self.w_w, self.w_h,
                                self.root.winfo_x(), self.root.winfo_y())
        else:
            self._mode = 'move'
            self._drag_off = (e.x, e.y)   # 鼠标相对于窗口的偏移量

    def _on_drag(self, e):
        """拖拽中：按当前模式执行缩放或移动"""
        if self._mode == 'resize':
            self._do_resize(e)
        elif self._mode == 'move':
            self._do_move(e)

    def _do_move(self, e):
        """移动窗口：根据鼠标偏移量计算新位置"""
        x = self.root.winfo_x() + e.x - self._drag_off[0]
        y = self.root.winfo_y() + e.y - self._drag_off[1]
        self.root.geometry(f'+{x}+{y}')

    def _do_resize(self, e):
        """缩放窗口：根据边缘方向和鼠标偏移计算新尺寸和位置"""
        dx = e.x_root - self._resize_start[0]
        dy = e.y_root - self._resize_start[1]
        ow, oh, ox, oy = self._resize_geo  # 缩放开始时的窗口数据

        nx, ny, nw, nh = ox, oy, ow, oh
        edge = self._edge

        # 根据方向分别调整左右边距和宽高
        if 'w' in edge:
            nx = ox + dx
            nw = ow - dx
        if 'e' in edge:
            nw = ow + dx
        if 'n' in edge:
            ny = oy + dy
            nh = oh - dy
        if 's' in edge:
            nh = oh + dy

        # 最小尺寸约束（防止缩放到看不见）
        if nw < 400:
            if 'w' in edge:
                nx = ox + (ow - 400)
            nw = 400
        if nh < 300:
            if 'n' in edge:
                ny = oy + (oh - 300)
            nh = 300

        self.root.geometry(f'{nw}x{nh}+{nx}+{ny}')
        self.w_w, self.w_h = nw, nh  # 更新缓存尺寸，供边缘检测使用

    # ── 双击全屏切换 ──
    def _toggle_fullscreen(self):
        if not self._fullscreen:
            # 保存当前窗口位置尺寸，然后铺满屏幕
            self._saved_geo = self.root.geometry()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f'{sw}x{sh}+0+0')
            self.w_w, self.w_h = sw, sh
        else:
            # 恢复保存的窗口位置尺寸
            self.root.geometry(self._saved_geo)
            m = re.match(r'(\d+)x(\d+)', self._saved_geo)
            if m:
                self.w_w, self.w_h = int(m.group(1)), int(m.group(2))
        self._fullscreen = not self._fullscreen

    # ── 右键菜单 ──
    def _build_menu(self):
        self.menu = Menu(self.root, tearoff=0,
                         bg=self._C['menu_bg'], fg=self._C['menu_fg'],
                         activebackground=self._C['menu_active_bg'],
                         activeforeground=self._C['menu_active_fg'])
        self.menu.add_command(label='🔄 刷新数据', command=self.refresh)
        self.menu.add_separator()
        self.menu.add_command(label='🔘 切换透明度', command=self._toggle_alpha)
        self.menu.add_separator()
        # 菜单文字随当前主题动态变化
        theme_label = '🎨 切换白色背景' if self._theme == 'dark' else '🎨 切换暗色背景'
        self.menu.add_command(label=theme_label, command=self._toggle_theme)
        self.menu.add_separator()
        self.menu.add_command(label='✕ 退出', command=self.root.destroy)
        self.root.bind('<Button-3>', lambda e: self.menu.post(e.x_root, e.y_root))

    # ── 透明度切换（点击切换 100% ↔ 35%） ──
    def _toggle_alpha(self):
        a = self.root.attributes('-alpha')
        self.root.attributes('-alpha', 0.35 if a > 0.5 else 1.0)

    # ══════════════════════════════════════════════════════
    #  主题切换
    # ══════════════════════════════════════════════════════

    def _toggle_theme(self):
        """在暗色/白色主题之间切换"""
        self._theme = 'light' if self._theme == 'dark' else 'dark'
        self._C = _THEMES[self._theme]
        self._apply_theme()
        if self.cost_df is not None:
            self._render()  # 重绘图表让新颜色生效

    def _apply_theme(self):
        """将当前主题色应用到所有 tkinter 控件和 matplotlib 样式"""
        C = self._C
        self.root.configure(bg=C['bg'])                     # 窗口背景
        bar, lbl, btn = self._title_bar
        bar.configure(bg=C['panel'])                        # 标题栏
        lbl.configure(bg=C['panel'], fg=C['fg'])
        btn.configure(bg=C['panel'])
        self.main.configure(bg=C['bg'])                     # 图表容器
        for f in self.frames.values():
            f.configure(bg=C['bg'], highlightbackground=C['border'])
        self.status.configure(bg=C['panel'], fg=C['status_fg'])  # 状态栏
        self._build_menu()                                  # 重建菜单（颜色变化）
        plt.style.use(C['mpl_style'])                       # matplotlib 样式
        # 样式切换会重置 font.sans-serif，重新设置中文字体（放在列表最前面）
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei'] \
                                           + plt.rcParams.get('font.sans-serif', [])
        plt.rcParams['axes.unicode_minus'] = False

    # ══════════════════════════════════════════════════════
    #  数据加载与刷新
    # ══════════════════════════════════════════════════════

    def _load_local(self):
        """从本地 zip 读取数据（不触发网络下载）"""
        try:
            zp = read_zip_name()
            self.cost_df, self.amount_df = read_csv_from_zip(zp)
            self._render()
            date_min = self.cost_df['utc_date'].min()
            date_max = self.cost_df['utc_date'].max()
            self.status.config(text=f'本地数据  |  {date_min} ~ {date_max}  |  {datetime.now():%H:%M}')
        except Exception as exc:
            self.status.config(text=f'✗ 无本地数据: {exc}')

    def refresh(self):
        """全量刷新：后台下载 → 更新图表"""
        if self._refreshing:
            return                          # 防止重复触发
        self._refreshing = True

        # 没有 playwright 时直接加载本地数据
        if not _HAS_DOWNLOAD:
            self._load_local()
            self._refreshing = False
            return

        self.status.config(text='⏳ 正在下载最新数据…')
        self.root.update_idletasks()
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        """后台线程：执行网络下载和 CSV 读取（不阻塞 UI）"""
        try:
            dataDownload.main()                     # 下载最新 CSV
            zp = read_zip_name()
            cost_df, amount_df = read_csv_from_zip(zp)
            # 回到主线程更新 UI
            self.root.after(0, self._apply_data, cost_df, amount_df, None)
        except Exception as exc:
            self.root.after(0, self._fallback_local, str(exc))

    def _apply_data(self, cost_df, amount_df, _):
        """在主线程中应用新数据并重绘图表"""
        self.cost_df = cost_df
        self.amount_df = amount_df
        self._render()
        date_min = self.cost_df['utc_date'].min()
        date_max = self.cost_df['utc_date'].max()
        self.status.config(text=f'✓ 已更新  |  {date_min} ~ {date_max}  |  {datetime.now():%H:%M}')
        self._refreshing = False

    def _fallback_local(self, _):
        """下载失败时回退到本地已有数据"""
        self.status.config(text='✗ 下载失败，使用本地数据')
        try:
            zp = read_zip_name()
            self.cost_df, self.amount_df = read_csv_from_zip(zp)
            self._render()
        except Exception:
            pass
        self._refreshing = False

    def _auto_refresh(self):
        """定时器：每隔 REFRESH_MS 自动刷新一次"""
        self.refresh()
        self.root.after(REFRESH_MS, self._auto_refresh)

    # ── 清空子帧中的旧图表 ──
    @staticmethod
    def _clear_frame(fr):
        for w in fr.winfo_children():
            w.destroy()

    # ══════════════════════════════════════════════════════
    #  图表渲染
    # ══════════════════════════════════════════════════════

    def _render(self):
        """统一渲染入口：按顺序渲染 4 个图表"""
        cost, amount = self.cost_df, self.amount_df

        # 1 折线图 —— 每日费用趋势
        df_line = data_samedate_cost(cost)
        self._clear_frame(self.frames['line'])
        self._embed_line(self.frames['line'], df_line)

        # 2 分组堆叠柱状图 —— 每日 Token 消耗（按模型分组，按类型堆叠）
        df_bar = data_samedatemodel_tokeninfo(amount)
        self._clear_frame(self.frames['bar'])
        self._embed_grouped_bar(self.frames['bar'], df_bar)

        # 3 饼图 —— 总费用分布占比
        df_pie = data_samemodel_cost(cost)
        self._clear_frame(self.frames['pie'])
        self._embed_pie(self.frames['pie'], df_pie)

        # 4 水平柱状图 —— 各 API Key 的 Token 用量排名
        df_tok = date_samemodelname_tokeninfo(amount)
        token_only = df_tok[df_tok['type'] == 'total_token']
        self._clear_frame(self.frames['token'])
        self._embed_token_bar(self.frames['token'], token_only)

    # ── 各图表绘制方法 ──
    # 每个方法创建一个 matplotlib Figure，用 FigureCanvasTkAgg 嵌入 tkinter 帧

    def _embed_line(self, parent, df):
        """折线图：X 轴为日期，Y 轴为总费用"""
        C = self._C
        fig = Figure(figsize=(3.6, 2.4), dpi=100, facecolor=C['fig_face'])
        ax = fig.add_subplot(111, facecolor=C['ax_face'])
        ax.plot(df['utc_date'].astype(str), df['cost'], color='#4ECDC4',
                marker='o', linewidth=1.5, markersize=3)
        ax.set_title('每日消耗趋势', color=C['title_fg'], fontsize=9, pad=6)
        ax.tick_params(colors=C['tick_color'], labelsize=6)
        ax.set_ylabel('CNY', color=C['label_color'], fontsize=7)
        fig.autofmt_xdate(rotation=40)
        fig.tight_layout(pad=1.5)
        canvas = FigureCanvasTkAgg(fig, parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _embed_grouped_bar(self, parent, df):
        """
        分组堆叠柱状图：每日 Token 消耗
        X 轴 = 日期，每个日期按 model 分组并排放置两个柱，
        每个柱内从下到上堆叠：input_cache_hit → input_cache_miss → output_tokens
        """
        C = self._C
        fig = Figure(figsize=(3.6, 2.4), dpi=100, facecolor=C['fig_face'])
        ax = fig.add_subplot(111, facecolor=C['ax_face'])

        # 只取三种 Token 类型（排除 request_count / total_token）
        type_order = ['input_cache_hit_tokens', 'input_cache_miss_tokens', 'output_tokens']
        type_labels = ['Cache Hit', 'Cache Miss', 'Output']
        type_colors = ['#4ECDC4', '#FFE66D', '#FF6B6B']
        plot_df = df[df['type'].isin(type_order)]

        # 透视：行=日期，列=[model, type]，值=amount
        pivot = plot_df.pivot_table(index='utc_date', columns=['model', 'type'],
                                    values='amount', aggfunc='sum')

        dates = list(pivot.index)  # X 轴刻度
        models = sorted(plot_df['model'].unique())
        n_models = len(models)
        n_dates = len(dates)

        # 柱状图定位：每个日期下两个 model 柱并排，居中于日期 tick
        x_pos = list(range(n_dates))
        group_width = 0.7                     # 每个日期总宽度
        bar_width = group_width / n_models    # 每个 model 柱宽度

        for i, model in enumerate(models):
            # 该 model 柱在 X 轴上的中心位置
            pos = [xi - group_width / 2 + (i + 0.5) * bar_width for xi in x_pos]

            # 从下到上逐层堆叠
            bottoms = [0] * n_dates
            for tp, lbl, clr in zip(type_order, type_labels, type_colors):
                col_key = (model, tp)
                if col_key in pivot.columns:
                    vals = pivot[col_key].fillna(0).values
                    ax.bar(pos, vals, bar_width, label=lbl if i == 0 else '',
                           color=clr, bottom=bottoms, edgecolor='none')
                    bottoms = [b + v for b, v in zip(bottoms, vals)]

            # 在柱顶标注模型名称（flash / pro），方便区分两个模型
            short_name = model.replace('deepseek-v4-', '')
            offset = max(bottoms) * 0.02 if max(bottoms) > 0 else 0
            for xi, tot in enumerate(bottoms):
                ax.text(pos[xi], tot + offset, short_name,
                        ha='center', va='bottom', fontsize=5,
                        color=C['legend_color'])

        ax.set_xticks(x_pos)
        ax.set_xticklabels([str(d) for d in dates], rotation=40,
                           ha='right', fontsize=6)
        ax.set_title('每日Token消耗量', color=C['title_fg'], fontsize=9, pad=6)
        ax.tick_params(colors=C['tick_color'], labelsize=6)
        ax.set_ylabel('Tokens', color=C['label_color'], fontsize=7)
        ax.legend(fontsize=5, labelcolor=C['legend_color'])
        fig.tight_layout(pad=1.5)
        canvas = FigureCanvasTkAgg(fig, parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _embed_pie(self, parent, df):
        """饼图：展示两个模型的总费用占比"""
        C = self._C
        fig = Figure(figsize=(3.6, 2.4), dpi=100, facecolor=C['fig_face'])
        ax = fig.add_subplot(111, facecolor=C['fig_face'])
        wedges, texts, autotexts = ax.pie(
            df['cost'], labels=df['model'],
            autopct='%1.1f%%',
            colors=['#4ECDC4', '#FF6B6B'],
            textprops={'color': C['title_fg'], 'fontsize': 7},
            startangle=90,
        )
        for t in autotexts:
            t.set_color(C['fig_face'])
            t.set_fontsize(8)
        ax.set_title('模型-成本分布', color=C['title_fg'], fontsize=9, pad=6)
        fig.tight_layout(pad=1.5)
        canvas = FigureCanvasTkAgg(fig, parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _embed_token_bar(self, parent, df):
        """水平柱状图：按 Token 总量排名展示各 API Key 的用量"""
        C = self._C
        fig = Figure(figsize=(3.6, 2.4), dpi=100, facecolor=C['fig_face'])
        ax = fig.add_subplot(111, facecolor=C['ax_face'])
        top = df.nlargest(8, 'amount')   # 取前 8 名
        labels = [f"{r['model']}\n({r['api_key_name']})" for _, r in top.iterrows()]
        ax.barh(range(len(top)), top['amount'].values, color='#95E1D3', height=0.55)
        ax.set_yticks(range(len(top)))
        ax.set_yticklabels(labels, color=C['title_fg'], fontsize=5.5)
        ax.set_title('角色/模型-总token消耗情况', color=C['title_fg'], fontsize=9, pad=6)
        ax.tick_params(colors=C['tick_color'], labelsize=6)
        fig.tight_layout(pad=1.5)
        canvas = FigureCanvasTkAgg(fig, parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ══════════════════════════════════════════════════════
    #  启动入口
    # ══════════════════════════════════════════════════════

    def run(self):
        """进入 tkinter 主事件循环"""
        self.root.mainloop()


def main():
    """外部调用入口：创建磁贴实例并启动"""
    app = UsageWidget()
    app.run()


if __name__ == '__main__':
    main()
