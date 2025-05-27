#ifndef OUTPUT_HANDLER_H
#define OUTPUT_HANDLER_H

#include <string>
#include <map>
#include <mutex>
#include <thread>
#include <queue>
#include <atomic>
#include <ctime>

// GPIO Pin Names
const std::map<int, std::string> GPIO_PIN_NAMES = {
    {23, "Green"},
    {24, "Yellow"}, 
    {25, "Red"},
    {12, "Load"}
};

struct GPIOData {
    int pin;
    std::string state;
    double time_diff_sec;
    std::string timestamp;
};

struct ExcelFile {
    std::string path;
};

class OutputHandler {
private:
    std::string output_dir;
    std::string excel_prefix;
    std::map<std::string, ExcelFile> excel_files;
    std::mutex file_mutex;
    std::queue<std::pair<std::string, GPIOData>> data_queue;
    std::mutex queue_mutex;
    std::thread processing_thread;
    std::atomic<bool> running;
    
    void processDataQueue();
    void addDataToExcel(const std::string& device_name, const GPIOData& data);
    void createNewExcel(const std::string& device_name, const std::string& excel_path);
    std::string getCurrentTime();
    std::string getPinName(int pin);
    
public:
    OutputHandler(const std::string& output_dir, const std::string& excel_prefix);
    ~OutputHandler();
    
    bool addData(const std::string& device_name, const GPIOData& data);
    void cleanup();
};

#endif // OUTPUT_HANDLER_H