# 附近施工(Other planned works)API 介面規格

| 項目 | 內容 |
| --- | --- |
| 契約版本 | v0.1(2026-09-30) |
| 程式碼 | `backend/app/impact/disruptions.py`、`backend/app/schemas.py`、`frontend/src/types.ts`、`frontend/src/disruptions.ts` |
| 資料 | `backend/app/data/disruptions.json`(由 `backend/scripts/fetch_disruptions.py` 產生並 commit) |
| 背景 | `docs/research/planned-disruptions-feasibility.md` |
| P5 reads | **no**。不進 `CommsFacts`,公告不得引用這些日期或數字 |

## 1. 目的

在地圖上顯示使用者施工地點 3 km 內、DTP 已核發許可的其他施工,依「時段重疊 × 距離」分成 4 級灰階,
並在同期施工落在我們封閉的街道或 detour 街道上時提醒使用者。

**只供顯示。** 許可只代表「可以」在這些時段施工,不代表當晚一定有人施工;封閉車道數也只有 45% 有值。
所以這些資料**不進入任何計算**(routing、延誤、設備、公告都不讀)。

## 2. `POST /api/disruptions`

### Request:`DisruptionsRequest`

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `works` | `LatLng[]`(至少 1 點) | 所有已畫線段的座標點 |
| `start_date` | `date` | 施工開始日 |
| `duration_days` | `int` 1–365 | 工期 |
| `time_window` | `day` / `night` / `custom` | 每日時段 |
| `custom_hours` | `[int, int] \| null` | 只有 `custom` 時讀取,可跨午夜 |

依「請求最小化」原則,不含車道、封閉目標、方向:其他許可與這些無關。
改工期或日期會重算這個模組(很便宜,只是查表),**不會**重算 network。

### Response:`DisruptionsResult`

| 欄位 | 說明 |
| --- | --- |
| `available` | `false` 表示這台機器沒有 snapshot,`disruptions` 為空,不會捏造資料 |
| `fetched_at`、`source` | snapshot 抓取時間與來源 |
| `disruptions` | `Disruption[]`,依 `relevance` 由高到低 |
| `note` | 固定說明文字,UI 必須顯示 |

`Disruption` 主要欄位:`permit`(同一許可有多段)、`road_name`、`cause`、`impact_type`、`direction`、
`lanes_impacted`(原樣顯示,常為空)、`start`/`end`(墨爾本當地時間 ISO)、`shifts`(`null` 表示未公布時段)、
`lines`、`edges`、`distance_m`、`overlap`、`relevance`、`level`。

## 3. 計算方式(排序用,不是影響數字)

- **overlap**:逐一檢查每個施工日,看我們的工作時段中有多少比例落在該許可的班次內。
  - 班次歸屬於開始的那一天,所以前一天的跨夜班、後一天的全天班也會納入。
  - 班次會被許可期間截斷,重複的班次先合併。
  - 未公布時段時,以整個許可期間計算:無法排除,就不隱藏。
- **closeness** = 1 / (1 + 距離 / 500 m)。
- **relevance** = overlap × closeness。
- **level**:overlap = 0 時為 0(不同時段);relevance ≥ 0.5 為 3,≥ 0.2 為 2,其餘為 1。
- 參數在 `config.py`(`DISRUPTION_RADIUS_M`、`DISRUPTION_HALF_M`、`DAY_HOURS`),屬於顯示設計選擇,不是工程依據。

## 4. 衝突提示(前端,`frontend/src/disruptions.ts`)

以無方向的 edge 集合交集判斷,level > 0 的許可:

- 與我們封閉路段的 edge 重疊 → 「另一張許可同時段涵蓋你封閉的街道」。
- 與 `NetworkImpact.load_increase` 的 edge 重疊 → 「detour 經過同時段有施工許可的街道」。

只做集合交集,不做任何模擬,文字一律寫成「請確認」而非斷言。

## 5. 更新資料

```bash
cd backend && VICROADS_API_KEY=... python scripts/fetch_disruptions.py   # 重抓並重建 disruptions.json
python scripts/fetch_disruptions.py --offline                            # 用本機原始檔重建
```

API key 放在 `backend/.env`(已被 gitignore)。官方 OpenAPI 規格與實際閘道不符,細節見腳本註解。
