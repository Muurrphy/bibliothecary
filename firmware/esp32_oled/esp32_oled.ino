#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include "config.h"

#if ROBOT_LIPSYNC_OLED_SH1106
#include <Adafruit_SH110X.h>
#define ROBOT_LIPSYNC_WHITE SH110X_WHITE
Adafruit_SH1106G display(
    128, 64, &Wire, -1,
    ROBOT_LIPSYNC_I2C_DURING,
    ROBOT_LIPSYNC_I2C_AFTER);
#else
#include <Adafruit_SSD1306.h>
#define ROBOT_LIPSYNC_WHITE SSD1306_WHITE
Adafruit_SSD1306 display(128, 64, &Wire, -1);
#endif

struct Articulation {
  float jaw;
  float separation;
  float width;
  float roundness;
  float press;
  float protrusion;
  float tuck;
  float asymmetry;
  float intensity;
};

struct TimelineEvent {
  uint32_t atMs;
  uint16_t durationMs;
  int16_t channels[9];
};

TimelineEvent timeline[ROBOT_LIPSYNC_QUEUE_CAPACITY];
uint16_t timelineCount = 0;
uint16_t timelineIndex = 0;
char timelineSession[17] = "none";
uint32_t timelineStartedMs = 0;
bool timelineRunning = false;
bool visibleStartReported = false;
bool oledReady = false;

char usbLine[180];
uint16_t usbLength = 0;
#if ROBOT_LIPSYNC_SECONDARY_UART
char uartLine[180];
uint16_t uartLength = 0;
#endif

uint32_t lastFrameMs = 0;

float clamp01(float value) {
  return max(0.0f, min(1.0f, value));
}

void emitReply(const char *text) {
  Serial.println(text);
#if ROBOT_LIPSYNC_SECONDARY_UART
  Serial1.println(text);
#endif
}

template <typename... Args>
void reply(const char *format, Args... args) {
  char output[180];
  snprintf(output, sizeof(output), format, args...);
  emitReply(output);
}

bool sameSession(const char *session) {
  return strncmp(session, timelineSession, sizeof(timelineSession)) == 0;
}

bool validSession(const char *session) {
  const size_t length = strlen(session);
  if (length == 0 || length > 16) return false;
  for (size_t i = 0; i < length; ++i) {
    const char c = session[i];
    if (!isalnum((unsigned char)c) && c != '_' && c != '-') return false;
  }
  return true;
}

Articulation restShape() {
  return {0.0f, 0.01f, 0.48f, 0.05f, 0.18f, 0.0f, 0.0f, 0.0f, 0.7f};
}

Articulation decode(const TimelineEvent &event) {
  Articulation result;
  result.jaw = clamp01(event.channels[0] / 1000.0f);
  result.separation = clamp01(event.channels[1] / 1000.0f);
  result.width = clamp01(event.channels[2] / 1000.0f);
  result.roundness = clamp01(event.channels[3] / 1000.0f);
  result.press = clamp01(event.channels[4] / 1000.0f);
  result.protrusion = clamp01(event.channels[5] / 1000.0f);
  result.tuck = clamp01(event.channels[6] / 1000.0f);
  result.asymmetry = max(-1.0f, min(1.0f, event.channels[7] / 1000.0f));
  result.intensity = clamp01(event.channels[8] / 1000.0f);
  return result;
}

Articulation mixShape(const Articulation &from, const Articulation &to, float amount) {
  amount = clamp01(amount);
  const float keep = 1.0f - amount;
  return {
      from.jaw * keep + to.jaw * amount,
      from.separation * keep + to.separation * amount,
      from.width * keep + to.width * amount,
      from.roundness * keep + to.roundness * amount,
      from.press * keep + to.press * amount,
      from.protrusion * keep + to.protrusion * amount,
      from.tuck * keep + to.tuck * amount,
      from.asymmetry * keep + to.asymmetry * amount,
      from.intensity * keep + to.intensity * amount,
  };
}

bool currentShape(uint32_t now, Articulation &shape) {
  if (!timelineRunning || timelineCount == 0 || (int32_t)(now - timelineStartedMs) < 0) {
    shape = restShape();
    return false;
  }

  const uint32_t elapsed = now - timelineStartedMs;
  while (timelineIndex + 1 < timelineCount && elapsed >= timeline[timelineIndex + 1].atMs) {
    ++timelineIndex;
  }
  const TimelineEvent &event = timeline[timelineIndex];
  const uint32_t eventEnd = event.atMs + event.durationMs;
  bool holdForNext = false;
  if (timelineIndex + 1 < timelineCount) {
    const uint32_t nextAt = timeline[timelineIndex + 1].atMs;
    holdForNext = nextAt >= eventEnd && nextAt - eventEnd <= ROBOT_LIPSYNC_SHORT_GAP_HOLD_MS;
  }
  if (elapsed < event.atMs || (elapsed >= eventEnd && !holdForNext)) {
    shape = restShape();
    return false;
  }

  const Articulation target = decode(event);
  const Articulation previous = timelineIndex == 0 ? restShape() : decode(timeline[timelineIndex - 1]);
  const uint16_t halfDuration = (uint16_t)(event.durationMs / 2);
  const uint16_t transitionMs = min((uint16_t)70, max((uint16_t)35, halfDuration));
  const float amount = clamp01((elapsed - event.atMs) / (float)transitionMs);
  shape = mixShape(previous, target, amount);
  return true;
}

