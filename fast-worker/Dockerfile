# ------------------------------------------------------------------------
# Dockerfile for FAST (Flood Assessment for TxDOT)
# Dockhub Image name: civileng127/fast-update:20250504
# Description: Realtime update of FAST Database
# Flood Assesment System for TxDOT
# From a hydrologic forecast (National Water Model)
# update the flooded roads (lines), flood limits (polygons)
# and bridge warnings (points)
#
# Base Image: continuumio/miniconda3:latest
#  -- Uses the Debian 11; 'bullseye'
# Version: 1.0.0
# Created by: Andy Carter, PE 
# -- Center for Water and the Environment
# -- University of Texas at Austin
# Date: 2025-05-04
# Revised: 2025-06-16
# 
# License: BSD 3-Clause License
# ------------------------------------------------------------------------

# docker run -e DB_PASSWORD='enter_password_here' -v ~/.aws:/root/.aws civileng127/fast-update:20250504

# ------------------------------------------------------------------------
# 2025-07-17  Modified by KISTERS -- Adjusted to support fully local deployment and better concurrency


# Use the Miniconda base image from Continuum
FROM continuumio/miniconda3:latest

# Install apt packages first
RUN apt-get update && apt-get install -y git nano wget proj-bin

# Upgrade base env: use mamba for speed
RUN conda install -y mamba -n base -c conda-forge

# Install Python 3.12 and conda packages via mamba
RUN mamba install -y -c conda-forge \
    python=3.12 \
    gdal \
    geopandas \
    xarray \
    sqlalchemy \
    tqdm \
    numpy \
    shapely \
    netcdf4 \
    h5netcdf \
    proj

# Install pip-only packages with compatible versions
RUN pip install \
    psycopg2-binary \
    boto3==1.34.103 \
    s3fs==2024.5.0 \
    geoalchemy2 \
    pyyaml \
    esrijson \
    pydantic_settings \
    pydantic \
    fastapi \
    uvicorn


# Clean caches
RUN conda clean -afy && rm -rf /var/lib/apt/lists/*

# Ensure conda is in PATH
ENV PATH /opt/conda/bin:$PATH

# # Copy your source
# COPY ../src /fast_realtime/src
# COPY ../inputs /fast_realtime/inputs
# COPY ../sql /fast_realtime/sql


# Do just mount points
RUN mkdir -p /fast_realtime/src \
             /fast_realtime/inputs \
             /fast_realtime/sql \
             /fast_realtime/output \
             /fast_realtime/data

# Add build timestamp
RUN echo "Rebuilt at $(date)" > /fast_realtime/last_built.txt

# Set working directory
WORKDIR /fast_realtime/src

# Default command
CMD ["python", "fast_realtime_update.py", "-c", "config_realtime_linux.ini"]
