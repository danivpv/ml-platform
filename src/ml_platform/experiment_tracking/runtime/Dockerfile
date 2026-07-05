FROM python:3.12-slim

# Install mlflow server + postgres driver + boto3 for S3 artifact access.
# Versions are unpinned placeholders — Thread 2 will pin after validating
# compatibility. See PRD §6.4 for CVE scanning hardening.
RUN pip install --no-cache-dir \
    "mlflow[extras]==2.14.*" \
    "psycopg2-binary" \
    "boto3"

# ECS agent injects the following env vars at container start via ECS Secrets:
#   DB_USERNAME, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
# and plain env vars:
#   MLFLOW_HOST, MLFLOW_PORT, MLFLOW_ARTIFACT_ROOT
#
# The CMD below constructs the Postgres backend store URI from those vars
# so no plaintext credentials appear in this image or the task definition.
CMD ["sh", "-c", \
     "exec mlflow server \
       --backend-store-uri postgresql://${DB_USERNAME}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME} \
       --artifacts-destination ${MLFLOW_ARTIFACT_ROOT} \
       --host ${MLFLOW_HOST} \
       --port ${MLFLOW_PORT}"]
