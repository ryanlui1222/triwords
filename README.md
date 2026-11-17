# 三語日課 TriWords — Gemini + GitHub + Vercel + Turso

**版本：v0.1，2026-11-18**  ·  Android / 電腦瀏覽器均可使用  ·  **不需要 Expo、不需要 npm、不需要推播**

這是可以在本機執行的**第一版原始碼**。以 **Python FastAPI + HTML/CSS/JavaScript** 製作網頁介面，在 Vercel 部署。每天由 GitHub Actions 呼叫 Gemini API 產生英語、日語、西班牙語各10詞，存入 Turso。首次測試內建30個人工示範詞，**不需要 API 金鑰即可於本機操作**。

**先知道限制：** 此專案尚未用你的 Turso / Gemini API / Vercel 帳戶完成實際雲端部署；需要你自行設定環境變數與金鑰。此版本需要網絡讀寫學習資料，並非離線優先 App；記憶演算法為**簡化的日粒度間隔複習**，尚非 FSRS。所有語音透過裝置的 Web Speech API 合成，並不提供真人錄音。

## 0. 專案架構與檔案

```text
triwords/
├─ app.py                   # Python FastAPI 網站與 API、單人登入
├─ db.py                    # Turso / SQLite 資料庫、記憶排程
├─ generate_daily.py        # Gemini 每日產出30詞並存入 Turso
├─ seed_demo.py             # 本機示範30詞，不會接遠端資料庫
├─ demo_words.json          # 30個示範詞
├─ public/
│  ├─ index.html            # App 畫面
│  ├─ app.css               # 手機 / 桌面響應式排版
│  ├─ app.js                # 單字卡、語音、收藏、詞庫等互動
│  └─ manifest.webmanifest  # 可加到手機主畫面
├─ .github/workflows/daily-vocabulary.yml  # 每天12:00自動產詞
├─ pyproject.toml           # Vercel Python 自動部署
├─ requirements.txt         # Python 網站運行所需套件
├─ requirements-generator.txt # GitHub 產詞另外需要 google-genai
├─ .env.example             # 環境變數範本；不會自動讀取
└─ tests/test_app.py        # 自動測試
```

## 1. 先在 Windows 電腦執行，不需要 Turso / Gemini

你需要安裝 **Python 3.12** 和 **VS Code**（或你的慣用編輯器）。下載 ZIP 並解壓，開啟 PowerShell，移至解壓的資料夾，例如：

```powershell
cd C:\Users\你的帳戶\Downloads\trilingual-vercel-mvp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

以下設定只適用於**目前這個 PowerShell 視窗**。請把示例密碼改成你自己的長密碼。`SESSION_SECRET` 須至少32個字元且不同於登入密碼：

```powershell
$env:APP_PASSWORD="my-demo-password-at-least-12"
$env:SESSION_SECRET="another-long-secret-random-string-1234567890"
$env:APP_TIMEZONE="Asia/Hong_Kong"
```

這階段不需要設定 `TURSO_DATABASE_URL` 或 `TURSO_AUTH_TOKEN`。建立30詞示範詞包，再啟動伺服器：

```powershell
.\.venv\Scripts\python.exe seed_demo.py
.\.venv\Scripts\python.exe -m uvicorn app:app --reload
```

開啟 **http://127.0.0.1:8000**，輸入上面的 `APP_PASSWORD`，就能使用。

如果在 macOS / Linux，使用 `python3 -m venv .venv`、`.venv/bin/python`，並將 PowerShell `$env:XXX=...` 改成 `export XXX=...`。

> `seed_demo.py` 會針對系統設定的 `APP_TIMEZONE` 產生**當日**示範詞包。示範詞只供測試，不會每天真正變化。要有新詞，必須連接 Gemini + Turso 並執行產詞腳本。

### 可以立即測試的功能

- 「今日」：30個示範詞、英日西語切換、逐張翻卡、記憶評分、切換日期（有對應詞包時）。
- 「複習」：根據已評分詞彙的到期日顯示；新詞今日評分後，最快翌日會出現在這裏。
- 「詞庫」：搜尋、按語言篩選、翻閱每頁100詞、收藏與只看收藏。
- 「語音」：點選「朗讀單字」及「朗讀例句」。瀏覽器須支援 Speech Synthesis；日語、西語音色取決於你的裝置和語音包。
- 「設定」：語速調整、登入和登出、Android 主畫面安裝提示。

執行自動測試（不需連接雲端）：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest httpx
.\.venv\Scripts\python.exe -m pytest -q tests
```

