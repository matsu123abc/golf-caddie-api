import math
import os
import json
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from fastapi import File, UploadFile, Form
from azure.storage.blob import BlobServiceClient
from datetime import datetime, timedelta, timezone
import requests
import math
from io import BytesIO
from PIL import Image
from fastapi.responses import StreamingResponse

app = FastAPI()

connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
blob_service = BlobServiceClient.from_connection_string(connection_string)
container = blob_service.get_container_client("course-maps")

# -------------------------
# 距離計算ロジック
# -------------------------
class GPSData(BaseModel):
    lat1: float
    lon1: float
    lat2: float
    lon2: float

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # 地球の半径（メートル）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

@app.get("/", response_class=HTMLResponse)
def home():
    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Golf Tools</title>
        <style>
            body {
                margin: 0;
                padding: 24px;
                background: #f5f5f5;
                font-family: sans-serif;
            }
            .home-container {
                display: flex;
                flex-direction: column;
                gap: 32px;
                max-width: 480px;
                margin: 0 auto;
            }
            .home-btn {
                width: 100%;
                padding: 36px;
                font-size: 32px;
                font-weight: bold;
                border-radius: 20px;
                border: none;
                background: #2d7df6;
                color: white;
            }
            .home-btn:active {
                background: #1e5ec0;
            }
        </style>
    </head>
    <body>

    <div class="home-container">

        <button class="home-btn" onclick="location.href='/distance'">
            📏 飛距離計
        </button>

        <button class="home-btn" onclick="location.href='/wind-ai'">
            🌬 風向きAI分析
        </button>

    </div>

    </body>
    </html>
    """
    return HTMLResponse(content=html)

# -------------------------
# 距離計算API
# -------------------------
@app.post("/gps/distance")
def calc_distance(data: GPSData):
    dist_m = haversine(data.lat1, data.lon1, data.lat2, data.lon2)
    dist_yd = dist_m * 1.09361
    return {
        "distance_m": dist_m,
        "distance_yd": dist_yd
    }

# -------------------------
# 風向き・風速 API（JMA 風タイル PNG）
# -------------------------
class WindRequest(BaseModel):
    lat: float
    lon: float

# 緯度経度 → タイル座標
def latlon_to_tile(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile

# タイル内ピクセル位置
def latlon_to_pixel(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n * 256
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n * 256
    return int(x % 256), int(y % 256)

# RGB → 風速（JMA 色凡例）
def rgb_to_wind(rgb):
    r, g, b = rgb

    if b > 200: return 3      # 青 0–5
    if g > 200: return 8      # 緑 5–10
    if r > 200 and g > 200: return 13  # 黄 10–15
    if r > 200 and g < 100: return 18  # 赤 15–20
    if r > 200 and b > 200: return 23  # 紫 20–25
    if r > 200 and g > 200 and b > 200: return 28  # 白 25+

    return 0

@app.post("/wind-jma-image")
def wind_jma_image(data: WindRequest):
    zoom = 10

    # タイル座標
    xtile, ytile = latlon_to_tile(data.lat, data.lon, zoom)
    px, py = latlon_to_pixel(data.lat, data.lon, zoom)

    # まずは固定URLでテスト（後で最新時刻に差し替え）
    url = f"https://www.jma.go.jp/bosai/jmatile/data/wind/rasrf/202405090600/{zoom}/{xtile}/{ytile}.png"

    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    return StreamingResponse(BytesIO(resp.content), media_type="image/png")

@app.post("/wind-jma")
def wind_jma(data: WindRequest):
    zoom = 10

    # 最新時刻を取得
    latest_url = "https://www.jma.go.jp/bosai/jmatile/data/wind/rasrf/latest_time.json"
    latest = requests.get(latest_url).json()
    latest_time = latest["time"]  # "202405090610" のような文字列

    # タイル座標
    xtile, ytile = latlon_to_tile(data.lat, data.lon, zoom)
    px, py = latlon_to_pixel(data.lat, data.lon, zoom)

    # 正しいタイル URL
    url = f"https://www.jma.go.jp/bosai/jmatile/data/wind/rasrf/{latest_time}/{zoom}/{xtile}/{ytile}.png"

    resp = requests.get(url, timeout=10)
    resp.raise_for_status()

    img = Image.open(BytesIO(resp.content))
    rgb = img.getpixel((px, py))

    wind_speed = rgb_to_wind(rgb)

    return {
        "wind_speed": wind_speed,
        "rgb": rgb,
        "tile": url
    }

# -------------------------
# ショット方向（1m歩行方式）
# -------------------------
class ShotDirectionRequest(BaseModel):
    lat1: float
    lon1: float
    lat2: float
    lon2: float


@app.post("/shot-direction")
def shot_direction(data: ShotDirectionRequest):

    lat1 = math.radians(data.lat1)
    lat2 = math.radians(data.lat2)
    dlon = math.radians(data.lon2 - data.lon1)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)

    bearing = math.degrees(math.atan2(x, y))
    bearing = (bearing + 360) % 360   # 0〜360° に正規化

    return {
        "shot_direction": bearing
    }

@app.get("/wind-map", response_class=HTMLResponse)
def wind_map_page():
    return """
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.js"></script>
        <link href="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.css" rel="stylesheet" />
        <style>
            body { margin:0; padding:0; }
            #map { width:100%; height:100vh; }
        </style>
    </head>
    <body>
        <div id="map"></div>

        <script>
            async function getLatestTime() {
                const html = await fetch("https://www.jma.go.jp/bosai/jmatile/data/wind/rasrf/")
                    .then(r => r.text());

                const matches = [...html.matchAll(/(\\d{12})\\//g)];
                const times = matches.map(m => m[1]);
                return times.length ? times.sort().pop() : null;
            }

            async function initMap() {
                const latest = await getLatestTime();
                if (!latest) {
                    alert("最新時刻が取得できませんでした");
                    return;
                }

                const map = new maplibregl.Map({
                    container: "map",
                    style: {
                        version: 8,
                        sources: {
                            wind: {
                                type: "raster",
                                tiles: [
                                    `https://www.jma.go.jp/bosai/jmatile/data/wind/rasrf/${latest}/{z}/{x}/{y}.png`
                                ],
                                tileSize: 256,
                                attribution: "© JMA"
                            }
                        },
                        layers: [
                            {
                                id: "wind-layer",
                                type: "raster",
                                source: "wind",
                                minzoom: 3,
                                maxzoom: 10
                            }
                        ]
                    },
                    center: [140.47, 36.37],
                    zoom: 7
                });
            }

            initMap();
        </script>
    </body>
    </html>
    """

# -------------------------
# UI（HTML + JavaScript）
# -------------------------
@app.get("/distance", response_class=HTMLResponse)
def distance_page():
    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>飛距離計</title>

        <style>
            body {
                font-family: sans-serif;
                padding: 20px;
                background: #f5f5f5;
                margin: 0;
            }
            h2 {
                text-align: center;
                font-size: 32px;
                margin-bottom: 20px;
            }
            .top-btn {
                width: 100%;
                padding: 20px;
                font-size: 26px;
                border-radius: 14px;
                border: none;
                background: #444;
                color: white;
                margin-bottom: 20px;
            }
            button {
                width: 100%;
                padding: 26px;
                margin-top: 16px;
                font-size: 30px;
                border-radius: 16px;
                border: none;
                background: #0078d4;
                color: white;
            }
            button:active {
                background: #005a9e;
            }
            .info-box {
                margin-top: 10px;
                padding: 20px;
                background: white;
                border-radius: 12px;
                font-size: 26px;
                border: 2px solid #ccc;
            }
            #distanceResult {
                font-size: 60px;
                font-weight: bold;
                text-align: center;
                margin-top: 30px;
                text-shadow: 1px 1px 3px #aaa;
            }
            #voiceStatus {
                margin-top: 20px;
                font-size: 28px;
                color: #444;
                text-align: center;
            }

            /* 画面下に固定するGPS精度バー */
            #gpsAccuracyBar {
                position: fixed;
                bottom: 0;
                left: 0;
                width: 100%;
                background: #222;
                color: #fff;
                text-align: center;
                padding: 20px 0;
                font-size: 30px;
                z-index: 9999;
            }
        </style>
    </head>

    <body>

    <button class="top-btn" onclick="location.href='/'">← ホームに戻る</button>

    <h2>📏 飛距離計</h2>

    <button onclick="recordA()">地点A（ショット地点）を記録</button>
    <div id="posA" class="info-box">未記録</div>

    <button onclick="recordB()">地点B（ボール地点）を記録</button>
    <div id="posB" class="info-box">未記録</div>

    <button onclick="calcDistance()">距離を計算</button>

    <div id="distanceResult"></div>

    <button onclick="startVoice()">🎤 音声操作スタート</button>
    <div id="voiceStatus">音声操作は停止中</div>

    <!-- GPS精度バー -->
    <div id="gpsAccuracyBar">GPS精度：計測中…</div>

    <script>
    let pointA = null;
    let pointB = null;

    // 高精度GPS取得（2回測定＋1秒待機＋平均＋精度表示）
    function getGPS(callback) {
        document.getElementById("distanceResult").innerText = "GPS取得中…";
        document.getElementById("gpsAccuracyBar").innerText = "GPS精度：計測中…";

        navigator.geolocation.getCurrentPosition(
            (pos1) => {

                setTimeout(() => {
                    navigator.geolocation.getCurrentPosition(
                        (pos2) => {

                            const lat = (pos1.coords.latitude + pos2.coords.latitude) / 2;
                            const lon = (pos1.coords.longitude + pos2.coords.longitude) / 2;

                            const acc = (pos1.coords.accuracy + pos2.coords.accuracy) / 2;

                            document.getElementById("gpsAccuracyBar").innerText =
                                `GPS精度：±${acc.toFixed(1)} m`;

                            callback({ lat, lon });
                            document.getElementById("distanceResult").innerText = "";

                        },
                        (err) => {
                            alert("2回目のGPS取得に失敗しました: " + err.message);
                            document.getElementById("distanceResult").innerText = "";
                            document.getElementById("gpsAccuracyBar").innerText = "GPS精度：取得失敗";
                        },
                        { enableHighAccuracy: true }
                    );
                }, 1000);

            },
            (err) => {
                alert("1回目のGPS取得に失敗しました: " + err.message);
                document.getElementById("distanceResult").innerText = "";
                document.getElementById("gpsAccuracyBar").innerText = "GPS精度：取得失敗";
            },
            { enableHighAccuracy: true }
        );
    }

    // A地点記録
    function recordA() {
        getGPS((p) => {
            pointA = p;
            document.getElementById("posA").innerText =
                `A地点: ${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`;
        });
    }

    // B地点記録
    function recordB() {
        getGPS((p) => {
            pointB = p;
            document.getElementById("posB").innerText =
                `B地点: ${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`;
        });
    }

    // 距離計算API呼び出し
    function calcDistance() {
        if (!pointA || !pointB) {
            alert("A地点とB地点を記録してください");
            return;
        }

        document.getElementById("distanceResult").innerText = "計算中…";

        fetch("/gps/distance", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                lat1: pointA.lat,
                lon1: pointA.lon,
                lat2: pointB.lat,
                lon2: pointB.lon
            })
        })
        .then(res => res.json())

        .then(data => {
            const yards = data.distance_yd;
            document.getElementById("distanceResult").innerText =
                `飛距離：${yards.toFixed(1)} yd`;

            const utter = new SpeechSynthesisUtterance(`飛距離 ${yards.toFixed(0)} ヤードです`);
            utter.lang = "ja-JP";
            speechSynthesis.speak(utter);
        });
    }

    // 音声操作
    function startVoice() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            alert("このブラウザは音声認識に対応していません");
            return;
        }

        const recognition = new SpeechRecognition();
        recognition.lang = "ja-JP";
        recognition.continuous = true;

        recognition.onstart = () => {
            document.getElementById("voiceStatus").innerText = "🎤 音声認識中…";
        };

        recognition.onresult = (event) => {
            const text = event.results[event.results.length - 1][0].transcript;
            document.getElementById("voiceStatus").innerText = "認識: " + text;

            if (text.includes("A")) recordA();
            if (text.includes("B")) recordB();
            if (text.includes("距離")) calcDistance();
        };

        recognition.onerror = (e) => {
            document.getElementById("voiceStatus").innerText = "音声認識エラー: " + e.error;
        };

        recognition.start();
    }
    </script>

    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/wind-ai", response_class=HTMLResponse)
def wind_ai_page():
    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>風向きAI分析</title>

        <!-- MapLibre -->
        <script src="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.js"></script>
        <link href="https://unpkg.com/maplibre-gl@2.4.0/dist/maplibre-gl.css" rel="stylesheet" />

        <style>
            body {
                font-family: sans-serif;
                padding: 20px;
                background: #f5f5f5;
                margin: 0;
            }
            h2 {
                text-align: center;
                font-size: 32px;
                margin-bottom: 20px;
            }
            .top-btn {
                width: 100%;
                padding: 20px;
                font-size: 26px;
                border-radius: 14px;
                border: none;
                background: #444;
                color: white;
                margin-bottom: 20px;
            }
            #windMap {
                width: 100%;
                height: 300px;
                border-radius: 12px;
                overflow: hidden;
                border: 2px solid #ccc;
            }
            .info-box {
                margin-top: 20px;
                padding: 20px;
                background: white;
                border-radius: 12px;
                font-size: 26px;
                border: 2px solid #ccc;
            }
            button {
                width: 100%;
                padding: 26px;
                margin-top: 16px;
                font-size: 30px;
                border-radius: 16px;
                border: none;
                background: #0078d4;
                color: white;
            }
            button:active {
                background: #005a9e;
            }
        </style>
    </head>

    <body>

    <button class="top-btn" onclick="location.href='/'">← ホームに戻る</button>

    <h2>🌬 風向きAI分析</h2>

    <!-- API が返した PNG を表示 -->
    <img id="windTile" style="width:100%;border:2px solid #ccc;border-radius:12px;">

    <!-- 最新風データ（数値） -->
    <div id="windInfo" class="info-box">風データ取得中…</div>

    <!-- ショット方向 -->
    <button onclick="startShotDirection()">ショット方向を計測（1m歩行）</button>
    <div id="shotDirectionResult" class="info-box">未計測</div>

    <!-- 風 × ショット方向 -->
    <div id="windShotResult" class="info-box">風とショット方向の関係：未計算</div>

    <script>

        // -----------------------------
        // API の PNG を表示
        // -----------------------------
        navigator.geolocation.getCurrentPosition(async (pos) => {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;

            // PNG を返す API をそのまま img にセット
            const url = `/wind-jma-image?lat=${lat}&lon=${lon}`;
            document.getElementById("windTile").src = url;

            // 風速・風向き（数値）も取得
            const res = await fetch("/wind-jma", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ lat, lon })
            });

            const data = await res.json();

            document.getElementById("windInfo").innerText =
                `最新風データ\n風速：${data.wind_speed} m/s\n風向：${data.wind_direction}°`;
        });

        // -----------------------------
        // ショット方向（1m歩行方式）
        // -----------------------------
        let shotA = null;

        function startShotDirection() {
            document.getElementById("shotDirectionResult").innerText = "A地点取得中…";

            navigator.geolocation.getCurrentPosition((pos) => {
                shotA = {
                    lat: pos.coords.latitude,
                    lon: pos.coords.longitude
                };

                document.getElementById("shotDirectionResult").innerText =
                    "A地点取得 → グリーン方向に1m歩いてください…";

                watchPositionForShot();
            });
        }

        function watchPositionForShot() {
            const watchId = navigator.geolocation.watchPosition(
                (pos) => {
                    const lat = pos.coords.latitude;
                    const lon = pos.coords.longitude;

                    const dist = calcHaversine(shotA.lat, shotA.lon, lat, lon);

                    if (dist >= 1.0) {
                        navigator.geolocation.clearWatch(watchId);

                        fetch("/shot-direction", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                lat1: shotA.lat,
                                lon1: shotA.lon,
                                lat2: lat,
                                lon2: lon
                            })
                        })
                        .then(res => res.json())
                        .then(data => {
                            const dir = data.shot_direction;

                            document.getElementById("shotDirectionResult").innerText =
                                `ショット方向：${dir.toFixed(1)}°`;

                            // 風データを取得して角度差を計算
                            fetch("/wind-jma", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ lat: shotA.lat, lon: shotA.lon })
                            })
                            .then(res => res.json())
                            .then(wind => {
                                const windDir = wind.wind_direction;

                                const effect = calcWindEffect(windDir, dir);

                                document.getElementById("windShotResult").innerText =
                                    `風向き：${windDir}°\nショット方向：${dir.toFixed(1)}°\n→ ${effect}`;

                                const utter = new SpeechSynthesisUtterance(
                                    `風は ${effect} です`
                                );
                                utter.lang = "ja-JP";
                                speechSynthesis.speak(utter);
                            });
                        });
                    }
                },
                (err) => {
                    alert("ショット方向のGPS取得に失敗: " + err.message);
                },
                { enableHighAccuracy: true }
            );
        }

        // -----------------------------
        // 風 × ショット方向 → フォロー/アゲインスト判定
        // -----------------------------
        function calcWindEffect(windDir, shotDir) {
            let diff = Math.abs(windDir - shotDir);
            if (diff > 180) diff = 360 - diff;

            if (diff <= 20) return "完全フォロー（追い風）";
            if (diff <= 60) return "ややフォロー";
            if (diff <= 120) return "横風";
            if (diff <= 160) return "ややアゲインスト（向かい風）";
            return "完全アゲインスト（向かい風）";
        }

        // -----------------------------
        // 距離計算（ハバーサイン）
        // -----------------------------
        function calcHaversine(lat1, lon1, lat2, lon2) {
            const R = 6371000;
            const toRad = (x) => x * Math.PI / 180;

            const dLat = toRad(lat2 - lat1);
            const dLon = toRad(lon2 - lon1);

            const a =
                Math.sin(dLat/2)**2 +
                Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
                Math.sin(dLon/2)**2;

            return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        }

    </script>

    </body>
   
    </html>
    """
    return HTMLResponse(content=html)
