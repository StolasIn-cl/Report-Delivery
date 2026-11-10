# Report Delivery｜共用報告寄送

集中維護 Nightly PR 與 WER 報告的寄送流程，透過使用者已登入的 **Chrome Outlook Web** 發送郵件，並保存附件快照、工作佇列與寄送狀態。

報告專案決定內容與收件者；本模組負責完成寄送。`delivery.py` 使用 Python 標準函式庫，**本身不寄信，也不連線瀏覽器**；實際郵件操作由 [report-delivery skill](skill/report-delivery/SKILL.md) 指導代理執行，不使用 Graph 或其他郵件 API。

## 專案分工

| 元件 | 負責工作 |
| --- | --- |
| Nightly-PR-Report、WER-Daily-Report | 產生與驗證報告，提供寄件者、收件者、原主旨、內文與 PDF |
| `delivery.py` | 驗證寄送清單、建立附件快照、管理佇列與寄送鎖、保存狀態與證據 |
| `report-delivery` skill | 操作 Chrome Outlook、附檔、核對郵件、寄出與查證寄件備份 |
| Codex 排程 | 定時串接報告產生、共用寄送與結果同步 |

## 安裝與本機設定

需要 Python 3.11 以上，以及可供 Codex 操作、已登入 Outlook 的 Chrome 擴充功能連線。

將三個專案放在同一層目錄，於本專案複製設定範本：

```text
Desktop/
├─ Nightly-PR-Report/
├─ WER-Daily-Report/
└─ Report-Delivery/
```

```powershell
Copy-Item config.example.json config.local.json
```

將 `sender_account` 改為實際登入 Outlook 的寄件帳號。測試收件者限制仍為 `Stolas_In@cyberlink.com`，不可改用正式名單測試。

### Skill 的維護位置

| 位置 | 用途 |
| --- | --- |
| `skill/report-delivery/SKILL.md` | 唯一維護來源，包含完整寄送與恢復步驟 |
| `C:/Users/stolas_in/.codex/skills/report-delivery` | 本機全域入口，以目錄連結（junction）指向上述來源 |

因此只需修改一份 skill。新聊天可透過全域入口找到它；既有排程也明確讀取其路徑。現行 skill 含本機絕對路徑，移至其他電腦時須一併調整。

## 寄送流程

1. 報告專案產生 `delivery-manifest.json`，提供完整郵件與附件資訊。
2. 共用模組驗證清單並保存附件快照；相同報告日期不因重新產生內容就允許重寄。
3. 代理取得共用寄送鎖後，依 skill 操作 Chrome Outlook。
4. 核對寄件者、完整收件地址、主旨、內文與附件；先記錄寄送意圖，再按一次「傳送」。
5. 開啟寄件備份，核對該次郵件與附件後，才記錄為 `sent`。
6. 報告專案依確認結果同步自己的狀態，再繼續處理佇列中的工作。

同一時間只允許一個工作操作 Outlook。不能僅憑編輯視窗關閉就宣告成功；可能已寄出的工作只能查證，不能直接再寄。

### 常用指令

以下指令只操作本機紀錄，不會自行寄信。所有結果以 JSON 輸出。

```powershell
# 查看完整參數
python delivery.py --help

# 查看工作佇列
python delivery.py list

# 提交報告專案產生的寄送清單
python delivery.py submit C:/path/to/delivery-manifest.json

# 驗證指定工作的附件快照
python delivery.py verify JOB_ID
```

| 指令 | 用途 |
| --- | --- |
| `claim` | 取得下一個工作與寄送鎖 |
| `transition` | 依允許的順序與證據更新寄送階段 |
| `recover` | 確認原執行者停止後，處理中斷狀態 |
| `reserve`、`release` | 取得或釋放恢復調查專用的寄送鎖 |
| `requeue` | 確認尚未寄出及草稿處置後，重新排隊 |
| `reconcile` | 以寄件備份證據確認不明的寄送結果 |
| `escalate` | 記錄一次 Sol 6.1 診斷需求 |
| `import-legacy` | 匯入舊寄送紀錄，保留防重寄保護 |

恢復指令涉及工作擁有者與鎖定權杖，請依 [完整 skill 流程](skill/report-delivery/SKILL.md) 執行。

## 排程與故障處理

| 報告 | 觸發時間（台灣時間） |
| --- | --- |
| WER | 每日 08:00 |
| Nightly PR | 週二至週六 09:00 |

兩個既有排程各自組合報告與寄送；時間為觸發時間，不保證當下送達。

Luna 6 xhigh 依 skill 完成有限次數的本機排查後，若仍無法解決**寄送層問題**，須委派 `gpt-6.1-sol` 分析，再嘗試一次有根據的恢復。Sol 提供診斷，由原代理執行修復，避免兩個代理同時操作瀏覽器。

資料擷取、日期、報告內容或 PDF 驗證錯誤則停止，不為了寄出而改用舊報告。登入、實際工具審核與政策拒絕仍須遵守。

## 本機資料與備份

| 路徑 | 內容 |
| --- | --- |
| `config.local.json` | 本機寄件帳號設定 |
| `state/delivery.sqlite3` | 寄送狀態的權威紀錄、工作擁有權與事件紀錄 |
| `state/spool/ID/` | 不可變的寄送清單與 PDF 快照 |
| `evidence/` | 代理實際觀察到的寄送證據 |
| `backups/2026-11-10/` | 本次整合前的本機檔案與排程備份 |

上述資料不納入 Git。**換機或重新安裝時須另外保留紀錄**，不可只重新 clone 就視為從未寄送。不要為了解鎖而直接刪除狀態、鎖或附件快照；恢復前須確認舊執行者已停止，並查明其草稿與寄送結果。

舊紀錄中已確認寄出的日期匯入為 `sent`；`sending`、`preparing`、`send_unknown` 匯入為待查證狀態。舊證據可能較不完整，仍保留防重寄保護；沒有紀錄的歷史日期不會自動補寄。

若需還原舊流程，從備份恢復報告專案檔案，並透過 Codex 自動化工具還原排程。共用寄送紀錄應保留，避免重複寄送。

## 驗證與使用限制

```powershell
python -m unittest discover -s tests -v
```

實測與審查結果見 [VALIDATION.md](VALIDATION.md)。測試郵件使用 `make_test.py` 建立獨立工作，**只寄給 `Stolas_In@cyberlink.com`**。

寄送結果依代理觀察到的 Outlook 證據建立。狀態機可檢查帳號、主旨、時間、收件者與附件名稱是否一致，但無法獨立證明畫面內容，或保證外部郵件系統絕對只投遞一次。寄件備份表示 Outlook 已接受郵件，不代表每位收件者都已收信；證據不足時保留不明狀態，不自動重寄。
