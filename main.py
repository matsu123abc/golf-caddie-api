from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import requests
import math

app = FastAPI()

# -----------------------------
# Wind Request
# -----------------------------
class WindRequest(BaseModel):
    lat: float
    lon: float

# -----------------------------
# Open-Meteo 風データ API
# -----------------------------
@app.post("/wind-openmeteo")
def wind_openmeteo(req: WindRequest):
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={req.lat}&longitude={req.lon}"
        f"&hourly=windspeed_10m,winddirection_10m&timezone=Asia/Tokyo"
    )

    data = requests.get(url).json()

    speed = data["hourly"]["windspeed_10m"][0]
    direction = data["hourly"]["winddirection_10m"][0]

    return {
        "wind_speed": speed,
        "wind_direction": direction
    }

# -----------------------------
# ショット方向（2点の方位角）
# -----------------------------
class ShotRequest(BaseModel):
    lat1: float
    lon1: float
    lat2: float
    lon2: float

@app.post("/shot-direction")
def shot_direction(req: ShotRequest):
    lat1 = math.radians(req.lat1)
    lon1 = math.radians(req.lon1)
    lat2 = math.radians(req.lat2)
    lon2 = math.radians(req.lon2)

    dlon = lon2 - lon1

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)

    bearing = math.degrees(math.atan2(x, y))
    bearing = (bearing + 360) % 360

    return {"shot_direction": bearing}

# -----------------------------
# UI ページ
# -----------------------------
@app.get("/wind-ai", response_class=HTMLResponse)
def wind_ai_page():
    return """
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: sans-serif; padding: 20px; }
            .info-box {
                background: #f0f0f0;
                padding: 12px;
                margin-top: 10px;
                border-radius: 8px;
            }
            button {
                padding: 12px;
                width: 100%;
                margin-top: 10px;
                font-size: 18px;
            }
        </style>
    </head>
    <body>

        <h2>🌬 風向きAI分析（Open-Meteo版）</h2>

        <div id="windInfo" class="info-box">風データ取得中…</div>

        <button onclick="startShotDirection()">ショット方向を計測（1m歩行）</button>
        <div id="shotDirectionResult" class="info-box">未計測</div>

        <div id="windShotResult" class="info-box">風とショット方向の関係：未計算</div>

        <script>
            // -----------------------------
            // Open-Meteo 風データ取得
            // -----------------------------
            navigator.geolocation.getCurrentPosition(async (pos) => {
                const lat = pos.coords.latitude;
                const lon = pos.coords.longitude;

                const res = await fetch("/wind-openmeteo", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ lat, lon })
                });

                const data = await res.json();

                document.getElementById("windInfo").innerText =
                    `風速：${data.wind_speed} m/s\\n風向：${data.wind_direction}°`;

                window.latestWind = data;
            });

            // -----------------------------
            // ショット方向（1m歩行）
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

                                const windDir = window.latestWind.wind_direction;
                                const effect = calcWindEffect(windDir, dir);

                                document.getElementById("windShotResult").innerText =
                                    `風向き：${windDir}°\\nショット方向：${dir.toFixed(1)}°\\n→ ${effect}`;

                                const utter = new SpeechSynthesisUtterance(
                                    `風は ${effect} です`
                                );
                                utter.lang = "ja-JP";
                                speechSynthesis.speak(utter);
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
