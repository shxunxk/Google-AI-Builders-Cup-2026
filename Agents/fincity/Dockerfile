FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY Agents/fincity/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Agents/__init__.py Agents/__init__.py
COPY Agents/fincity/ Agents/fincity/
COPY Agents/build_index.py Agents/duel.py Agents/
COPY Agents/attacker/ Agents/attacker/
COPY Agents/courtroom/ Agents/courtroom/

EXPOSE 8080

CMD ["sh", "-c", "uvicorn Agents.fincity.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
