@echo off
chcp 65001 >nul
echo ============================================
echo   A股每日投资分析报告 - 自动生成
echo ============================================
echo.

cd /d "%~dp0"

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /1
}

REM 安装依赖
echo [1/2] 检查依赖...
pip install -q requests >nul 2>&1

REM 生成报告
echo [2/2] 生成报告...
python report.py

echo.
echo ============================================
echo   完成！报告已生成在当前目录
echo ============================================
pause
