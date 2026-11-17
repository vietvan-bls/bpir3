/*
  ESP32 gửi dữ liệu lên BPI-R3 qua MQTT có TLS (Tailscale Funnel) và nhận lệnh từ trang /iot.

  Thư viện: PubSubClient (Nick O'Leary). Board: ESP32 (Arduino core 2.x / 3.x).
  1. Chép secrets.example.h -> secrets.h, điền Wi-Fi + tài khoản MQTT.
  2. Nạp code. Mở Serial Monitor 115200 để xem log.

  Topic (tài khoản "<tên>" chỉ dùng được iot/<tên>/...):
    iot/<tên>          JSON dữ liệu mỗi SEND_EVERY_MS  -> trang /iot tách thành từng giá trị
    iot/<tên>/status   online / offline (LWT, giữ lại)
    iot/<tên>/set      lệnh từ trang /iot: "on" / "off" bật tắt LED
    iot/<tên>/led      trạng thái LED (dùng làm "topic trạng thái" cho công tắc trên trang /iot)
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <time.h>
#include "secrets.h"

#define LED_PIN 2                 // LED trên nhiều board ESP32 DevKit; đổi nếu board khác
const unsigned long SEND_EVERY_MS = 10000;

// Funnel dùng chứng chỉ Let's Encrypt; chuỗi chứng chỉ nối lên ISRG Root X2 và ISRG Root X1.
static const char ROOT_CA[] PROGMEM = R"PEM(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh
cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4
WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu
ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY
MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc
h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+
0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U
A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW
T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH
B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC
B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv
KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn
OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn
jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw
qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI
rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq
hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL
ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ
3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK
NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5
ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur
TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC
jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc
oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq
4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA
mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d
emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=
-----END CERTIFICATE-----
-----BEGIN CERTIFICATE-----
MIICGzCCAaGgAwIBAgIQQdKd0XLq7qeAwSxs6S+HUjAKBggqhkjOPQQDAzBPMQsw
CQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJuZXQgU2VjdXJpdHkgUmVzZWFyY2gg
R3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBYMjAeFw0yMDA5MDQwMDAwMDBaFw00
MDA5MTcxNjAwMDBaME8xCzAJBgNVBAYTAlVTMSkwJwYDVQQKEyBJbnRlcm5ldCBT
ZWN1cml0eSBSZXNlYXJjaCBHcm91cDEVMBMGA1UEAxMMSVNSRyBSb290IFgyMHYw
EAYHKoZIzj0CAQYFK4EEACIDYgAEzZvVn4CDCuwJSvMWSj5cz3es3mcFDR0HttwW
+1qLFNvicWDEukWVEYmO6gbf9yoWHKS5xcUy4APgHoIYOIvXRdgKam7mAHf7AlF9
ItgKbppbd9/w+kHsOdx1ymgHDB/qo0IwQDAOBgNVHQ8BAf8EBAMCAQYwDwYDVR0T
AQH/BAUwAwEB/zAdBgNVHQ4EFgQUfEKWrt5LSDv6kviejM9ti6lyN5UwCgYIKoZI
zj0EAwMDaAAwZQIwe3lORlCEwkSHRhtFcP9Ymd70/aTSVaYgLXTWNLxBo1BfASdW
tL4ndQavEi51mI38AjEAi/V3bNTIZargCyzuFJ0nN6T5U6VR5CmD1/iQMVtCnwr1
/q4AaOeMSQ+2b1tbFfLn
-----END CERTIFICATE-----
)PEM";

WiFiClientSecure net;
PubSubClient mqtt(net);
String base = String("iot/") + MQTT_USER;
bool ledOn = false;
unsigned long lastSend = 0;

void setLed(bool on) {
  ledOn = on;
  digitalWrite(LED_PIN, on ? HIGH : LOW);
  mqtt.publish((base + "/led").c_str(), on ? "on" : "off", true);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  String msg;
  for (unsigned int i = 0; i < len; i++) msg += (char)payload[i];
  msg.trim();
  msg.toLowerCase();
  Serial.printf("Lệnh %s: %s\n", topic, msg.c_str());
  if (String(topic) == base + "/set") {
    if (msg == "on" || msg == "1" || msg == "true") setLed(true);
    else if (msg == "off" || msg == "0" || msg == "false") setLed(false);
    else if (msg == "toggle") setLed(!ledOn);
  }
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Wi-Fi %s ", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 60 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print('.'); }
  Serial.println(WiFi.status() == WL_CONNECTED ? " OK " + WiFi.localIP().toString() : " lỗi");
}

// TLS cần đồng hồ đúng để kiểm tra hạn chứng chỉ.
void syncTime() {
  configTime(7 * 3600, 0, "pool.ntp.org", "time.google.com");
  Serial.print("Đồng bộ giờ ");
  for (int i = 0; i < 40 && time(nullptr) < 1700000000; i++) { delay(250); Serial.print('.'); }
  Serial.println(time(nullptr) >= 1700000000 ? " OK" : " lỗi (TLS có thể thất bại)");
}

void connectMqtt() {
  while (!mqtt.connected()) {
    connectWiFi();
    String id = base + "-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    Serial.printf("MQTT %s:%d ... ", MQTT_HOST, MQTT_PORT);
    // LWT: mất kết nối thì broker tự báo offline
    if (mqtt.connect(id.c_str(), MQTT_USER, MQTT_PASS, (base + "/status").c_str(), 1, true, "offline")) {
      Serial.println("OK");
      mqtt.publish((base + "/status").c_str(), "online", true);
      mqtt.subscribe((base + "/set").c_str(), 1);
      setLed(ledOn);
    } else {
      // -2: không mở được kết nối/TLS, 4: sai user/mật khẩu, 5: không có quyền
      Serial.printf("lỗi %d, thử lại sau 5 giây\n", mqtt.state());
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  connectWiFi();
  syncTime();
  net.setCACert(ROOT_CA);
  net.setHandshakeTimeout(30);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(15);
  mqtt.setBufferSize(512);
}

void loop() {
  connectMqtt();
  mqtt.loop();
  if (millis() - lastSend >= SEND_EVERY_MS) {
    lastSend = millis();
    // Thay bằng dữ liệu cảm biến thật (DHT22, BME280...)
    char json[160];
    snprintf(json, sizeof(json), "{\"rssi\": %d, \"uptime\": %lu, \"heap\": %u}",
             WiFi.RSSI(), millis() / 1000, ESP.getFreeHeap());
    mqtt.publish(base.c_str(), json);
    Serial.printf("Gửi %s\n", json);
  }
}
