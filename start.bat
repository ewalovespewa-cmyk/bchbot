@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BCH Bot

echo [1/3] Обновляю бота с GitHub...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $z=Join-Path $env:TEMP 'bch.zip'; $d=Join-Path $env:TEMP 'bch'; Invoke-WebRequest 'https://github.com/ewalovespewa-cmyk/bchbot/archive/refs/heads/main.zip' -UseBasicParsing -OutFile $z; if (Test-Path $d) { Remove-Item $d -Recurse -Force }; Expand-Archive $z $d -Force; Copy-Item (Join-Path $d 'bchbot-main\*') . -Recurse -Force -Exclude 'start.bat'"
if errorlevel 1 (
    echo   Не получилось скачать обновление - запускаю ту версию, что уже есть.
) else (
    echo   Готово, версия свежая.
)

echo [2/3] Проверяю библиотеки...
python -m pip install -q -r requirements.txt

if exist ".env" goto run
echo.
echo Первый запуск: нужен токен бота от @BotFather.
set /p "TOKEN=Вставь токен и нажми Enter: "
> ".env" echo BOT_TOKEN=%TOKEN%
>> ".env" echo ADMIN_IDS=1999072927
echo   Токен сохранён в файл .env в этой папке - больше спрашивать не буду.

:run
echo [3/3] Запускаю бота. Чтобы остановить - закрой это окно.
echo.
python main.py
echo.
echo Бот остановился. Если выше красная ошибка - сделай скриншот.
pause
