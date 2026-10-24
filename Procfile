web: gunicorn memorphia_scanner.web_wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 90 --max-requests 2000 --max-requests-jitter 200
worker: python -m memorphia_scanner.worker
