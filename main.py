from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import math

app = FastAPI()

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

# -------------------------
# UI（HTML + JavaScript）
# -------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <title>ゴルフ距離計</title>
        <style>
            body {
                font-family: sans-serif;
                padding: 20px;
                background: #f5f5f5;
            }
            h2 {
                text-align: center;
            }
            button {
                width: 100%;
                padding: 18px;
                margin-top: 12px;
                font-size: 20px;
                border-radius: 10px;
                border: none;
                background: #0078d4;
                color: white;
            }
            button:active {
                background: #005a9e;
            }
            .info-box {
                margin-top: 10px;
                padding: 10px;
                background: white;
                border-radius: 8px;
                font-size: 16px;
            }
            #distanceResult {
                font-size: 28px;
                font-weight: bold;
                text-align: center;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>

    <h2>📏 ゴルフ距離計（地点A/B）</h2>

    <button onclick="recordA()">地点A（ショット地点）を記録</button>
    <div id="posA" class="info-box">未記録</div>

    <button onclick="recordB()">地点B（ボール地点）を記録</button>
    <div id="posB" class="info-box">未記録</div>

    <button onclick="calcDistance()">距離を計算</button>

    <div id="distanceResult"></div>

    <script>
    let pointA = null;
    let pointB = null;

    // GPS取得
    function getGPS(callback) {
        document.getElementById("distanceResult").innerText = "GPS取得中…";

        navigator.geolocation.getCurrentPosition(
            (pos) => {
                callback({
                    lat: pos.coords.latitude,
                    lon: pos.coords.longitude
                });
                document.getElementById("distanceResult").innerText = "";
            },
            (err) => {
                alert("GPS取得に失敗しました: " + err.message);
                document.getElementById("distanceResult").innerText = "";
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
        });
    }
    </script>

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
