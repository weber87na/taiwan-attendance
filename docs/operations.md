# 安全與維運

## 執行模式

本版是單公司、本機優先參考實作，使用 Python 標準函式庫 HTTP 伺服器與 SQLite。預設只監聽 `127.0.0.1`。小規模內部評估可由原始碼啟動；正式大量連線應先做容量與部署評估，改用具資源限制的應用服務配置。

無預設帳密。管理員透過 `python -m attendance init` 建立。密碼需至少12字元，雜湊儲存；登入 session 原始token只存在 HttpOnly cookie，伺服器儲存雜湊。變更操作要求 CSRF token，拒絕未知 Host 與跨來源 Origin，前端不載入第三方資源。

## HTTPS 反向代理

例如公開名稱為 `attendance.example.com`：

```sh
python -m attendance serve --host 127.0.0.1 --port 8000 --public-origin https://attendance.example.com --secure-cookie
```

代理需保留 `Host: attendance.example.com`，限制請求大小、連線數、速率與閒置時間。對外僅開 HTTPS，不直接暴露後端連接埠。不要將 `--secure-cookie` 用於一般 HTTP 測試，瀏覽器不會送出 Secure cookie。

## 資料與權限

- 資料庫包含員工姓名、薪資、出勤與請假內容。只讓應用程式及必要管理人員讀取。
- Linux啟動指令會套用限制性umask；Windows應另外設定資料夾ACL與磁碟加密。
- 管理員／主管可查詢管理資料，員工只可查自己的出勤。這是基本角色分權，尚未有部門邊界與欄位級權限。
- 不蒐集GPS、身分證字號、臉部特徵或健保卡號；不要在原因欄填不必要的健康細節。
- 不提供刪除原始出勤的介面。資料庫管理者仍有技術能力修改SQLite，本版的稽核表不是外部防竄改證據。
- 核准加班與實際出勤分開記錄；勞務已提供時的工資認定不得只以申請狀態判斷。

## 備份與復原

一致性備份：

```sh
python -m attendance backup backups/attendance-2026-09-16.sqlite3
```

指令使用SQLite備份API，禁止覆蓋既有檔案。備份包含全部個資，應加密、存放在受控位置且定期測試復原。正式安排可由作業系統排程執行並檢查回傳碼。

復原時先停止伺服器，保留目前資料庫與伴隨的WAL／SHM檔，將備份放到**新路徑**後執行：

```sh
python -m attendance --db runtime/restored.sqlite3 serve
```

先確認帳號、月報、班表與申請完整，再決定切換。勿在服務運作時單獨覆蓋SQLite主檔。

## 保存與年度更新

勞基法出勤紀錄應逐日記載至分鐘、保存五年，並提供勞工申請副本。原始事件保留時間資訊，CSV可匯出月報；正式保存需包含資料库、備份及可辨識的核准紀錄。

2026日曆與社會保險規則只支援已驗證年度。跨到新年度前需更新官方資料、確認有效期間並跑測試。國定假日補假必須連同公司排班約定處理，不能單靠政府行事曆自動套用。

參考法規：勞動部 [勞動基準法](https://laws.mol.gov.tw/FLAW/FLAWDAT0201.aspx?id=FL014930)，第30條。查核日期2026-09-16。
