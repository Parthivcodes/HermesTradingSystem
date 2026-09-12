FROM python:3.12-slim
WORKDIR /app
COPY . .
ENV PORT=5000
EXPOSE 5000
CMD ["python", "run_engine.py", "--capital", "100000", "--interval", "60"]
