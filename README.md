# TriWords v0.2 — 升級指南（GitHub + Vercel + Turso + Gemini）

這是一份以 **TriWords v0.1 + 先前 Vercel 500 修正 + Gemini 503 修正** 為基礎的完整可部署版本。只需保留現有的 GitHub Repository、Vercel Project、Turso Database；不要建立新的 Turso 資料庫。

## v0.2 新增功能

- **永久防重複**：`term_registry` 以語言＋正規化詞形為唯一鍵，涵蓋每日詞、自訂詞、待生成、已認識，以及編輯前的舊詞形。每天產詞在本地比對完整歷史，再由 Turso 唯一鍵守住寫入。正規化包括大小寫、全形／半形與多餘空白；**不會保證辨認所有同義詞、日語異體寫法或西文變位**。
- **熟習指數 0–100%**：由已評分次數（連續成功數）、複習間隔、難易系數及逾期天數計算的啟發式指標；不是科學校準的記憶保持概率。尚未複習的新詞為 0%；自行標記「已認識」顯示 100%。
- **我的生字**：可選英、日、西三語；自行輸入詞義／雙語例句後直接進入複習，或只先輸入生字及上下文、儲存為 `pending`，稍後手動按「Gemini 補全」。
- **AI 批次生成**：每次固定取**最早的最多 5 個待生成詞**，一次 Gemini 請求（可混合三語），不提供自動排程。只有結果格式、詞 ID、原詞、語言全數驗證通過才一次寫入。若遇 503 或輸出格式有問題，整批仍停留在待生成。
- **編輯／已認識／重新生成**：每個詞都可編輯詞義、原文、讀音、例句等；可退回待生成（重設複習進度、保留複習歷史），或標為已認識（不再排程或被每日 AI 重新選入）；可在詞庫篩選已認識。

## 升級前：備份

**強烈建議先在 Turso 介面匯出／建立可用備份**，再更新程式。這一版會第一次連線到 Turso 時執行 `ALTER TABLE` 和建立索引，並不刪除原本的詞彙、收藏或複習紀錄。若舊資料中存在「英文大小寫不同但正規化後相同」的不同 ID，為避免誤刪複習紀錄，遷移會報錯而不自動合併；需先處理衝突。

**不要先刪除任何資料表，不要重新 seed 示範詞庫到 Turso，也不要在正式資料庫執行 `seed_demo.py`。**

## 1. 將 v0.2 覆蓋至現有 GitHub Repository

解壓完整 ZIP，將 `triwords-v02/` 裡的檔案**內容**複製到現有 Repository 的根目錄（不是增加一層 `triwords-v02` 子資料夾）。你也可以使用另一份 `triwords-v02-updated-files.zip`，只包含本次變動的檔案。建議使用 GitHub Desktop，避免網頁上傳 `.github/` 隱藏資料夾出現 `This file is hidden`。

必要更新：

```
app.py
 db.py
 generate_daily.py
 seed_demo.py
 requirements.txt
 pyproject.toml
 public/index.html
 public/app.js
 public/app.css
 public/static/app.js
 public/static/app.css
 .github/workflows/daily-vocabulary.yml
```

請特別保留原先修復 Vercel 啟動問題時新增的 `public/static/` 檔案。新版 `public/index.html` 會讀取 `/static/app.js?v=02` 和 `/static/app.css?v=02`，因此**必須同時更新 `public/static` 下的 JS 和 CSS**，否則前端可能仍執行舊版。

然後按 GitHub Desktop 的 **Commit to main** → **Push origin**。Vercel 會自動觸發新的部署。

## 2. Vercel 環境變數

到 **Vercel → triwords → Settings → Environment Variables**，確認 *Production* 環境已有：

