# Stage 1: Build Stage
# Use a lightweight Python image as the base image
FROM python:3.9-alpine as builder

# Install dependencies required for the build process
# Alpine doesn't use apt-get, so we'll use apk instead for package management
RUN apk add --no-cache \
    curl \
    unzip \
    docker-cli \
    build-base \
    libffi-dev \
    openssl-dev && \
    rm -rf /var/cache/apk/*

# Install AWS CLI
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf awscliv2.zip aws

# Set the working directory
WORKDIR /app

# Copy only the requirements file to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
# This creates a virtual environment in the 'build' directory to keep the final image small
RUN python3 -m venv /app/venv && \
    source /app/venv/bin/activate && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Final Stage
# Use a fresh, minimal Python image as the base for the final image
FROM python:3.9-alpine

# Set the working directory in the final image
WORKDIR /app

# Copy the virtual environment from the build stage
COPY --from=builder /app/venv /app/venv

# Copy the application code from the host machine to the container
COPY . .

# Ensure the virtual environment's binaries are on the PATH
ENV PATH="/app/venv/bin:$PATH"

# Expose port 5000 to allow the application to be accessible
EXPOSE 5000

# Set the command to run the Flask application
CMD ["python3", "app.py"]
