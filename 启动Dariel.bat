@echo off
chcp 65001 >/dev/null
cd /d %~dp0

echo.
echo   ╔══════════════════════════╗
echo   ║   Dariel 唤醒中...       ║
echo   ╚══════════════════════════╝
echo.

:: Step 1: 预跑 wake.py
D:\Python\python.exe dariel\wake.py
if %errorlevel% neq 0 (
    echo [warn] wake.py 执行异常，继续启动...
)

:: Step 2: 快速查看 QQ 待回消息数
if exist dariel\tts\qq_push.json (
    D:\Python\python.exe -c "import json; d=json.load(open('dariel/tts/qq_push.json','r',encoding='utf-8')); print(f'QQ 待回: {d[\"count\"]} 条')" 2>/dev/null
)

echo.
echo   启动 Claude Code (注入 BP1)...
echo.

:: Step 3: 注入 BP1 触发词
claude "执行BP1"