| 變數 | 用途 |
|---|---|
| `APP_PASSWORD` | 你的登入密碼，至少12字元 |
| `SESSION_SECRET` | 隨機字串，至少32字元 |
| `APP_TIMEZONE` | 預設 `Asia/Hong_Kong` |
| `TURSO_DATABASE_URL` | 現有 Turso 資料庫 URL |
| `TURSO_AUTH_TOKEN` | 現有 Turso token |
| `TURSO_DRIVER` | 跟之前成功使用的 `turso` 或 `libsql` 一致 |
| **`GEMINI_API_KEY`** | **新增：網頁手動補全需要；與 GitHub Secrets 可使用同一 Key** |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite`（若你的 AI Studio 顯示可用） |

**不要把真正的 API Key 或密碼上傳到 GitHub。** `.env.example` 只是示範檔案。

若新增了 `GEMINI_API_KEY`，**必須重新 Redeploy**，才會套用到新部署。GitHub Actions Secrets 是另一個環境：即使每日詞生成成功，也不代表 Vercel 已取得 Gemini Key。

`requirements.txt` 與 `pyproject.toml` 已加入 `google-genai`，供 Vercel 的 Python API 手動補全使用。GitHub Actions 依然沿用 `requirements-generator.txt`，每日30詞腳本有自己的環境變數。

## 3. 自動升級 Turso（不刪舊資料）

在新版部署完成後，開啟網站、登入、點擊「詞庫」或「我的生字」。首次讀取資料的 API 會執行 `db.init_db()`：

1. 保留舊有 `vocabulary`、`daily_lessons`、`review_progress`、`review_history`、`bookmarks`。
2. 為 `vocabulary` 新增 `source`、`status`、`normalized_term`、`context_sentence`、`known_at`、`updated_at`。
3. 建立 `term_registry`，把**所有舊詞**加進永久排除清單。
4. 建立唯一索引，阻止相同語言、相同正規化詞形重覆寫入。
5. 記錄 schema_version=2，之後的部署不需要再次全庫回填。

若出現資料庫錯誤，請在 Vercel Runtime Logs 查看 Traceback；不要清空資料表嘗試修復。

## 4. 在手機測試功能

1. **新增手動詞**：進入「生字」→ 選語言、輸入單字、選「自行填寫」→ 填中文釋義等 → 儲存。它會立即進入「複習」頁。
2. **新增待 AI 補全**：進入「生字」→ 選「AI 補全」，只輸入原詞（可附原句）→ 儲存；待處理清單會新增一項，**不會自動向 Gemini 發送請求**。
3. **手動生成前五詞**：累積幾個後，點「用 Gemini 補全前 N 詞」（N≤5）。生成成功後移入「詞庫 → 學習中」，同時排入「複習」。可以只提交1個，也可以提交5個。遇503時會保留待處理詞。
4. **編輯**：在今日／複習單字卡或詞庫按「編輯」。修改詞義等後儲存。編輯前的舊詞形仍會記入永久排除清單。
5. **退回待生成**：在編輯視窗選「重新加入待生成」。它暫時不再參加複習，原有 `review_progress` 重設但 `review_history` 不刪。待 AI 補全後可重新學習。
6. **標記已認識**：在編輯視窗選「標記為已認識」，它從正常學習及待複習中退出。到「詞庫」的狀態選單切換為「已認識」便能找到它。
7. **檢查永久去重**：試著再次輸入同語言已存在的單字（包括大小寫差別），應收到409提示而不會產生第二筆。
8. **熟習指數**：在「複習」評分後，單字卡和詞庫會顯示新的百分比；它不是記憶概率。

## 5. GitHub Actions 每日30詞

新版 `generate_daily.py` 會查詢 **Turso 全歷史保留詞形**，而非舊版僅檢查最近400詞。AI 仍只收到精簡的最近180個詞作提示；Python 對完整保留集合過濾，並在不足10個時最多再生成5輪候選。資料庫唯一鍵提供最後一道保護。

「已認識」、「手動新增」、「待補全」以及「改名之前的拼法」都會在全歷史排除清單內。GitHub Action 重新執行時已有10個的語言會跳過；若出現 Gemini 503，沿用有限次重試。

## 6. 疑難排解

| 症狀 | 原因與處理 |
|---|---|
| 頁面仍是舊版 | 確認 `public/static/app.js`、`public/static/app.css` 有一起上傳，並在 Vercel 最新 Production Deploy 部署成功；手機重新載入 |
| 點生成出現「Vercel 尚未設定 GEMINI_API_KEY」 | 到 Vercel 的 **Production** 環境變數新增並 Redeploy |
| 503 Gemini 暫時過載 | 請稍後再按生成；待補全單字會保留，不會扣掉你的待生成記錄 |
| 409 詞彙已存在 | 這是預期防重複功能；請在詞庫搜尋原詞，而不是重複新增 |
| 500 或 RuntimeError | 到 Vercel Runtime Logs 查看；不要直接刪除資料庫 |
| 舊詞衝突導致遷移中止 | 正規化後有不同 ID 重複；先備份，再依錯誤訊息人工檢視，避免遺失複習歷史 |

## 開發與測試

建議 Python 3.12：

```bash
pip install -r requirements-generator.txt
python seed_demo.py
python -m unittest discover -s tests -v
uvicorn app:app --reload
```

本地示範需要設定 `APP_PASSWORD`（≥12字元）和 `SESSION_SECRET`（≥32字元），不會連接正式 Turso，除非你自行設定了 Turso 環境變數。

**驗證範圍**：本專案在交付前通過 Python 11項自動測試及前端 JavaScript 語法檢查。未在你的 Vercel/Turso/Gemini 正式帳戶執行整合測試；也未完成可運行的真實瀏覽器自動化點擊測試。部署後請按第4節手動檢查。

**注意回退**：升級後，**不要僅把每日生成腳本回退至 v0.1**，因為新唯一索引和資料表已生效。若必須回退，應保留新版資料庫寫入層和新版產詞腳本，或由升級前的資料庫備份完整還原。
