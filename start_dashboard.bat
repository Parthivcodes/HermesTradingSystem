@echo off
cd /d %~dp0\hermes-agent-main
python -m trading_engine --capital 100000 --interval 60 --port 5000
pause
