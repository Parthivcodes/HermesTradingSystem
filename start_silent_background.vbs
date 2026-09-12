Set WshShell = CreateObject("WScript.Shell")
WshShell.run "python run_engine.py --capital 100000 --interval 60 --port 5000", 0, False
