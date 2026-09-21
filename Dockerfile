FROM python:3.12-slim

# Evita criação de arquivos .pyc e garante logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências básicas do sistema operacional
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalação das dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Copia os arquivos do projeto
COPY . .

# Diretório para persistência do banco SQLite
RUN mkdir -p /app/data

EXPOSE 5000

# Executa migrações/seed e inicia o Gunicorn
CMD ["sh", "-c", "python init_db.py && gunicorn --workers 3 --bind 0.0.0.0:5000 --timeout 120 run:app"]
