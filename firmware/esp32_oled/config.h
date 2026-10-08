#pragma once

// Reference hardware: ESP32-C3 SuperMini + 1.3-inch SH1106 128x64 I2C OLED.
// Change these values before compiling for another board.
#ifndef ROBOT_LIPSYNC_OLED_SH1106
#define ROBOT_LIPSYNC_OLED_SH1106 1
#endif
#define ROBOT_LIPSYNC_OLED_ADDRESS 0x3C
#define ROBOT_LIPSYNC_OLED_SDA 6
#define ROBOT_LIPSYNC_OLED_SCL 7

// The SH1106 transfer itself runs at 300 kHz, then the bus returns to 100 kHz.
// This leaves time between 20 fps full-frame writes on breadboard wiring.
#define ROBOT_LIPSYNC_I2C_DURING 300000
#define ROBOT_LIPSYNC_I2C_AFTER 100000
#define ROBOT_LIPSYNC_FRAME_INTERVAL_MS 50
#define ROBOT_LIPSYNC_QUEUE_CAPACITY 256
#define ROBOT_LIPSYNC_SHORT_GAP_HOLD_MS 90

// Optional second UART for a head-controller bridge. USB Serial always remains on.
#define ROBOT_LIPSYNC_SECONDARY_UART 0
#define ROBOT_LIPSYNC_UART_RX 20
#define ROBOT_LIPSYNC_UART_TX 21
#define ROBOT_LIPSYNC_UART_BAUD 115200
