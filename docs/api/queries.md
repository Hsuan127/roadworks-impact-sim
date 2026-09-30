# 詢價(Hire queries)API 介面規格

| 項目 | 內容 |
| --- | --- |
| 契約版本 | v0.1(2026-09-30) |
| 程式碼 | `backend/app/queries.py`、`backend/app/schemas.py`、`frontend/src/types.ts`、`frontend/src/components/QueryPanel.tsx`、`frontend/src/components/DepotInbox.tsx` |
| P5 reads | **no**。不進 `CommsFacts` |

## 1. 目的

規劃者(contractor)**看不到庫存**。直接說「沒貨」會在公司還沒評估前就失去這筆生意;
同一天可能有重要與相對不重要的案子,應由公司決定接哪個。所以規劃者送出 query,
公司在 `?view=depot` 收件匣看到每筆 query 的設備、日期、估計金額,以及**把同期其他 query 一起算進去**後的庫存缺口。

資料只存在記憶體,後端重啟即清空(demo 用)。

## 2. `POST /api/queries`

Request `QueryRequest`:

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `scenario` | `ScenarioParams` | 整個方案(日期、時段、路段與路段名稱) |
| `equipment` | `EquipmentRequest` | 與規劃畫面相同的器材請求;**後端重新計算**,不採用前端的結果 |
| `contact` | `QueryContact` | `company`、`contact`(必填)、`email`、`note` |

Response:`HireQuery`(見第 4 節)。

## 3. `GET /api/queries`、`PATCH /api/queries/{id}`

- `GET`:所有 query,新的在前,每筆的 `stock_gaps` 於讀取時計算。
- `PATCH` body `{"status": "accepted" | "declined" | "countered" | "new"}`;找不到回 404。

## 4. `HireQuery`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `id` | string | `Q001` 起編 |
| `submitted_at` | datetime | |
| `status` | `new` / `accepted` / `declined` / `countered` | |
| `segments` | string[] | 路段名稱:使用者自訂名稱,否則道路名稱 |
| `road_classes` | string[] | OSM 道路等級 |
| `start_date`、`end_date` | date | `end_date` 為最後施工日(含) |
| `time_window` | `day` / `night` / `custom` | |
| `items`、`total_cost_aud` | | 同 `EquipmentResult`,含 `stock`、`in_stock`(只給公司看) |
| `stock_gaps` | `StockGap[]` | `item_id`、`name`、`stock`、`requested`(本案)、`overlapping_demand`(本案 + 日期重疊且未拒絕的其他 query) |
| `overlaps_with` | string[] | 日期重疊且未拒絕的其他 query id |

**刻意保守**:只要有一天重疊就視為同時需要整批設備;時段(日 / 夜)不區分。

## 5. 前端

- 規劃畫面:移除所有「庫存不足」提示,費用標示為「估價,非報價」;左側選單最下方有 **Send query to RPM Hire**。
- 公司畫面:`/?view=depot`,每 3 秒更新,點一列展開缺口明細與 Accept / Counter-offer / Decline。
