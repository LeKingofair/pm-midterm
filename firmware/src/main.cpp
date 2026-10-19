// PM transmitter: s(t) = sin(2*pi*fc*t + kp*m(t)) on GPIO25 (DAC1)
#include <Arduino.h>
#include "soc/rtc_io_reg.h"
#include "soc/soc.h"

constexpr uint32_t FS      = 40000;  // DAC sample rate (Hz)
constexpr int      DAC_PIN = 25;
constexpr int      POT_PIN = 34;
constexpr int      LED_PIN = 2;      // onboard LED, heartbeat
constexpr int      TABLE   = 1024;   // sine table size (10-bit phase index)

DRAM_ATTR static uint8_t dacTable[TABLE];  // 128 + 100*sin -> DAC codes
DRAM_ATTR static int8_t  msgTable[TABLE];  // 127*sin -> message samples

volatile uint32_t carrierAcc = 0, carrierStep = 0;
volatile uint32_t msgAcc = 0, msgStep = 0;
volatile int32_t  kpScale = 0;  // phase counts per message unit
volatile int32_t  potMsg  = 0;  // pot message, -127..127
volatile uint8_t  mode    = 1;  // 0 carrier, 1 sine, 2 pot

float g_fc = 4000.0f, g_fm = 200.0f, g_kp = 1.0f;
hw_timer_t *timer = nullptr;

void IRAM_ATTR onTimer() {
  carrierAcc += carrierStep;
  int32_t m = 0;
  if (mode == 1) { msgAcc += msgStep; m = msgTable[msgAcc >> 22]; }
  else if (mode == 2) { m = potMsg; }
  uint32_t phase = carrierAcc + (uint32_t)(m * kpScale);
  SET_PERI_REG_BITS(RTC_IO_PAD_DAC1_REG, RTC_IO_PDAC1_DAC,
                    dacTable[phase >> 22], RTC_IO_PDAC1_DAC_S);
}

void applySettings() {
  carrierStep = (uint32_t)((double)g_fc / FS * 4294967296.0);
  msgStep     = (uint32_t)((double)g_fm / FS * 4294967296.0);
  kpScale     = (int32_t)((double)g_kp / (2.0 * PI) * 4294967296.0 / 127.0);
}

void printStatus() {
  const char *names[] = {"carrier", "sine", "pot"};
  Serial.printf("mode=%s fc=%.1f Hz fm=%.1f Hz kp=%.3f rad pot=%d\n",
                names[mode], g_fc, g_fm, g_kp, (int)potMsg);
}

void printHelp() {
  Serial.println("Commands: mode carrier|sine|pot  kp <0-3>  fm <Hz>  fc <Hz>  status");
}

void handleCommand(String line) {
  line.trim();
  if (line.startsWith("mode ")) {
    String m = line.substring(5);
    if (m == "carrier") mode = 0;
    else if (m == "sine") mode = 1;
    else if (m == "pot") mode = 2;
    else { Serial.println("unknown mode"); return; }
  } else if (line.startsWith("kp ")) {
    g_kp = constrain(line.substring(3).toFloat(), 0.0f, 3.0f);
  } else if (line.startsWith("fm ")) {
    g_fm = constrain(line.substring(3).toFloat(), 1.0f, 1000.0f);
  } else if (line.startsWith("fc ")) {
    g_fc = constrain(line.substring(3).toFloat(), 1000.0f, 8000.0f);
  } else if (line != "status") {
    printHelp();
    return;
  }
  applySettings();
  printStatus();
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  analogReadResolution(12);
  for (int i = 0; i < TABLE; i++) {
    float s = sinf(2.0f * PI * i / TABLE);
    dacTable[i] = (uint8_t)lroundf(128.0f + 100.0f * s);
    msgTable[i] = (int8_t)lroundf(127.0f * s);
  }
  dacWrite(DAC_PIN, 128);                       // powers up DAC1 on GPIO25
  applySettings();
  timer = timerBegin(0, 80, true);              // 80 MHz / 80 = 1 MHz tick
  timerAttachInterrupt(timer, &onTimer, true);
  timerAlarmWrite(timer, 1000000 / FS, true);   // 25 ticks = 40 kHz
  timerAlarmEnable(timer);
  delay(500);
  printHelp();
  printStatus();
}

void loop() {
  static float potFiltered = 2048;
  static uint32_t lastBlink = 0, lastPrint = 0;
  potFiltered += 0.05f * (analogRead(POT_PIN) - potFiltered);  // smooth the knob
  potMsg = constrain((int32_t)lroundf((potFiltered - 2048.0f) / 2048.0f * 127.0f), -127, 127);

  if (Serial.available()) handleCommand(Serial.readStringUntil('\n'));

  uint32_t now = millis();
  if (now - lastBlink > 500) { lastBlink = now; digitalWrite(LED_PIN, !digitalRead(LED_PIN)); }
  if (mode == 2 && now - lastPrint > 1000) { lastPrint = now; printStatus(); }
  delay(2);
}