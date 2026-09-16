# 台灣出勤管理 Taiwan Attendance

繁體中文的出勤打卡系統參考實作，包含員工帳號、打卡事件、排班、假勤簽核、月報、2026 台灣假日，以及勞基法與勞健保／勞退試算。

**版本：0.1.0；規則查核日：2026-09-16。** 適用範圍是台灣一般本國全時受僱者、正常工時制度；保費是單一投保單位、全月加保試算。尚未涵蓋彈性工時、特殊身分、全套薪資結算或政府申報。各模組的適用條件與官方來源見 `docs/`。

## 快速開始

需要 Python 3.12 以上，不需安裝第三方 Python 套件。從完整原始碼目錄執行：

```powershell
git clone https://github.com/weber87na/taiwan-attendance.git
cd taiwan-attendance
python -m attendance init
python -m attendance serve
```

Windows 若 `python` 未設定好，可使用 `py -3.12` 取代。若已安裝 uv，也可以用 `uv run --python 3.12 python -m attendance init` 與 `uv run --python 3.12 python -m attendance serve`。

開啟 <http://127.0.0.1:8000>。初始化時互動輸入管理員密碼，預設帳號 `admin`，**沒有預設密碼**。管理員可以新增主管與員工，再設定班次。資料保存在 `runtime/attendance.sqlite3`，不會提交 Git。

指定資料庫或連接埠：

```powershell
python -m attendance --db runtime/company.sqlite3 init --username owner --name 管理員
python -m attendance --db runtime/company.sqlite3 serve --port 8080
```

## 使用流程

1. 管理員建立帳號：設定到職日、角色及月薪。
2. 管理員或主管建立每日班次，明確指定工作日、休息日、例假或國定假日。
3. 員工記錄上班、休息開始、休息結束、下班。時間採伺服器時間，換算台灣時區。
4. 員工送出請假、補卡或加班申請，主管檢查後核准或駁回；禁止核准自己的申請。
5. 員工檢視自己的紀錄，管理人員查詢月報並匯出 CSV。勞健保與加班費可在試算頁分別估算。

請假需要先有班次；申請的分鐘數須明確填寫，系統不會把開始至結束的整段時間一律當成工作時間。排定休息分鐘也不會直接從原始打卡紀錄扣除。

婚喪假、產假、產檢等事件型假別仍需人工核對資格、事件及請休期間，核准時須留下簽核意見。多日請假的淨分鐘會依班次順序分配到報表；需要每日精確分鐘時請逐日申請。

## 已有功能

| 模組 | 本版內容 |
| --- | --- |
| 帳號與權限 | 管理員／主管／員工、密碼雜湊、到期登入階段、修改密碼 |
| 打卡 | 四種打卡事件、重複／順序檢查、跨日紀錄、伺服器時間 |
| 排班 | 個人每日班次、休息設定、日別分類、跨日班次 |
| 假勤 | 請假／加班／補卡申請、核准／駁回、禁止自批、稽核紀錄 |
| 報表 | 個人與管理月報、原始事件、CSV 匯出、缺卡異常 |
| 台灣日曆 | 2026 國定假日、政府日曆參考、週末撞假標記、補假候選 |
| 勞基法 | 特休級距、平日／休息日／國定假日加班試算、工時提示、假別規範 |
| 社會保險 | 勞保、就保、職災、健保及勞退分項試算、各自投保級距 |
| 維運 | SQLite 備份指令、零外部前端資源、Docker、Windows/Linux 測試工作流程 |

完整功能盤點與尚未完成項目在 [docs/features.md](docs/features.md)。

## 台灣規則的重要區分

- **行政機關辦公日曆不等於民間公司排班。** 國定假日遇例假／休息日應補假，但補假日期需要依實際約定設定；介面上的政府補假參考不會自動變成公司班次。
- 月薪、平日每小時工資額、各制度的月投保薪資與月提繳工資是不同概念。加班試算要求輸入經確認的平日每小時工資額，保費試算依各制度查級距。
- 保費含職災範例費率；正式使用應改填投保單位的核定費率。未實作部分月份、留職停薪、特殊身分、補充保費或正式申報。
- 原始出勤、核准加班與應給工資需分別判斷；不能以「加班未核准」直接認定已提供勞務不需給薪。
- 一般例假出勤不提供自動核算；特殊法定事由須另外處理。
- 出勤紀錄需依法保存至少五年，本系統沒有自動清除出勤資料的功能。仍需落實備份與存取管理。

來源與精確限制：

- [勞基法與請假規則](docs/labor-rules.md)
- [台灣日曆](docs/calendar-rules.md)
- [勞健保、職災及勞退](docs/insurance-rules.md)
- [安全與維運](docs/operations.md)

## 測試

```powershell
python -m unittest discover -s tests -v
node --check web/app.js
```

Node.js 只用於 JavaScript 語法檢查，不是執行系統的必要條件。GitHub Actions 已配置 Windows／Linux 與 Python 3.12／3.13 矩陣；本機執行結果與遠端 Actions 結果應分開判讀。

## Docker

```sh
docker build -t taiwan-attendance .
docker volume create taiwan-attendance-data
docker run --rm -it -v taiwan-attendance-data:/app/runtime taiwan-attendance python -m attendance init
docker run --rm -p 127.0.0.1:8000:8000 -v taiwan-attendance-data:/app/runtime taiwan-attendance
```

Docker 指令是可重現設定，是否可執行仍需在具 Docker 的主機驗證。正式網路使用請依 [維運文件](docs/operations.md) 設定 HTTPS 與反向代理，勿將本機 HTTP 範例直接公開。

## 專案與驗證

- 原始碼：[weber87na/taiwan-attendance](https://github.com/weber87na/taiwan-attendance)
- 自動測試：[GitHub Actions](https://github.com/weber87na/taiwan-attendance/actions)
- 已執行及尚未完成的驗證：[docs/validation.md](docs/validation.md)

也可使用 GitHub 的 **Code → Download ZIP** 取得完整原始碼，解壓縮後從專案目錄執行前述 Python 指令。

請勿將資料庫、備份、密碼或真實員工資料加入倉庫。
