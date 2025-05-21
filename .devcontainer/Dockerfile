# Dockerfile for python-app
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Set the working directory
#WORKDIR /app

# Copy the requirements file into the container (if you have one)
# COPY requirements.txt .

RUN apt update
RUN apt upgrade -y
RUN apt install -y ack vim graphviz cmake

# Install the required Python modules
RUN pip install --upgrade pip
RUN pip install black build
RUN pip install pydot jsonschema

# Copy the rest of your application code into the container
# COPY . .

# Command to run your application
CMD ["sleep", "infinity"]