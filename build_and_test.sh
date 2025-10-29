#!/bin/bash

# Build and test script for ESG App Docker container

echo "🐳 Building Docker image for ESG App..."

# Build the Docker image
docker build -t esg-app:latest .

if [ $? -eq 0 ]; then
    echo "✅ Docker image built successfully!"
    
    echo "🧪 Testing Docker container..."
    
    # Run the container in detached mode
    docker run -d \
        --name esg-app-test \
        -p 8501:8501 \
        -v $(pwd)/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro \
        esg-app:latest
    
    if [ $? -eq 0 ]; then
        echo "✅ Container started successfully!"
        echo "🌐 App should be available at: http://localhost:8501"
        echo ""
        echo "📊 Container logs:"
        docker logs esg-app-test
        echo ""
        echo "🔍 Container status:"
        docker ps | grep esg-app-test
        echo ""
        echo "⏹️  To stop the container: docker stop esg-app-test"
        echo "🗑️  To remove the container: docker rm esg-app-test"
    else
        echo "❌ Failed to start container"
        exit 1
    fi
else
    echo "❌ Docker build failed"
    exit 1
fi
