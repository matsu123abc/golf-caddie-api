from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import math

from fastapi import File, UploadFile, Form
from azure.storage.blob import BlobServiceClient
import os

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

        <button class="home-btn" onclick="location.href='/course'">
            コースナビ
        </button>
    </div>

    </body>
    </html>
    """
    return HTMLResponse(content=html)


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
# コースナビAPI
# -------------------------
@app.get("/course", response_class=HTMLResponse)
def course_list():
    # ★ まずは固定のダミーコース一覧（後で Blob 連携に置き換える）
    courses = [
        {"id": "course1", "name": "内原カントリー倶楽部"},
        {"id": "course2", "name": "笠間カントリークラブ"},
        {"id": "course3", "name": "白帆カントリークラブ"},
    ]

    html = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>コース一覧</title>
        <style>
            body {
                margin: 0;
                padding: 24px;
                background: #f5f5f5;
                font-family: sans-serif;
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
            .course-btn {
                width: 100%;
                padding: 32px;
                margin-top: 16px;
                font-size: 30px;
                border-radius: 16px;
                border: none;
                background: #2d7df6;
                color: white;
            }
            .course-btn:active {
                background: #1e5ec0;
            }
        </style>
    </head>

    <body>

    <button class="top-btn" onclick="location.href='/'">← ホームに戻る</button>

    <h2>⛳ コース一覧</h2>

    <div id="courseList">
    """

    # Python でコース一覧を HTML に埋め込む
    for c in courses:
        html += f"""
        <button class="course-btn" onclick="location.href='/course/{c['id']}'">
            {c['name']}
        </button>
        """

    html += """
    </div>

    </body>
    </html>
    """

    return HTMLResponse(content=html)

@app.get("/course/{course_id}", response_class=HTMLResponse)
def hole_select(course_id: str):
    html = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ホール選択</title>

        <style>
            body {{
                margin: 0;
                padding: 24px;
                background: #f5f5f5;
                font-family: sans-serif;
            }}
            h2 {{
                text-align: center;
                font-size: 32px;
                margin-bottom: 20px;
            }}
            .top-btn {{
                width: 100%;
                padding: 20px;
                font-size: 26px;
                border-radius: 14px;
                border: none;
                background: #444;
                color: white;
                margin-bottom: 20px;
            }}
            .hole-grid {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 16px;
                max-width: 480px;
                margin: 0 auto;
            }}
            .hole-btn {{
                padding: 32px 0;
                font-size: 30px;
                font-weight: bold;
                border-radius: 16px;
                border: none;
                background: #2d7df6;
                color: white;
            }}
            .hole-btn:active {{
                background: #1e5ec0;
            }}
        </style>
    </head>

    <body>

    <button class="top-btn" onclick="location.href='/course'">← コース一覧に戻る</button>

    <h2>ホール選択</h2>

    <div class="hole-grid">
    """

    # 1〜18H のボタンを生成
    for hole in range(1, 19):
        html += f"""
        <button class="hole-btn" onclick="location.href='/course/{course_id}/{hole}'">
            {hole}H
        </button>
        """

    html += """
    </div>

    </body>
    </html>
    """

    return HTMLResponse(content=html)

@app.get("/course/uchihara/{hole}", response_class=HTMLResponse)
def show_course_map(hole: int):
    # Blob に保存されているファイル名
    blob_name = f"uchihara_{hole}H.png"  # PNG 前提（必要なら JPG に変更）

    # ストレージアカウント名（章さんの環境に合わせて変更）
    account_name = "pcbdiagnosisrga8a5"

    # 公開アクセス（Blob）を前提とした URL
    image_url = f"https://{account_name}.blob.core.windows.net/course-maps/{blob_name}"

    html = f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>コースマップ {hole}H</title>

        <style>
            body {{
                margin: 0;
                padding: 0;
                background: #000;
                color: white;
                font-family: sans-serif;
                text-align: center;
            }}
            .top-btn {{
                width: 100%;
                padding: 20px;
                font-size: 26px;
                border: none;
                background: #444;
                color: white;
            }}
            img {{
                width: 100%;
                height: auto;
                margin-top: 10px;
            }}
        </style>
    </head>

    <body>

    <button class="top-btn" onclick="location.href='/course/uchihara'">← ホール選択に戻る</button>

    <h2 style="font-size: 32px; margin: 10px 0;">{hole}H コースマップ</h2>

    <img src="{image_url}" alt="Course Map">

    </body>
    </html>
    """

    return HTMLResponse(content=html)
