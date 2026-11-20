FROM python:3.12-slim
# tzdata: necessário para o fuso (variável TZ) funcionar na imagem enxuta
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
ENV HOST=0.0.0.0 PORT=8000 TZ=America/Manaus DB_PATH=/data/lembramed.db
EXPOSE 8000
# Um único processo: o agendador de alarmes roda dentro dele (vários processos mandariam avisos em dobro)
CMD ["python", "app.py"]
