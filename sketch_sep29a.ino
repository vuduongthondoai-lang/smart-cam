#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

// ==============================
// WIFI
// ==============================
const char* ssid = "DUONG2G";
const char* password = "28012005";

// ==============================
// AI Thinker ESP32-CAM
// ==============================
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5

#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// ==============================
// HTTP STREAM
// ==============================
#define PART_BOUNDARY "123456789000000000000987654321"

static const char* _STREAM_CONTENT_TYPE =
    "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;

static const char* _STREAM_BOUNDARY =
    "\r\n--" PART_BOUNDARY "\r\n";

static const char* _STREAM_PART =
    "Content-Type: image/jpeg\r\n"
    "Content-Length: %u\r\n\r\n";

httpd_handle_t stream_httpd = NULL;

// ==============================
// STREAM HANDLER
// ==============================
static esp_err_t stream_handler(httpd_req_t *req)
{
  camera_fb_t *fb = NULL;
  esp_err_t res = ESP_OK;

  char part_buf[64];

  res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
  httpd_resp_set_hdr(req, "Cache-Control", "no-cache");
httpd_resp_set_hdr(req, "Pragma", "no-cache");
httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

  if (res != ESP_OK) {
    return res;
  }

  while (true)
  {
    fb = esp_camera_fb_get();

    if (!fb)
    {
      Serial.println("Camera capture failed");
      res = ESP_FAIL;
      break;
    }

    if (fb->format != PIXFORMAT_JPEG)
    {
      Serial.println("Frame is not JPEG");
      esp_camera_fb_return(fb);
      res = ESP_FAIL;
      break;
    }

    size_t hlen = snprintf(
      part_buf,
      sizeof(part_buf),
      _STREAM_PART,
      fb->len
    );

    res = httpd_resp_send_chunk(
      req,
      part_buf,
      hlen
    );

    if (res == ESP_OK)
    {
      res = httpd_resp_send_chunk(
        req,
        (const char *)fb->buf,
        fb->len
      );
    }

    if (res == ESP_OK)
    {
      res = httpd_resp_send_chunk(
        req,
        _STREAM_BOUNDARY,
        strlen(_STREAM_BOUNDARY)
      );
    }

    esp_camera_fb_return(fb);

    if (res != ESP_OK)
    {
      break;
    }
  }

  return res;
}

// ==============================
// ROOT PAGE
// ==============================
static esp_err_t index_handler(httpd_req_t *req)
{
  const char* html = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">

<title>ESP32-CAM OV5640</title>

<style>
body {
  background: #111;
  color: white;
  font-family: Arial;
  text-align: center;
}

h1 {
  margin-top: 20px;
}

img {
  width: 95%;
  max-width: 900px;
  height: auto;
  border: 2px solid white;
}

.info {
  margin: 15px;
  font-size: 18px;
}
</style>

</head>

<body>

<h1>ESP32-CAM OV5640</h1>

<div class="info">
  Real-time Camera Stream
</div>

<img src="/stream">

</body>
</html>
)rawliteral";

  httpd_resp_set_type(req, "text/html");

  return httpd_resp_send(
    req,
    html,
    strlen(html)
  );
}

// ==============================
// START WEB SERVER
// ==============================
void startCameraServer()
{
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();

  config.server_port = 80;

  httpd_uri_t index_uri = {
    .uri       = "/",
    .method    = HTTP_GET,
    .handler   = index_handler,
    .user_ctx  = NULL
  };

  httpd_uri_t stream_uri = {
    .uri       = "/stream",
    .method    = HTTP_GET,
    .handler   = stream_handler,
    .user_ctx  = NULL
  };

  Serial.println("Starting HTTP server...");

  if (httpd_start(&stream_httpd, &config) == ESP_OK)
  {
    httpd_register_uri_handler(
      stream_httpd,
      &index_uri
    );

    httpd_register_uri_handler(
      stream_httpd,
      &stream_uri
    );

    Serial.println("HTTP server started!");
  }
  else
  {
    Serial.println("HTTP server failed!");
  }
}

// ==============================
// SETUP
// ==============================
void setup()
{
  Serial.begin(115200);

  delay(2000);

  Serial.println();
  Serial.println("==============================");
  Serial.println(" ESP32-CAM OV5640 STREAM");
  Serial.println("==============================");

  // ============================
  // CAMERA CONFIG
  // ============================

  camera_config_t config;

  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;

  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;

  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;

  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;

  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;

  config.xclk_freq_hz = 20000000;

  config.pixel_format = PIXFORMAT_JPEG;

  // ============================
  // PSRAM
  // ============================
  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA;   // 640x480
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.grab_mode = CAMERA_GRAB_LATEST;
}
  else
  {
    Serial.println("PSRAM: NOT FOUND");

    config.frame_size = FRAMESIZE_QVGA;

    config.jpeg_quality = 15;

    config.fb_count = 1;

    config.fb_location = CAMERA_FB_IN_DRAM;

    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  }

  // ============================
  // INIT CAMERA
  // ============================

  Serial.println("Initializing camera...");

  esp_err_t err = esp_camera_init(&config);

  if (err != ESP_OK)
  {
    Serial.print("CAMERA INIT FAILED: 0x");
    Serial.println(err, HEX);

    while (true)
    {
      delay(1000);
    }
  }

  Serial.println("CAMERA INIT OK!");

  // ============================
  // SENSOR INFO
  // ============================

  sensor_t *s = esp_camera_sensor_get();

  if (s != NULL)
  {
    Serial.print("Sensor PID: 0x");
    Serial.println(s->id.PID, HEX);

    Serial.print("Sensor VER: 0x");
    Serial.println(s->id.VER, HEX);

    Serial.print("Sensor MIDH: 0x");
    Serial.println(s->id.MIDH, HEX);

    Serial.print("Sensor MIDL: 0x");
    Serial.println(s->id.MIDL, HEX);
  }

  // ============================
  // WIFI
  // ============================

  Serial.println();
  Serial.println("Connecting to WiFi...");

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);

    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi connected!");

  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  // ============================
  // START SERVER
  // ============================

  startCameraServer();

  Serial.println();
  Serial.println("==============================");
  Serial.println(" CAMERA READY!");
  Serial.println("==============================");

  Serial.print("Open browser: http://");
  Serial.println(WiFi.localIP());
}

// ==============================
// LOOP
// ==============================
void loop()
{
  delay(1000);
}