#!/bin/bash

# Build script for Andon Server

echo "Building Andon Server..."

# Create data directory
mkdir -p data

# Detect OS and build accordingly
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    echo "Building for Windows..."
    g++ -std=c++17 -Wall -Wextra -O2 -I. server.cpp output_handler.cpp -o andon_server.exe -lws2_32
    if [ $? -eq 0 ]; then
        echo "Build successful! Created andon_server.exe"
    else
        echo "Build failed!"
        exit 1
    fi
else
    echo "Building for Linux/Unix..."
    g++ -std=c++17 -Wall -Wextra -O2 -I. server.cpp output_handler.cpp -o andon_server -pthread
    if [ $? -eq 0 ]; then
        echo "Build successful! Created andon_server"
    else
        echo "Build failed!"
        exit 1
    fi
fi

echo "Done!"