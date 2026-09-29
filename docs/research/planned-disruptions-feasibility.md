# 可行性驗證:DTP Planned Disruptions – Road 作為背景施工資訊

| 項目 | 內容 |
| --- | --- |
| 日期 | 2026-09-30 |
| 分支 | `feature/real-time` |
| 腳本 | `backend/scripts/fetch_disruptions.py` |
| 快照 | `backend/app/data/disruptions_raw.json`(fetched_at 2026-09-29T23:44Z) |
| 結論 | **Phase 1(顯示 + 時空關聯度 + detour 衝突警告)可做。Phase 2(納入 routing)暫緩。** |

## 1. 問題

使用者設定封路時,能不能同時看到附近真實已排定的施工,並依「時間重疊 × 距離」呈現關聯程度?
前提是資料能對上我們的 OSM 路網,且時間欄位足以判斷是否與施工時段重疊。

## 2. 資料來源與存取

- Transport Victoria Open Data,`https://api.opendata.transport.vic.gov.au/opendata/roads/disruptions/planned/v1/`
- **官方 OpenAPI 規格與實際閘道不符**(已在腳本註解說明):
  - 認證 header 要用 `KeyID`,規格寫的 `Ocp-Apim-Subscription-Key` 會回 401。
  - `?format=geojson` 會被閘道擋下(400 MessageBlocked),不帶參數就回 GeoJSON。
  - 分頁 token 要放在 `NextPageToken` **header**。放 query string 會被忽略,第二頁重複第一頁,造成無限迴圈。
- 每頁 500 筆,全州 10,454 筆,路網中心 3 km 內 374 筆(研究區 2.5 km 內 283 筆)。

## 3. 結果

| 檢查 | 結果 | 判定 |
| --- | --- | --- |
| 3 km 內筆數 | 374(54 個許可證,單一許可證最多 34 段) | 充足 |
| 幾何 | LineString 369、Point 5 | 好 |
| 幾何對應 OSM edge(中位偏移 ≤ 15 m) | 356 / 369(96%),整體中位偏移 0.0 m | **非常好**,feed 幾何看起來與 OSM 同源 |
| 幾何 + 路名同時吻合 | 229 / 369(62%) | 路名不一致多半是命名問題(見下) |
| 有 AADT 的路段 | 293 / 369(79%) | Phase 2 的 BPR 大多可用 |
| 起訖日期 | 100% | 好 |
| 每日時段(recurrences) | 100% | 好,但格式特殊(見下) |
| 方向 | 97% 有值,但 220 筆是 "All directions" | 粗 |
| 封閉車道數 | **45%** | 不足以支撐 Phase 2 |

路名不一致的主因:feed 路名為空(26 筆)、匝道命名不同(`CITYLINK OUT FOOTSCRAY RAMP OFF` 對 OSM `Footscray Road Offramp`)、
路口處抓到交叉道路(Victoria St 對 Bouverie St)。幾何本身是對的,所以顯示和 edge 交集判斷不受影響。

### 時間面(施工窗口 2026-10-12 起 3 天)

- 日期重疊 274 筆。很多許可證一次核發數月到一年(7 個月以上 145 筆),所以**日期幾乎無法區分關聯度**。
- 每日時段才是真正的區分因素:日間(09:30–15:30)重疊 14 筆,夜間(20:00–05:00)重疊 268 筆。
  附近施工以夜間為主(大多 21:00–05:00、22:00–05:00),這對 Plan B(夜間施工)是重要的衝突訊號。

### 資料格式陷阱

- `startTime` 為 12 小時制,例如 `9:30 AM`、`9:00 PM`。
- 跨夜班次的 `duration` 是**負值**:`9:00 PM` + `PT-16H0M` 表示到 05:00 結束(實際 8 小時),解析時要 +24h。
- `recurrences` 依星期列出(`startDay`),少數沒有 `startTime`。
- 同一個 ID 會重複出現,甚至在同一頁內,需要去重。
- ID 前綴 `Planned:OneView:` 表示來自 OneView 許可系統。`rmaClass` 含 MU(市議會道路)122 筆,
  所以**資料並非只有 DTP 幹道**,與原本的假設不同。
- `impact.delay` 是 DTP 的分級估計("0 to 5 min"),**不是我們算的**,不能當成模型結果顯示(Rule 1、6)。

## 4. 判定與建議

- **Phase 1 可做。** 門檻:3 km 內至少約 5 筆、日期和時段大多有值、至少約 70% 的線段在 15 m 內對上。
  幾何對應率 96% 過關。路名一致只有 62%,但失敗的原因是命名差異,不是幾何錯誤。
  - 關聯度建議改為 **時段重疊 × 距離**,日期只當過濾條件(因為多數許可證跨數月)。
  - 最有價值的功能是 detour 與同期施工 edge 的交集警告,不需重算 routing。
  - Plan A / Plan B 切換時,背景施工的關聯度會明顯改變(日間 14 筆 vs 夜間 268 筆),這是很好的 demo 點。
- **Phase 2 暫緩。** 封閉車道數只有 45%、方向多為 "All directions",若納入 routing 需要大量假設,違反「不捏造數字」原則。
- 原始快照(約 1.1 MB)被 `.gitignore` 的 raw 規則排除,與 `aadt_raw` 相同,需用腳本重抓。正式版應另存只含所需欄位的精簡檔再 commit。