## 2. 建立獨立 Turso 資料庫

**建議不要使用你其他應用現有的資料庫**。同一 Turso 帳戶可以新增一個獨立 DB，例如 `triwords`。

取得：

1. `TURSO_DATABASE_URL` — Turso Dashboard 的連線網址。
2. `TURSO_AUTH_TOKEN` — 有效的資料庫授權 token。
3. `TURSO_DRIVER` — 取決於你建立的**資料庫引擎**：
   - **libSQL**（多數既有 DB）：設 `libsql`，URL 通常以 `libsql://` 開頭。
   - **新的 Turso Database 引擎**：設 `turso`，使用 `turso_serverless`，URL 以 Turso Dashboard 提供的值為準。

在本專案中，這兩種驅動都已列在 Python 依賴檔案內。**不要將密碼或 token 寫入公開程式檔**。

資料表由 `generate_daily.py` 首次執行時建立，包含：

| 資料表 | 主要內容 |
|---|---|
| `vocabulary` | 語言、單字、讀音、詞性、繁體中文釋義、雙語例句、程度、主題 |
| `daily_lessons` | 日期、語言及每天10詞的對應 |
| `review_progress` | 間隔天數、熟悉度、下一次複習日期 |
| `review_history` | 每次的評分紀錄（有去重 ID） |
| `bookmarks` | 收藏詞彙 |

## 3. 準備 Gemini 免費 API 金鑰

1. 開啟 **https://aistudio.google.com/apikey**，以自己的 Google 帳戶進入並建立 API Key。
2. 目前預設文字生成模型為 `gemini-2.5-flash-lite`。
3. 每天為英、日、西各呼叫一次 Gemini，請求每種語言15個候選詞，程式經去重及基本欄位檢查後各取10個。
4. 英語預設 C1–C2、日語 N2–N1、西班牙語 A2–B1。可自行修改 `generate_daily.py` 裏的 `LANGS` 字典與提示詞。

**重要：** 免費 API 額度、可用地區、模型名稱都可能變更；登入 AI Studio 確認你的帳戶實際免費配額。生成結果可能有讀音、翻譯、語法錯誤，初期應抽樣檢查。免費 API 的資料處理條款可能允許服務商使用輸入和輸出改進服務，不要傳送私人或敏感文字。

## 4. 建立 GitHub 私人 Repository 並自動生成

1. 前往 GitHub 新建 **Private repository**，例如 `triwords-daily`。
2. 將 ZIP 解壓後的**所有檔案和隱藏 `.github/` 資料夾**上傳。切勿上傳 `.env`、本機 SQLite `.db` 檔或任何金鑰。
3. 前往 Repository → **Settings → Secrets and variables → Actions → Secrets → New repository secret**，新增：
   - `TURSO_DATABASE_URL`
   - `TURSO_AUTH_TOKEN`
   - `GEMINI_API_KEY`
4. 在同一頁的 **Variables** 分頁設 `TURSO_DRIVER`，值為 `libsql` 或 `turso`。
5. 前往 **Actions → 每日生成三語詞彙 → Run workflow**，第一次**手動執行**，查看日誌是否顯示 `en saved 10詞`、`ja saved 10詞`、`es saved 10詞`。

`.github/workflows/daily-vocabulary.yml` 已包含排程：

```yaml
schedule:
  - cron: '0 12 * * *'
    timezone: 'Asia/Hong_Kong'
```

代表**香港時間每日中午12:00嘗試開始**，不是給手機發通知。GitHub Actions 可能延遲，也可能因額度、停用、API 配額等原因失敗。你可隨時按 `Run workflow` 補跑；已完整產生10詞的語言會自動略過，避免重複加入同日詞包。

**如果你希望以英國當地日期為準**，請把 workflow 的 `timezone` 和 `APP_TIMEZONE` 都改成 `Europe/London`（英國夏令時間會自動處理），Vercel 同樣設為 `Europe/London`。不要只改其中一處，否則頁面與產詞腳本可能認定不同的「今天」。

