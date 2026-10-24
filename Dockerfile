FROM python:3.12-slim
WORKDIR /app/paperbot
COPY paperbot/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY paperbot/ ./
RUN python -m unittest discover -s tests -p "test_*.py"
ENV PYTHONUNBUFFERED=1 PORT=10000 TRADER_CLOUD=true TRADER_STORAGE=broker TRADER_STATE_DIR=/tmp/paper-trader ALPACA_PAPER_TRADE=true PAPER_ENTRIES_ENABLED=false
EXPOSE 10000
CMD ["python", "-u", "trader/standalone/web.py"]
