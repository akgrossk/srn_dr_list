# ESG App - Docker Deployment Guide

This guide explains how to build, test, and deploy the ESG Streamlit application using Docker.

## 📋 Prerequisites

- Docker installed on your system
- Docker Compose (optional, for easier management)
- Access to the `.streamlit/secrets.toml` file with your API keys

## 🐳 Quick Start

### Option 1: Using Docker Compose (Recommended)

1. **Start the application:**
   ```bash
   docker-compose up -d
   ```

2. **View logs:**
   ```bash
   docker-compose logs -f
   ```

3. **Stop the application:**
   ```bash
   docker-compose down
   ```

### Option 2: Using Docker Commands

1. **Build the image:**
   ```bash
   docker build -t esg-app:latest .
   ```

2. **Run the container:**
   ```bash
   docker run -d \
     --name esg-app \
     -p 8501:8501 \
     -v $(pwd)/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro \
     esg-app:latest
   ```

3. **View logs:**
   ```bash
   docker logs -f esg-app
   ```

4. **Stop the container:**
   ```bash
   docker stop esg-app && docker rm esg-app
   ```

## 🚀 Production Deployment

### Using the Production Dockerfile

For production deployments, use the optimized multi-stage build:

```bash
docker build -f Dockerfile.prod -t esg-app:prod .
```

### Environment Variables

You can also pass environment variables directly:

```bash
docker run -d \
  --name esg-app \
  -p 8501:8501 \
  -e OPENAI_API_KEY="your-openai-key" \
  -e SUPABASE_URL="your-supabase-url" \
  -e SUPABASE_ANON_KEY="your-supabase-anon-key" \
  esg-app:latest
```

## 🔧 Configuration

### Secrets Management

The application requires the following secrets in `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "your-openai-api-key"
SUPABASE_ANON_KEY = "your-supabase-anon-key"
SUPABASE_PUBLIC_KEY = "your-supabase-public-key"
SUPABASE_URL = "your-supabase-url"
```

### Port Configuration

The default port is 8501. To change it:

```bash
docker run -d \
  --name esg-app \
  -p 8080:8501 \
  -v $(pwd)/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro \
  esg-app:latest
```

## 📊 Monitoring

### Health Checks

The container includes health checks. Check status:

```bash
docker ps
```

### Logs

View application logs:

```bash
docker logs esg-app
```

### Container Stats

Monitor resource usage:

```bash
docker stats esg-app
```

## 🧪 Testing

### Automated Testing Script

Use the provided script to build and test:

```bash
chmod +x build_and_test.sh
./build_and_test.sh
```

### Manual Testing

1. **Build and run:**
   ```bash
   docker build -t esg-app:test .
   docker run -d --name esg-test -p 8501:8501 -v $(pwd)/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro esg-app:test
   ```

2. **Test the application:**
   - Open http://localhost:8501 in your browser
   - Verify the app loads correctly
   - Test the tracking functionality

3. **Clean up:**
   ```bash
   docker stop esg-test && docker rm esg-test
   ```

## 🚢 Deployment Options

### Docker Hub

1. **Tag your image:**
   ```bash
   docker tag esg-app:latest yourusername/esg-app:latest
   ```

2. **Push to Docker Hub:**
   ```bash
   docker push yourusername/esg-app:latest
   ```

3. **Deploy from Docker Hub:**
   ```bash
   docker run -d --name esg-app -p 8501:8501 yourusername/esg-app:latest
   ```

### AWS ECS / Google Cloud Run / Azure Container Instances

The Docker image is compatible with all major cloud container services. Use the same environment variables and port configuration.

### Kubernetes

Create a deployment YAML:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: esg-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: esg-app
  template:
    metadata:
      labels:
        app: esg-app
    spec:
      containers:
      - name: esg-app
        image: esg-app:latest
        ports:
        - containerPort: 8501
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: esg-secrets
              key: openai-api-key
        - name: SUPABASE_URL
          valueFrom:
            secretKeyRef:
              name: esg-secrets
              key: supabase-url
---
apiVersion: v1
kind: Service
metadata:
  name: esg-app-service
spec:
  selector:
    app: esg-app
  ports:
  - port: 80
    targetPort: 8501
  type: LoadBalancer
```

## 🔒 Security Considerations

1. **Non-root user:** The container runs as a non-root user for security
2. **Secrets management:** Use proper secrets management in production
3. **Network security:** Configure appropriate firewall rules
4. **Image scanning:** Regularly scan images for vulnerabilities

## 📈 Performance Optimization

### Resource Limits

Set resource limits for production:

```bash
docker run -d \
  --name esg-app \
  --memory="1g" \
  --cpus="1.0" \
  -p 8501:8501 \
  esg-app:latest
```

### Multi-stage Build

The production Dockerfile uses multi-stage builds for smaller image size.

## 🐛 Troubleshooting

### Common Issues

1. **Port already in use:**
   ```bash
   docker ps
   docker stop <container-id>
   ```

2. **Secrets not found:**
   - Ensure `.streamlit/secrets.toml` exists
   - Check file permissions
   - Verify volume mount path

3. **App not loading:**
   ```bash
   docker logs esg-app
   ```

4. **Health check failing:**
   ```bash
   docker exec -it esg-app curl http://localhost:8501/_stcore/health
   ```

### Debug Mode

Run in interactive mode for debugging:

```bash
docker run -it --rm \
  -p 8501:8501 \
  -v $(pwd)/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro \
  esg-app:latest /bin/bash
```

## 📝 File Structure

```
.
├── Dockerfile              # Development Dockerfile
├── Dockerfile.prod         # Production Dockerfile
├── docker-compose.yml      # Docker Compose configuration
├── .dockerignore           # Docker ignore file
├── build_and_test.sh       # Build and test script
├── requirements.txt        # Python dependencies
├── esg_app.py             # Main application
└── .streamlit/
    └── secrets.toml       # Application secrets
```

## 🎯 Next Steps

1. Set up CI/CD pipeline for automated builds
2. Configure monitoring and alerting
3. Set up log aggregation
4. Implement backup strategies
5. Configure auto-scaling for high availability
