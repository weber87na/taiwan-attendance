# 驗證紀錄

版本0.1.0，日期2026-09-16。本機環境Linux、Python 3.12.14、Node.js 24。

| 驗證 | 結果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 74項全數通過 |
| `node --check web/app.js` | 通過 |
| `python -m compileall -q attendance tests` | 通過 |
| HTTP整合 | 真實本機HTTP連線測試登入、登出、cookie、CSRF、Host/Origin、排班異動、申請取消、日曆及計算器 |
| SQLite業務流程 | 權限隔離、並行打卡／簽核、跨日、請假額度、補卡更正與原始事件保存 |
| 官方規則 | 特休邊界、加班倍率、2026日曆、投保級距、眷屬與捨入 |
| 獨立審查 | 分筆請假總額、整段漏卡、休息不足提示已修復並復驗 |
| 備份 | SQLite完整性檢查、資料一致、禁止覆蓋與Linux檔案權限通過 |
| 瀏覽器操作與視覺驗證 | 未完成；雲端瀏覽器無法連線本機頁面，本機未安裝瀏覽器；已進行前端語法和介接靜態檢查 |
| GitHub Actions：Ubuntu／Windows、Python3.12／3.13 | 四組矩陣全部通過；每組74項測試及JavaScript語法檢查成功 |
| Docker | 已提供Dockerfile，尚未實際建置映像 |

遠端驗證：[GitHub Actions run 35073389572](https://github.com/weber87na/taiwan-attendance/actions/runs/35073389572)，測試程式版本 `63124f312b3fe65b90c4c697a93c729e5b51f2dd`。發布前另修正SQLite連線關閉及測試初始化日期，避免Windows暫存檔清除失敗及日期推移造成測試失敗。

## 測試分布

- 台灣日曆：12項。
- HTTP與安全控制：9項。
- 勞健保／勞退試算：14項。
- 勞基法與請假規則：22項。
- 資料庫與出勤工作流程：17項。

測試通過表示這些已列情境符合實作預期，不代表已完成所有勞動制度的法律認定、正式薪資結算或政府申報驗證。
