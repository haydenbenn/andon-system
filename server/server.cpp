#include <iostream>
#include <string>
#include <thread>
#include <vector>
#include <map>
#include <mutex>
#include <atomic>
#include <fstream>
#include <sstream>
#include <chrono>
#include <csignal>
#include <cstring>
#include <algorithm>
#include <iomanip>

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #ifdef _MSC_VER
        #pragma comment(lib, "ws2_32.lib")
    #endif
    typedef int socklen_t;
    #define CLOSE_SOCKET closesocket
#else
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #define CLOSE_SOCKET close
#endif

#include "json.hpp"
#include "output_handler.h"

using json = nlohmann::json;

// Forward declaration
class AndonServer;

// Global pointer for signal handler
AndonServer* g_server_instance = nullptr;

class AndonServer {
private:
    std::string host;
    int port;
    int max_connections;
    std::string output_dir;
    std::string excel_prefix;
    std::atomic<bool> running;
    std::mutex clients_mutex;
    std::map<std::string, int> clients;
    OutputHandler* output_handler;
    
    // Configuration structure
    struct Config {
        std::string host = "0.0.0.0";
        int port = 5000;
        int max_connections = 50;
        std::string output_dir = "data";
        std::string excel_prefix = "data_";
    };
    
public:
    AndonServer() : running(true), output_handler(nullptr) {
        Config config = loadConfig();
        host = config.host;
        port = config.port;
        max_connections = config.max_connections;
        output_dir = config.output_dir;
        excel_prefix = config.excel_prefix;
        
        // Set global instance for signal handler
        g_server_instance = this;
        
        // Setup signal handling
        std::signal(SIGINT, signalHandler);
        std::signal(SIGTERM, signalHandler);
        
        // Create output handler
        output_handler = new OutputHandler(output_dir, excel_prefix);
        
        std::cout << getCurrentTime() << " - INFO - Output handler initialized" << std::endl;
        
#ifdef _WIN32
        // Initialize Winsock
        WSADATA wsaData;
        if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
            std::cerr << "WSAStartup failed" << std::endl;
            exit(1);
        }
#endif
    }
    
    ~AndonServer() {
        cleanup();
#ifdef _WIN32
        WSACleanup();
#endif
    }
    
    void stop() {
        running = false;
    }
    
    Config loadConfig() {
        Config config;
        std::ifstream file("andon_server.conf");
        
        if (!file.is_open()) {
            std::cout << getCurrentTime() << " - INFO - Config file not found, using default configuration" << std::endl;
            createDefaultConfig();
            return config;
        }
        
        std::string line;
        std::string section;
        
        while (std::getline(file, line)) {
            // Remove whitespace
            line.erase(std::remove_if(line.begin(), line.end(), ::isspace), line.end());
            
            if (line.empty() || line[0] == '#') continue;
            
            if (line[0] == '[' && line.back() == ']') {
                section = line.substr(1, line.length() - 2);
                continue;
            }
            
            size_t pos = line.find('=');
            if (pos != std::string::npos) {
                std::string key = line.substr(0, pos);
                std::string value = line.substr(pos + 1);
                
                if (section == "server") {
                    if (key == "host") config.host = value;
                    else if (key == "port") config.port = std::stoi(value);
                    else if (key == "max_connections") config.max_connections = std::stoi(value);
                } else if (section == "data") {
                    if (key == "output_dir") config.output_dir = value;
                    else if (key == "excel_prefix") config.excel_prefix = value;
                }
            }
        }
        
        std::cout << getCurrentTime() << " - INFO - Configuration loaded from andon_server.conf" << std::endl;
        return config;
    }
    
    void createDefaultConfig() {
        std::ofstream file("andon_server.conf");
        if (file.is_open()) {
            file << "[server]\n";
            file << "host = 0.0.0.0\n";
            file << "port = 5000\n";
            file << "max_connections = 50\n\n";
            file << "[data]\n";
            file << "output_dir = data\n";
            file << "excel_prefix = data_\n";
            file.close();
            std::cout << getCurrentTime() << " - INFO - Default configuration saved to andon_server.conf" << std::endl;
        }
    }
    
    void handleClient(int client_socket, const std::string& client_ip) {
        std::cout << getCurrentTime() << " - INFO - New connection from " << client_ip << std::endl;
        
        try {
            // Set receive timeout
            struct timeval timeout;
            timeout.tv_sec = 5;
            timeout.tv_usec = 0;
            setsockopt(client_socket, SOL_SOCKET, SO_RCVTIMEO, (char*)&timeout, sizeof(timeout));
            
            // Receive data
            std::string data;
            char buffer[4096];
            
            while (true) {
                int bytes_received = recv(client_socket, buffer, sizeof(buffer) - 1, 0);
                if (bytes_received <= 0) break;
                
                buffer[bytes_received] = '\0';
                data += buffer;
                
                // Try to parse JSON to check if we have complete data
                try {
                    auto temp = json::parse(data);
                    break; // Successfully parsed, we have complete data
                } catch (json::parse_error&) {
                    // Not complete data yet, continue receiving
                    continue;
                }
            }
            
            if (!data.empty()) {
                try {
                    // Parse JSON data
                    json json_data = json::parse(data);
                    
                    std::string device_name = json_data.value("device_name", "unknown");
                    int pin = json_data.value("pin", 0);
                    std::string state = json_data.value("state", "unknown");
                    double time_diff_sec = json_data.value("time_diff_sec", 0.0);
                    std::string timestamp = json_data.value("timestamp", getCurrentTime());
                    
                    std::cout << getCurrentTime() << " - INFO - Received data from " << device_name 
                              << ": pin " << pin << " changed to " << state << std::endl;
                    
                    // Create data structure
                    GPIOData gpio_data;
                    gpio_data.pin = pin;
                    gpio_data.state = state;
                    gpio_data.time_diff_sec = time_diff_sec;
                    gpio_data.timestamp = timestamp;
                    
                    // Send to output handler
                    bool success = output_handler->addData(device_name, gpio_data);
                    
                    if (success) {
                        std::cout << getCurrentTime() << " - INFO - Data for " << device_name 
                                  << " sent to output handler" << std::endl;
                        send(client_socket, "OK", 2, 0);
                    } else {
                        std::cerr << getCurrentTime() << " - ERROR - Failed to process data for " 
                                  << device_name << std::endl;
                        send(client_socket, "ERROR: Failed to process data", 29, 0);
                    }
                    
                } catch (json::parse_error& e) {
                    std::cerr << getCurrentTime() << " - ERROR - Error parsing JSON from " 
                              << client_ip << ": " << e.what() << std::endl;
                    send(client_socket, "ERROR: Invalid JSON format", 26, 0);
                } catch (std::exception& e) {
                    std::cerr << getCurrentTime() << " - ERROR - Error processing data from " 
                              << client_ip << ": " << e.what() << std::endl;
                    send(client_socket, "ERROR: Internal server error", 28, 0);
                }
            }
        } catch (std::exception& e) {
            std::cerr << getCurrentTime() << " - ERROR - Error handling client " 
                      << client_ip << ": " << e.what() << std::endl;
        }
        
        CLOSE_SOCKET(client_socket);
        std::cout << getCurrentTime() << " - INFO - Connection from " << client_ip << " closed" << std::endl;
    }
    
    static void signalHandler(int /* sig */) {
        std::cout << "\nShutdown signal received, cleaning up..." << std::endl;
        if (g_server_instance) {
            g_server_instance->stop();
        }
    }
    
    void cleanup() {
        std::cout << getCurrentTime() << " - INFO - Cleaning up resources..." << std::endl;
        if (output_handler) {
            output_handler->cleanup();
            delete output_handler;
            output_handler = nullptr;
        }
        std::cout << getCurrentTime() << " - INFO - All resources cleaned up" << std::endl;
    }
    
    void start() {
        try {
            int server_socket = socket(AF_INET, SOCK_STREAM, 0);
            if (server_socket < 0) {
                std::cerr << "Failed to create socket" << std::endl;
                return;
            }
            
            // Set socket options
            int opt = 1;
            setsockopt(server_socket, SOL_SOCKET, SO_REUSEADDR, (char*)&opt, sizeof(opt));
            
            struct sockaddr_in server_addr;
            memset(&server_addr, 0, sizeof(server_addr));
            server_addr.sin_family = AF_INET;
            server_addr.sin_port = htons(port);
            
            if (host == "0.0.0.0") {
                server_addr.sin_addr.s_addr = INADDR_ANY;
            } else {
                inet_pton(AF_INET, host.c_str(), &server_addr.sin_addr);
            }
            
            if (bind(server_socket, (struct sockaddr*)&server_addr, sizeof(server_addr)) < 0) {
                std::cerr << getCurrentTime() << " - ERROR - Failed to bind to " 
                          << host << ":" << port << std::endl;
                CLOSE_SOCKET(server_socket);
                return;
            }
            
            std::cout << getCurrentTime() << " - INFO - Successfully bound to " 
                      << host << ":" << port << std::endl;
            
            if (listen(server_socket, max_connections) < 0) {
                std::cerr << "Failed to listen on socket" << std::endl;
                CLOSE_SOCKET(server_socket);
                return;
            }
            
            std::cout << getCurrentTime() << " - INFO - Server started on " 
                      << host << ":" << port << std::endl;
            std::cout << getCurrentTime() << " - INFO - Saving data to directory: " 
                      << output_dir << std::endl;
            std::cout << getCurrentTime() << " - INFO - Ready to handle up to " 
                      << max_connections << " concurrent connections" << std::endl;
            
            while (running) {
                struct sockaddr_in client_addr;
                socklen_t client_len = sizeof(client_addr);
                
                // Set a timeout for accept to allow checking running flag
                struct timeval timeout;
                timeout.tv_sec = 1;
                timeout.tv_usec = 0;
                setsockopt(server_socket, SOL_SOCKET, SO_RCVTIMEO, (char*)&timeout, sizeof(timeout));
                
                int client_socket = accept(server_socket, (struct sockaddr*)&client_addr, &client_len);
                if (client_socket < 0) {
                    if (running) {
                        // Only log error if we're still supposed to be running
                        continue;
                    }
                    break;
                }
                
                std::string client_ip = inet_ntoa(client_addr.sin_addr);
                std::cout << getCurrentTime() << " - INFO - Accepted connection from " 
                          << client_ip << ":" << ntohs(client_addr.sin_port) << std::endl;
                
                // Start a new thread to handle client
                std::thread client_thread(&AndonServer::handleClient, this, client_socket, client_ip);
                client_thread.detach();
            }
            
            CLOSE_SOCKET(server_socket);
            std::cout << getCurrentTime() << " - INFO - Server socket closed" << std::endl;
            
        } catch (std::exception& e) {
            std::cerr << getCurrentTime() << " - ERROR - Server error: " << e.what() << std::endl;
        }
        
        cleanup();
    }
    
private:
    std::string getCurrentTime() {
        auto now = std::chrono::system_clock::now();
        auto time_t = std::chrono::system_clock::to_time_t(now);
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;
        
        std::stringstream ss;
        ss << std::put_time(std::localtime(&time_t), "%Y-%m-%d %H:%M:%S");
        ss << "." << std::setfill('0') << std::setw(3) << ms.count();
        return ss.str();
    }
};

int main() {
    AndonServer server;
    server.start();
    return 0;
}
