# AI-Powered-Smart-Agriculture-LoRa-FYP
Final Year Project: AI-powered smart agriculture monitoring system using LoRa communication, multi-parameter sensing and machine learning anomaly detection.

## Project Overview

This project presents a low-power smart agriculture monitoring prototype developed for chilli cultivation.

The system uses an ESP32-based field node to collect soil and environmental measurements and transmit them to a base station using SX1278 LoRa communication. The received data is logged and processed using Python, while an Isolation Forest machine-learning model is used to identify unusual sensor conditions.

A Streamlit dashboard provides sensor readings, historical trends, LoRa communication quality, anomaly-detection results and farmer-oriented alerts.

The prototype was designed as a proof of concept for agricultural environments where continuous internet connectivity may not be available at the field node.

## Main Features

- ESP32-based remote field node
- SX1278 433 MHz LoRa communication
- 7-in-1 RS485/Modbus soil sensor
- Soil moisture monitoring
- Soil temperature monitoring
- Electrical conductivity (EC)
- Soil pH
- Nitrogen, phosphorus and potassium (NPK)
- Air temperature and humidity monitoring
- Solar-powered field-node design
- ESP32 deep-sleep operation for reduced power consumption
- Packet acknowledgement and sequence tracking
- Expandable multi-hop LoRa communication architecture
- Python-based data logging
- SQLite data storage
- Isolation Forest anomaly detection
- Streamlit monitoring dashboard
- RSSI and SNR link-quality monitoring

## System Architecture

The overall data flow is:

Field Sensors  
↓  
ESP32 Field Node  
↓  
SX1278 LoRa Transmitter  
↓  
LoRa Base-Station Receiver  
↓  
ESP32 Receiver  
↓  
USB Serial Communication  
↓  
Python Base-Station Software  
↓  
SQLite Database / CSV Logging  
↓  
Isolation Forest Anomaly Detection  
↓  
Streamlit Dashboard

## Repository Structure

```text
AI-Powered-Smart-Agriculture-LoRa/
│
├── FYP_Transmitter/
│   └── ESP32 transmitter firmware
│
├── FYP_Receiver/
│   └── ESP32 receiver firmware
│
├── Base-Station/
│   ├── base_station.py
│   ├── dashboard.py
│   ├── load_dataset.py
│   ├── settings.py
│   └── requirements.txt
│
├── Dataset/
│   └── Field and home evaluation dataset
│
├── Hardware/
│   ├── Schematic
│   ├── PCB layout
│   └── Gerber / supporting design files
│
└── README.md
