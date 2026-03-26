FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

ENV LLM_COST_DB=/data/costs.db
EXPOSE 8877

CMD ["llm-cost-monitor", "start", "--host", "0.0.0.0", "--port", "8877"]
