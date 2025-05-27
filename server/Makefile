# Makefile for Andon Server

# Detect OS
ifeq ($(OS),Windows_NT)
    DETECTED_OS := Windows
else
    DETECTED_OS := $(shell uname -s)
endif

# Compiler settings
CXX = g++
CXXFLAGS = -std=c++17 -Wall -Wextra -O2

# OS-specific settings
ifeq ($(DETECTED_OS),Windows)
    LIBS = -lws2_32
    TARGET = andon_server.exe
    RM = del /Q
    MKDIR = mkdir
else
    LIBS = -pthread
    TARGET = andon_server
    RM = rm -f
    MKDIR = mkdir -p
endif

# Include directories
INCLUDES = -I./include -I.

# Source files
SOURCES = server.cpp output_handler.cpp
OBJECTS = $(SOURCES:.cpp=.o)

# Default target
all: $(TARGET)

# Build the main executable
$(TARGET): $(OBJECTS)
	$(CXX) $(CXXFLAGS) $(OBJECTS) -o $(TARGET) $(LIBS)

# Compile source files
%.o: %.cpp
	$(CXX) $(CXXFLAGS) $(INCLUDES) -c $< -o $@

# Clean build artifacts
clean:
ifeq ($(DETECTED_OS),Windows)
	if exist *.o $(RM) *.o
	if exist $(TARGET) $(RM) $(TARGET)
else
	$(RM) $(OBJECTS) $(TARGET)
endif

# Create data directory
setup:
	$(MKDIR) data

# Install dependencies (Ubuntu/Debian)
install-deps-linux:
	sudo apt-get update
	sudo apt-get install -y build-essential nlohmann-json3-dev

# Install dependencies (Windows with vcpkg)
install-deps-windows:
	vcpkg install nlohmann-json:x64-windows

# Install dependencies (Windows with MSYS2)
install-deps-msys2:
	pacman -S mingw-w64-x86_64-nlohmann-json

# Build with debug symbols
debug: CXXFLAGS += -g -DDEBUG
debug: $(TARGET)

# Help
help:
	@echo "Available targets:"
	@echo "  all               - Build the Andon server"
	@echo "  debug             - Build with debug symbols"
	@echo "  clean             - Remove build artifacts"
	@echo "  setup             - Create data directories"
	@echo "  install-deps-linux    - Install dependencies (Linux)"
	@echo "  install-deps-windows  - Install dependencies (Windows with vcpkg)"
	@echo "  install-deps-msys2    - Install dependencies (Windows with MSYS2)"
	@echo "  help              - Show this help message"
	@echo ""
	@echo "Detected OS: $(DETECTED_OS)"

.PHONY: all clean setup install-deps-linux install-deps-windows install-deps-msys2 debug help