import math
import os
import json
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from fastapi import File, UploadFile, Form
from azure.storage.blob import BlobServiceClient

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
            飛距離計
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
# 風向き・風速 API（Open-Meteo）
# -------------------------
class WindRequest(BaseModel):
    lat: float
    lon: float

@app.post("/wind")
def get_wind(data: WindRequest):
    import requests

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={data.lat}&longitude={data.lon}"
        "&hourly=windspeed_10m,winddirection_10m"
        "&timezone=Asia/Tokyo"
    )

    res = requests.get(url)
    weather = res.json()

    speeds = weather["hourly"]["windspeed_10m"]
    dirs = weather["hourly"]["winddirection_10m"]
    times = weather["hourly"]["time"]

    latest = len(speeds) - 1

    return {
        "time": times[latest],
        "wind_speed": speeds[latest],       # m/s
        "wind_direction": dirs[latest]      # 0〜360°
    }

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

    async function fetchWind(lat, lon) {
        const res = await fetch("/wind", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lat, lon })
        });

        const data = await res.json();
        console.log("風速:", data.wind_speed, "m/s");
        console.log("風向き:", data.wind_direction, "°");

        return data;
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