## 5. 部署到 Vercel（毋須 Node.js）

1. 在 Vercel 選 **Add New → Project**，Import 剛建立的 GitHub repository。這應是一個**新專案**，不必改動你其他應用的 Vercel 設定。
2. Repository Root Directory 選專案根目錄；`pyproject.toml` 的 `[tool.vercel] entrypoint = "app:app"` 指明 FastAPI 進入點。
3. 在 **Environment Variables** 加入以下值，Production 至少需要：

| Key | 用途 |
|---|---|
| `APP_PASSWORD` | 自己設定的登入密碼，**至少12字元** |
| `SESSION_SECRET` | 另一串**至少32字元**的隨機私密值 |
| `APP_TIMEZONE` | `Asia/Hong_Kong` 或 `Europe/London` |
| `TURSO_DATABASE_URL` | Turso 網址 |
| `TURSO_AUTH_TOKEN` | Turso token |
| `TURSO_DRIVER` | `libsql` 或 `turso` |

4. **不必**把 `GEMINI_API_KEY` 放到 Vercel。AI 生成只在 GitHub Actions 執行，金鑰保存在 GitHub Secrets。
5. 按 **Deploy**，完成後開啟 Vercel 提供的 HTTPS 網址。登入後應可看到已透過 GitHub Actions 生成的詞包。

如果部署後詞庫是空的，先檢查 GitHub Actions 是否成功寫入正確的 Turso 資料庫；**Vercel 和 GitHub 的 `TURSO_DATABASE_URL` 必須相同**。

若本機執行時遇到 `ModuleNotFoundError`，在同一 PowerShell 視窗重新執行 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。

## 6. Android 上使用

用 Android Chrome 開啟 Vercel HTTPS 網址，點選選單中的 **「安裝應用程式」或「加入主畫面」**（選項因 Chrome 版本而異）。日後可點主畫面圖示進入，介面會自動調整手機尺寸。

這**不是原生 APK**；其語音朗讀取決於瀏覽器和系統可用聲音。本版也**尚未實作可離線寫入並同步 Turso 的功能**，請在連網時使用。

## 7. 記憶排程 v0.1（非 FSRS）

本版記錄每個詞的評分、熟悉度係數與複習間隔。初學後，「忘記」及「困難」通常隔日再看，「記得」約1日，「容易」4日；後續視評分調整間隔。為了讓部署簡單，精確到「日期」，不處理同日數分鐘後的複習，也沒有採用 FSRS 算法。你可以在 `db.py` 的 `calculate_next()` 改動規則。每次評分會記錄一個隨機事件 ID，避免相同請求重複計數。

## 8. 安全與現階段限制

- **金鑰不在前端：** Turso token 和 Gemini Key 只能保存在 GitHub Secrets、Vercel 環境變數，不能貼到 HTML/JS 或提交 repository。
- **單人使用者：** 本版以長密碼和經 HMAC 簽署的 HttpOnly Cookie 保護學習 API。**不是完整的多人帳號系統**，亦未加入登入限速或兩步驗證。若要公開給他人使用，必須升級驗證設計。
- **不會使用本地 SQLite 作 Vercel 正式資料庫：** Vercel 環境需要提供 Turso URL；本機 SQLite 只供測試。
- **產詞檢查仍有限：** 程式驗證欄位完整和避免重複詞，但**無法保證 AI 翻譯與讀音準確**。日語讀音、詞形及西語動詞變化尤應抽查。
- **零額外費用是目標，不是保證：** Gemini 免費額度、Turso、GitHub Actions 與 Vercel Hobby 都有政策和限額。請在自己帳戶確認最新方案。
- **首次驗證：** 已在本機使用 Python TestClient 驗證登入、30詞、詞庫分頁、評分、收藏與安全檢查；未連接你的雲端帳戶進行端對端測試。

## 官方文件

- [Vercel FastAPI 部署](https://vercel.com/docs/frameworks/backend/fastapi)
- [Turso Python SDK Quickstart](https://docs.turso.tech/sdk/python/quickstart)
- [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini Python SDK](https://googleapis.github.io/python-genai/)
- [GitHub Actions 排程](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule)
- [瀏覽器朗讀 API](https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis)
