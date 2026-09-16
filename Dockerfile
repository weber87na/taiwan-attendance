FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY attendance/ attendance/
COPY data/ data/
COPY web/ web/
RUN useradd --create-home --uid 10001 attendance && mkdir runtime && chown attendance:attendance runtime
USER attendance
EXPOSE 8000
CMD ["python", "-m", "attendance", "serve", "--host", "0.0.0.0"]
