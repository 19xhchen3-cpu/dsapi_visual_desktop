"解压压缩包，读取数据，处理数据，保存数据到数据库中。"
import os
import re
from unittest import result
import zipfile
import pandas as pd
import glob
from tabulate import tabulate

def print_centered(df):
    """居中打印 DataFrame"""
    print(tabulate(df, headers='keys', tablefmt='pretty', stralign='center', numalign='center', showindex=False))

pd.set_option('display.colheader_justify', 'center')

#读取zip返回两个csv的内容
def read_csv_from_zip(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as z:
        # 打印压缩包中所有文件名
        print("压缩包中的文件列表:")
        for f in z.namelist():
            print(f"  - {f}")

        csv_files = [f for f in z.namelist() if f.endswith('.csv')]
        if not csv_files:
            raise ValueError("压缩包中没有找到 CSV 文件")


        # 第一个 CSV 赋值给 cost，第二个赋值给 amount
        print(f"正在读取: {csv_files[0]}")
        with z.open(csv_files[0]) as f:
            cost = pd.read_csv(f)

        print(f"正在读取: {csv_files[1]}")
        with z.open(csv_files[1]) as f:
            amount = pd.read_csv(f)

        return cost, amount

#返回文件的地址
def read_zip_name():
    zips = glob.glob("*.zip")
    if not zips:
        raise FileNotFoundError("当前文件夹没有找到 .zip 文件")
    return os.path.abspath(zips[0])

#读取对应的文件，将里面的内容进行处理
def data_samedate_cost(cost):
    result = cost.groupby("utc_date")["cost"].sum().reset_index()
    # print_centered(result)
    return result

def data_samemodel_cost(cost):
    result = cost.groupby("model")["cost"].sum().reset_index()
    # print_centered(result)
    return result

def data_samedatemodel_cost(cost):
    result = cost.groupby(["utc_date","model"])["cost"].sum().reset_index()
    # print_centered(result)
    return result

def data_samedatemodel_tokeninfo(amount):
    result = amount.groupby(["utc_date","model", "type"])["amount"].sum().reset_index()
    # print_centered(result)
    return result
def data_samedatemodel_requestinfo(amount):
    result = amount[amount["type"] == "request_count"].groupby(["utc_date","model","type"])["amount"].sum().reset_index()
    # print_centered(result)
    return result

def date_samemodelname_tokeninfo(amount):
    # 过滤掉 request_count，按 api_key_name 和 type 分组求和
    result = amount[amount["type"] != "request_count"].groupby(["model","api_key_name","type"])["amount"].sum().reset_index()

    # 计算每个 model + api_key_name 的 total_token（三个 type 之和）
    total = result.groupby(["model", "api_key_name"])["amount"].sum().reset_index()
    total["type"] = "total_token"

    # 合并结果
    result = pd.concat([result, total], ignore_index=True)

    # 排序：按 model、api_key_name 分组，每组内 total_token 排在最前
    type_order = {"input_cache_hit_tokens": 1, "input_cache_miss_tokens": 2, "output_tokens": 3, "total_token": 0}
    result["_sort"] = result["type"].map(type_order)
    result = result.sort_values(["model", "api_key_name", "_sort"]).drop(columns=["_sort"]).reset_index(drop=True)

    # print_centered(result)
    return result

def  draw_datemodelcost():

    return 0



def main():
    zip_path = read_zip_name()
    cost, amount = read_csv_from_zip(zip_path)
    print("\n=== cost ===")
    print_centered(cost.head())
    print("\n=== amount ===")
    print_centered(amount.head())
    data_samedate_cost(cost)
    data_samemodel_cost(cost)
    data_samedatemodel_cost(cost)
    data_samedatemodel_tokeninfo(amount)
    data_samedatemodel_requestinfo(amount)
    date_samemodelname_tokeninfo(amount)

if __name__ == "__main__":
    main()
