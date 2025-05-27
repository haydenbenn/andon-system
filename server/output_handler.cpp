#include "output_handler.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <chrono>
#include <iomanip>
#include <filesystem>
#include <algorithm>

namespace fs = std::filesystem;

OutputHandler::OutputHandler(const std::string& output_dir, const std::string& excel_prefix)
    : output_dir(output_dir), excel_prefix(excel_prefix), running(true) {
    
    // Create output directory if it doesn't exist
    if (!fs::exists(output_dir)) {
        fs::create_directories(output_dir);
        std::cout << getCurrentTime() << " - INFO - Created output directory: " << output_dir << std::endl;
    }
    
    // Start data processing thread
    processing_thread = std::thread(&OutputHandler::processDataQueue, this);
    std::cout << getCurrentTime() << " - INFO - Data processing thread started" << std::endl;
}

OutputHandler::~OutputHandler() {
    cleanup();
}

void OutputHandler::processDataQueue() {
    while (running) {
        std::pair<std::string, GPIOData> item;
        bool has_data = false;
        
        {
            std::lock_guard<std::mutex> lock(queue_mutex);
            if (!data_queue.empty()) {
                item = data_queue.front();
                data_queue.pop();
                has_data = true;
            }
        }
        
        if (has_data) {
            addDataToExcel(item.first, item.second);
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }
}

bool OutputHandler::addData(const std::string& device_name, const GPIOData& data) {
    std::lock_guard<std::mutex> lock(queue_mutex);
    data_queue.push({device_name, data});
    return true;
}

std::string OutputHandler::getPinName(int pin) {
    auto it = GPIO_PIN_NAMES.find(pin);
    if (it != GPIO_PIN_NAMES.end()) {
        return it->second;
    }
    return "Pin_" + std::to_string(pin);
}

void OutputHandler::addDataToExcel(const std::string& device_name, const GPIOData& data) {
    try {
        std::string excel_path = output_dir + "/" + excel_prefix + device_name + ".xlsx";
        
        // Check if file exists, create if not
        if (!fs::exists(excel_path)) {
            createNewExcel(device_name, excel_path);
        }
        
        // For now, we'll use CSV format since Excel manipulation in C++ is complex
        // Convert .xlsx to .csv for easier handling
        std::string csv_path = output_dir + "/" + excel_prefix + device_name + ".csv";
        
        std::ofstream file(csv_path, std::ios::app);
        if (file.is_open()) {
            // If file is new, add headers
            if (fs::file_size(csv_path) == 0) {
                file << "Timestamp,Pin,State,Time Difference (sec)" << std::endl;
            }
            
            // Add data row
            file << data.timestamp << "," 
                 << getPinName(data.pin) << "," 
                 << data.state << "," 
                 << data.time_diff_sec << std::endl;
            
            file.close();
            
            // Update file tracking
            {
                std::lock_guard<std::mutex> lock(file_mutex);
                excel_files[device_name].path = csv_path;
            }
            
            std::cout << getCurrentTime() << " - INFO - Added and saved data for " 
                      << device_name << std::endl;
        } else {
            std::cerr << getCurrentTime() << " - ERROR - Could not open file for " 
                      << device_name << std::endl;
        }
        
    } catch (std::exception& e) {
        std::cerr << getCurrentTime() << " - ERROR - Error adding data to Excel for " 
                  << device_name << ": " << e.what() << std::endl;
    }
}

void OutputHandler::createNewExcel(const std::string& device_name, const std::string& excel_path) {
    // Since we're using CSV, this just ensures the path is tracked
    std::lock_guard<std::mutex> lock(file_mutex);
    excel_files[device_name].path = excel_path;
    
    std::cout << getCurrentTime() << " - INFO - Created new file tracking for " 
              << device_name << ": " << excel_path << std::endl;
}

void OutputHandler::cleanup() {
    std::cout << getCurrentTime() << " - INFO - Cleaning up output handler..." << std::endl;
    running = false;
    
    // Wait for processing thread to finish
    if (processing_thread.joinable()) {
        processing_thread.join();
    }
    
    std::cout << getCurrentTime() << " - INFO - Output handler cleaned up" << std::endl;
}

std::string OutputHandler::getCurrentTime() {
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()) % 1000;
    
    std::stringstream ss;
    ss << std::put_time(std::localtime(&time_t), "%Y-%m-%d %H:%M:%S");
    ss << "." << std::setfill('0') << std::setw(3) << ms.count();
    return ss.str();
}