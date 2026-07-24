#!/bin/bash
# A股每日投资分析报告 - Mac/Linux 自动生成脚本
cd "$(dirname "$0")"

echo "============================================"
echo "  A股每日投资分析报告 - 自动生成"
echo "============================================"
echo

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 python3，请先安装"
    exit 1
fi

# 安装依赖
echo "[1/2] 检查依赖..."
pip3 install -q requests 2>/dev/null

# 生成报告
echo "[2/2] 生成报告..."
python3 report.py

echo
echo "============================================"
echo "  完成！报告已生成在当前目录"
echo "============================================"
