@echo off
chcp 65001 >nul
rem 两处占位要自己换：<devtools> = 微信开发者工具安装目录，<ascii-dir> = 纯 ASCII 的项目目录（见 README「真机预览」）
call "<devtools>\cli.bat" preview --project <ascii-dir> --qr-format image --qr-output <ascii-dir>\mp_preview.png
echo EXIT=%ERRORLEVEL%