float gaussian(float x, float center, float width) {
  const float z = (x - center) / width;
  return expf(-z * z);
}

void drawDotLips(const Articulation &a) {
  const float vertical = max(a.separation, a.jaw * 0.92f);
  const float halfWidth = (40.0f + 19.0f * a.width) * (1.0f - 0.40f * a.roundness);
  const float gap = (1.0f + 15.0f * vertical) * (1.0f - 0.92f * a.press);
  const float upperThickness = 6.0f + 4.0f * a.protrusion + 2.0f * a.intensity;
  const float lowerThickness = (8.0f + 5.0f * a.protrusion + 2.0f * a.intensity) * (1.0f - 0.42f * a.tuck);
  const float centerX = 64.0f + 4.0f * a.asymmetry;
  const float centerY = 32.0f;

  for (int y = 2; y < 63; y += 3) {
    for (int x = 2; x < 127; x += 3) {
      const float nx = (x - centerX) / halfWidth;
      if (fabsf(nx) > 1.0f) continue;
      const float edge = sqrtf(max(0.0f, 1.0f - nx * nx));
      const float peaks = gaussian(nx, -0.26f, 0.20f) + gaussian(nx, 0.26f, 0.20f);
      const float center = gaussian(nx, 0.0f, 0.17f);
      const float cornerLift = (1.0f - edge) * 2.2f;

      const float upperInner = centerY - gap * 0.5f + cornerLift + center * (2.4f * (1.0f - vertical));
      const float upperOuter = upperInner - upperThickness * (0.32f + 0.68f * edge) - peaks * 2.6f + center * 1.8f;
      const float lowerInner = centerY + gap * 0.5f - cornerLift * 0.55f;
      const float lowerOuter = lowerInner + lowerThickness * (0.28f + 0.72f * edge) + center * 1.4f;

      if ((y >= upperOuter && y <= upperInner) || (y >= lowerInner && y <= lowerOuter)) {
        display.fillRect(x, y, 2, 2, ROBOT_LIPSYNC_WHITE);
      }
    }
  }
}

void renderFrame() {
  if (!oledReady) return;
  const uint32_t now = millis();
  Articulation shape;
  const bool active = currentShape(now, shape);
  display.clearDisplay();
  drawDotLips(shape);
  display.display();
  if (active && !visibleStartReported) {
    visibleStartReported = true;
    reply("LIP/EVENT VISIBLE_START sid=%s board_ms=%lu index=%u",
          timelineSession, (unsigned long)now, (unsigned)timelineIndex);
  }
}

void resetTimeline(const char *session) {
  strncpy(timelineSession, session, sizeof(timelineSession) - 1);
  timelineSession[sizeof(timelineSession) - 1] = '\0';
  timelineCount = 0;
  timelineIndex = 0;
  timelineStartedMs = 0;
  timelineRunning = false;
  visibleStartReported = false;
}

