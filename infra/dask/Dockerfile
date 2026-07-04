# Shared image for the Dask scheduler, Dask worker, and Jupyter services in
# this scaffold -- one image, one build, so scheduler/worker/client always
# agree on dask/pandas/pyarrow versions (Dask requires matching versions
# across scheduler/worker/client or task (de)serialization can fail with
# confusing errors). Built locally on each node that runs a service from
# this image -- there is no shared registry in this repo, and Swarm stacks
# ignore any `build:` key, so this must be run manually first. See README.md.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /home/notebooks
