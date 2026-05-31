import data_Process
import draw

if __name__ == "__main__":
    try:
        import dataDownload
        print("正在下载最新数据...")
        dataDownload.main()
    except ImportError:
        print("playwright 未安装，跳过下载，使用已有数据")
    except Exception as e:
        print(f"下载失败: {e}，使用已有数据")

    print("\n数据处理:")
    data_Process.main()

    print("\n启动桌面磁贴...")
    draw.main()