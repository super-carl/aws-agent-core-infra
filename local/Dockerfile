# Local SuperCarl API — stdlib only, no AWS. Build context is the repo root:
#   docker build -f local/Dockerfile -t supercarl-local .
FROM python:3.12-slim

WORKDIR /app
# The local server reuses the deterministic generators in functions/people_search.
COPY functions/people_search/supercarl_client.py ./functions/people_search/supercarl_client.py
COPY local/local_server.py ./local/local_server.py

EXPOSE 8080
ENV PORT=8080 HOST=0.0.0.0
CMD ["python", "local/local_server.py"]