void handleLine(char *line) {
  while (*line == ' ') ++line;
  char session[17] = {0};
  unsigned long atMs = 0;
  unsigned int durationMs = 0;
  int values[9] = {0};
  int delayMs = 0;
  unsigned long offsetMs = 0;

  if (strcmp(line, "LIP/HELLO") == 0) {
    reply("LIP/OK HELLO protocol=1 device=esp32_oled capacity=%u channels=8",
          (unsigned)ROBOT_LIPSYNC_QUEUE_CAPACITY);
  } else if (strcmp(line, "LIP/DIAG") == 0) {
    Wire.beginTransmission(ROBOT_LIPSYNC_OLED_ADDRESS);
    const uint8_t i2cError = Wire.endTransmission();
    reply("LIP/OK DIAG oled=%s i2c=%s queue=%u running=%s",
          oledReady ? "ready" : "missing", i2cError == 0 ? "ack" : "error",
          (unsigned)timelineCount, timelineRunning ? "yes" : "no");
  } else if (sscanf(line, "LIP/RESET %16s", session) == 1) {
    if (!validSession(session)) {
      emitReply("LIP/ERR RESET reason=invalid_session");
    } else {
      resetTimeline(session);
      reply("LIP/OK RESET sid=%s capacity=%u", timelineSession,
            (unsigned)ROBOT_LIPSYNC_QUEUE_CAPACITY);
    }
  } else if (sscanf(
                 line,
                 "LIP/EVENT %16s %lu %u %d %d %d %d %d %d %d %d %d",
                 session, &atMs, &durationMs, &values[0], &values[1], &values[2],
                 &values[3], &values[4], &values[5], &values[6], &values[7],
                 &values[8]) == 12) {
    if (!sameSession(session)) {
      emitReply("LIP/ERR EVENT reason=session_mismatch");
    } else if (timelineCount >= ROBOT_LIPSYNC_QUEUE_CAPACITY) {
      emitReply("LIP/ERR EVENT reason=queue_full");
    } else if (durationMs < 1 || durationMs > 10000 || atMs > 600000UL) {
      emitReply("LIP/ERR EVENT reason=invalid_time");
    } else if (timelineCount > 0 && atMs < timeline[timelineCount - 1].atMs) {
      emitReply("LIP/ERR EVENT reason=non_monotonic");
    } else {
      bool valid = values[7] >= -1000 && values[7] <= 1000;
      for (int i = 0; i < 9; ++i) {
        if (i != 7 && (values[i] < 0 || values[i] > 1000)) valid = false;
      }
      if (!valid) {
        emitReply("LIP/ERR EVENT reason=invalid_channel");
      } else {
        TimelineEvent &event = timeline[timelineCount++];
        event.atMs = (uint32_t)atMs;
        event.durationMs = (uint16_t)durationMs;
        for (int i = 0; i < 9; ++i) event.channels[i] = (int16_t)values[i];
      }
    }
  } else if (sscanf(line, "LIP/START %16s %d %lu", session, &delayMs, &offsetMs) == 3) {
    if (!sameSession(session) || timelineCount == 0) {
      emitReply("LIP/ERR START reason=session_or_empty");
    } else if (delayMs < 0 || delayMs > 5000 || offsetMs > 600000UL) {
      emitReply("LIP/ERR START reason=invalid_time");
    } else {
      timelineIndex = 0;
      timelineStartedMs = millis() + (uint32_t)delayMs - (uint32_t)offsetMs;
      timelineRunning = true;
      visibleStartReported = false;
      reply("LIP/OK START sid=%s board_ms=%lu delay_ms=%d offset_ms=%lu events=%u",
            timelineSession, (unsigned long)millis(), delayMs, offsetMs,
            (unsigned)timelineCount);
    }
  } else if (sscanf(line, "LIP/COUNT %16s", session) == 1) {
    if (!sameSession(session)) {
      emitReply("LIP/ERR COUNT reason=session_mismatch");
    } else {
      reply("LIP/OK COUNT sid=%s events=%u capacity=%u", timelineSession,
            (unsigned)timelineCount, (unsigned)ROBOT_LIPSYNC_QUEUE_CAPACITY);
    }
  } else if (sscanf(line, "LIP/END %16s", session) == 1) {
    if (!sameSession(session)) {
      emitReply("LIP/ERR END reason=session_mismatch");
    } else {
      timelineRunning = false;
      reply("LIP/OK END sid=%s events=%u", timelineSession, (unsigned)timelineCount);
    }
  } else if (*line) {
    emitReply("LIP/ERR COMMAND reason=unknown");
  }
}

void pollStream(Stream &stream, char *buffer, uint16_t &length) {
  while (stream.available()) {
    const char value = (char)stream.read();
    if (value == '\n' || value == '\r') {
      if (length > 0) {
        buffer[length] = '\0';
        handleLine(buffer);
        length = 0;
      }
    } else if (length < 179) {
      buffer[length++] = value;
    } else {
      length = 0;
      emitReply("LIP/ERR COMMAND reason=line_too_long");
    }
  }
}

bool beginDisplay() {
#if ROBOT_LIPSYNC_OLED_SH1106
  return display.begin(ROBOT_LIPSYNC_OLED_ADDRESS, true);
#else
  return display.begin(SSD1306_SWITCHCAPVCC, ROBOT_LIPSYNC_OLED_ADDRESS);
#endif
}

void setup() {
  Serial.begin(115200);
#if ROBOT_LIPSYNC_SECONDARY_UART
  Serial1.setRxBufferSize(1024);
  Serial1.begin(ROBOT_LIPSYNC_UART_BAUD, SERIAL_8N1,
                ROBOT_LIPSYNC_UART_RX, ROBOT_LIPSYNC_UART_TX);
#endif
  Wire.begin(ROBOT_LIPSYNC_OLED_SDA, ROBOT_LIPSYNC_OLED_SCL);
  Wire.setClock(ROBOT_LIPSYNC_I2C_AFTER);
  oledReady = beginDisplay();
  if (oledReady) {
    renderFrame();
    reply("LIP/OK READY protocol=1 oled=128x64 address=0x%02X",
          ROBOT_LIPSYNC_OLED_ADDRESS);
  } else {
    emitReply("LIP/ERR READY reason=oled_not_found");
  }
}

void loop() {
  pollStream(Serial, usbLine, usbLength);
#if ROBOT_LIPSYNC_SECONDARY_UART
  pollStream(Serial1, uartLine, uartLength);
#endif
  const uint32_t now = millis();
  if (now - lastFrameMs >= ROBOT_LIPSYNC_FRAME_INTERVAL_MS) {
    lastFrameMs = now;
    renderFrame();
  }
}
