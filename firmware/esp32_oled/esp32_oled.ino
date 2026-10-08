#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include "config.h"
#include "mouth_frames.h"   // 44 mouth bitmaps (tools/mouth/build_bank.py)
#include "mouth_select.h"   // nearest-frame choice from articulation channels

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
  int8_t frame;  // Mouth frame hint from the host, or -1
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

// Which Mouth frame to show now. Like the Lilyput chest board, the OLED shows
// one designed bitmap per event (no cross-fades): in-betweens are separate
// frames, and short gaps hold the previous pose instead of flashing rest.
int currentFrame(uint32_t now, bool &active) {
  active = false;
  if (!timelineRunning || timelineCount == 0 || (int32_t)(now - timelineStartedMs) < 0) {
    return MOUTH_V2_REST;
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
    return MOUTH_V2_REST;
  }
  active = true;
  if (event.frame >= 0 && event.frame < MOUTH_FRAME_COUNT) return event.frame;
  const Articulation a = decode(event);
  float muscles[MOUTH_CHANNELS];
  mouthMuscles(a.jaw, a.separation, a.width, a.roundness, a.press, a.protrusion, a.tuck, a.asymmetry, muscles);
  return mouthNearestFrame(muscles);
}

void renderFrame() {
  if (!oledReady) return;
  const uint32_t now = millis();
  bool active = false;
  const int frame = currentFrame(now, active);
  display.clearDisplay();
  display.drawBitmap(0, 0, MOUTH_FRAMES[frame], 128, 64, ROBOT_LIPSYNC_WHITE);
  display.display();
  if (active && !visibleStartReported) {
    visibleStartReported = true;
    reply("LIP/EVENT VISIBLE_START sid=%s board_ms=%lu index=%u frame=%d",
          timelineSession, (unsigned long)now, (unsigned)timelineIndex, frame);
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
  int frameHint = -1;
  int fieldCount = 0;
  int delayMs = 0;
  unsigned long offsetMs = 0;

  if (strcmp(line, "LIP/HELLO") == 0) {
    reply("LIP/OK HELLO protocol=1 device=esp32_oled capacity=%u channels=8 lips=mouth frames=%d",
          (unsigned)ROBOT_LIPSYNC_QUEUE_CAPACITY, MOUTH_FRAME_COUNT);
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
  } else if ((fieldCount = sscanf(
                  line,
                  "LIP/EVENT %16s %lu %u %d %d %d %d %d %d %d %d %d %d",
                  session, &atMs, &durationMs, &values[0], &values[1], &values[2],
                  &values[3], &values[4], &values[5], &values[6], &values[7],
                  &values[8], &frameHint)) >= 12) {
    if (fieldCount == 12) frameHint = -1;  // no frame hint: pick from channels
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
        event.frame = (frameHint >= 0 && frameHint < MOUTH_FRAME_COUNT) ? (int8_t)frameHint : (int8_t)-1;
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
