#!/usr/bin/env python3
"""
批量测试脚本：处理0314测试的pdf目录下的所有PDF文件
"""
import os
import requests
import base64
import glob
import time

# 配置
PDF_DIR = "0314测试的pdf"
OUTPUT_DIR = "test_results"
API_URL = "http://localhost:8000/ocr/upload"

# 获取所有PDF文件
pdf_files = sorted(glob.glob(f"{PDF_DIR}/*.pdf"))
print(f"找到 {len(pdf_files)} 个PDF文件")

for pdf_path in pdf_files:
    filename = os.path.basename(pdf_path)
    # 生成订单号（基于文件名）
    order_no = os.path.splitext(filename)[0][:50]  # 限制长度
    print(f"\n{'='*60}")
    print(f"处理文件: {filename}")
    print(f"订单号: {order_no}")

    try:
        # 读取PDF文件
        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        # 构建请求
        files = {
            'files': (filename, pdf_content, 'application/pdf')
        }
        data = {
            'order_no': order_no,
            'account_no': '',
            'account_name': '',
            'cust_name': '',
            'company_name': '',
        }

        # 发送请求
        print(f"发送请求到 {API_URL}...")
        start_time = time.time()

        response = requests.post(
            API_URL,
            files=files,
            data=data,
            timeout=600  # 10分钟超时
        )

        elapsed = time.time() - start_time
        print(f"请求完成，耗时: {elapsed:.1f}秒")
        print(f"响应状态: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"响应内容: {result.get('csvUrl', 'N/A')}")

            # 保存CSV文件
            csv_url = result.get('csvUrl')
            if csv_url:
                # 下载CSV文件
                csv_response = requests.get(f"http://localhost:8000{csv_url}")
                if csv_response.status_code == 200:
                    # 保存到输出目录
                    output_filename = f"{order_no}.csv"
                    output_path = os.path.join(OUTPUT_DIR, output_filename)
                    with open(output_path, 'wb') as f:
                        f.write(csv_response.content)
                    print(f"CSV已保存到: {output_path}")

                    # 同时打印记录数
                    content = csv_response.content.decode('utf-8-sig')
                    lines = content.strip().split('\n')
                    print(f"记录数: {len(lines) - 1} 行")
            else:
                # 检查csvFile字段（base64编码的CSV）
                csv_file_b64 = result.get('csvFile')
                if csv_file_b64:
                    csv_content = base64.b64decode(csv_file_b64)
                    output_filename = f"{order_no}.csv"
                    output_path = os.path.join(OUTPUT_DIR, output_filename)
                    with open(output_path, 'wb') as f:
                        f.write(csv_content)
                    print(f"CSV已保存到: {output_path}")

                    # 打印记录数
                    content = csv_content.decode('utf-8-sig')
                    lines = content.strip().split('\n')
                    print(f"记录数: {len(lines) - 1} 行")
                else:
                    print("未获取到CSV数据")
        else:
            print(f"请求失败: {response.text}")

    except Exception as e:
        print(f"处理出错: {e}")

print(f"\n{'='*60}")
print("所有文件处理完成!")
