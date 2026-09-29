# P5 AI 層 API 介面規格

| 項目 | 內容 |
| --- | --- |
| 契約版本 | v0.2(2026-09-29) |
| 負責人 | P5(AI 層) |
| 程式碼 | `backend/app/ai/llm.py`、`backend/app/schemas.py`、`frontend/src/types.ts` |
| 狀態 | 草案。欄位異動請依第 8 節的變更流程 |

## 1. 目的與範圍

本文件規定 P5 AI 層與其他模組之間的正式介面:P5 **接收**什麼、**回傳**什麼、**依賴**其他模組的哪些欄位,以及出錯時的行為。

P5 負責三件事:

1. **表單預填**:把使用者的一句話轉成表單欄位(`POST /api/parse`)。
2. **溝通草稿**:根據計算結果產生 VMS 看板訊息與民眾公告(`POST /api/comms`)。
3. **事實檢視**:回傳 AI 被允許使用的事實表,方便除錯(`POST /api/comms/facts`)。

P5 **不負責**計算任何數量或影響數字。所有數字都來自 P2、P3、P4 的輸出,P5 只負責把它們寫成文字。

## 2. 資料流

```
使用者 ─(一句話)→ P1 前端 ─POST /api/parse→ P5 ─→ 預填欄位 → P1 表單
                                                            │
P1 表單 ─→ P2 /api/impact/network ─→ NetworkImpact ─┐       │
        ─→ P3 /api/impact/transit ─→ TransitImpact ─┼→ P1 ─POST /api/comms→ P5 ─→ Comms → P1 顯示
        ─→ P4 /api/equipment      ─→ EquipmentResult┘
```

P5 不直接呼叫 P2、P3、P4。P1 前端先拿到三個模組的結果,再一起放進 `CommsRequest` 送給 P5。這樣 P5 可以獨立測試,也不會重複計算。

## 3. 通用約定

| 項目 | 規定 |
| --- | --- |
| 基本路徑 | 開發環境 `http://127.0.0.1:8000`;前端透過 Vite proxy 呼叫 `/api/...` |
| 格式 | 請求與回應皆為 JSON,UTF-8 |
| 日期 | `YYYY-MM-DD`(ISO 8601),例如 `2026-10-06` |
| 單位 | 長度公尺、時間分鐘、速度 km/h、金額澳幣(AUD) |
| 座標 | `[lat, lng]`(緯度在前),WGS84 |
| 錯誤格式 | `{"detail": "錯誤說明"}`,欄位驗證錯誤時 `detail` 為陣列(FastAPI 預設格式) |
| 自動文件 | 後端啟動後可在 `http://127.0.0.1:8000/docs` 直接試打所有端點 |

## 4. 端點

### 4.1 `POST /api/comms`:產生 VMS 訊息與民眾公告

**呼叫者**:P1 前端(使用者按下「Draft VMS and notice」時)。

**請求**:`CommsRequest`(第 5.7 節)。`scenario` 必填;`network`、`transit`、`equipment` 可以是 `null`,缺少時公告就不提該部分。

**回應**:`Comms`(第 5.8 節)。

**行為規則**

1. 先由 `build_facts()` 從請求中整理出 `CommsFacts`(第 6 節)。**這是 AI 唯一可以使用的事實來源。**
2. 用固定範本產生 VMS 訊息與公告初稿。
3. 如果有設定 `ANTHROPIC_API_KEY`,再請 LLM 潤飾公告文字。
4. **數字防護**:LLM 的輸出只要出現任何不在事實表裡的數字,就整份退回範本版本。`generated_by` 會告訴前端最後用的是哪一種。
5. VMS 訊息**永遠**由範本產生,不經過 LLM,以確保行數與字數符合看板限制。

**錯誤**

| 狀態碼 | 何時發生 | 前端處理 |
| --- | --- | --- |
| 200 | 正常。LLM 失敗時也會回 200,只是 `generated_by` 為 `template` | 正常顯示 |
| 422 | 請求欄位格式錯誤(例如日期格式不對) | 顯示 `detail`,檢查送出的資料 |

這個端點**不會**因為 LLM 失敗而回錯誤,Demo 時可以放心使用。

**請求範例**(節錄)

```json
{
  "scenario": {
    "name": "A",
    "location": {"lat": -37.7938, "lng": 144.9484, "edge": [24, 25, 0],
                 "road_name": "Flemington Road", "road_class": "primary"},
    "targets": ["traffic_lane", "bike_lane"],
    "direction": "citybound",
    "lanes_closed": 1,
    "work_length_m": 30.0,
    "start_date": "2026-10-06",
    "duration_days": 3,
    "time_window": "day",
    "custom_hours": null,
    "speed_limit_kmh": 60,
    "work_type": "excavation"
  },
  "network": {"avg_extra_min": 0.19, "load_increase": [{"road_name": "Demo Street 4", "...": "..."}], "...": "..."},
  "transit": {"routes": [{"route_id": "demo-tram-2", "short_name": "Demo tram B", "mode": "tram", "needs_replacement": false}], "...": "..."},
  "equipment": null
}
```

**回應範例**

```json
{
  "vms_messages": [
    ["ROADWORKS", "FLEMINGTON", "LANE CLOSED"],
    ["LEFT LANE", "CLOSED AHEAD", "MERGE RIGHT"],
    ["BIKE LANE", "CLOSED", "USE CAUTION"],
    ["WORKS FROM", "TUE 6 OCT", "FOR 3 DAYS"]
  ],
  "public_notice_md": "# Roadworks notice: Flemington Road\n\nFrom **Tuesday 6 October 2026** to **Thursday 8 October 2026**, 9:30am to 3:30pm, works will close the traffic lane, bike lane on Flemington Road (citybound).\n\nExpect more traffic on Demo Street 4.\n\nPublic transport: Demo tram B may be affected.\n\nAccess to homes and businesses will be maintained. We apologise for any inconvenience.",
  "generated_by": "template",
  "disclaimer": "Draft only. Must be reviewed by a qualified traffic management practitioner."
}
```

### 4.2 `POST /api/parse`:一句話預填表單

**呼叫者**:P1 前端(使用者在「Describe the works in one sentence」輸入後按下「Fill the form」)。

**請求**:`ParseRequest`(第 5.9 節)。

**回應**:`ParseResult`(第 5.9 節)。

**行為規則**

1. 只回傳白名單內的欄位(`PARSE_FIELDS`,見第 5.9 節)。LLM 多給的欄位一律丟掉。
2. 每個欄位都會用 `ScenarioParams` 的規則驗證。驗證不過的欄位不會回傳,而是改列在 `missing`,請使用者自己填。
3. **不預填位置與速限**。句子裡提到的道路名稱放在 `road_hint`,使用者仍需在地圖上點選確認。
4. `fields` 只作為**預填值**。預填後使用者仍可在表單上修改任何欄位,前端不應把預填結果當作已確認的方案。

**錯誤**

| 狀態碼 | 何時發生 | 前端處理 |
| --- | --- | --- |
| 200 | 正常 | 預填表單,顯示 `missing` 與 `road_hint` |
| 422 | LLM 回傳的內容不是合法 JSON | 提示「無法解讀,請直接填表單」 |
| 502 | LLM 服務呼叫失敗或逾時 | 提示稍後再試,或直接填表單 |
| 503 | 伺服器沒有設定 `ANTHROPIC_API_KEY` | 隱藏或停用這個功能 |

**請求範例**

```json
{"text": "Next Tuesday for three days, dig up the citybound kerb lane and bike lane on Flemington Rd near Racecourse Rd, about 30 m."}
```

**回應範例**

```json
{
  "fields": {
    "targets": ["traffic_lane", "bike_lane"],
    "direction": "citybound",
    "lanes_closed": 1,
    "work_length_m": 30,
    "start_date": "2026-10-06",
    "duration_days": 3,
    "work_type": "excavation"
  },
  "missing": ["time_window"],
  "road_hint": "Flemington Rd near Racecourse Rd"
}
```

### 4.3 `POST /api/comms/facts`:檢視 AI 可用的事實表(除錯用)

**請求**:與 `/api/comms` 相同的 `CommsRequest`。

**回應**:`CommsFacts`(第 6 節)。

用途:當公告內容看起來不對時,先打這支確認事實表是否正確。事實表錯了是上游模組或 P1 的問題,事實表對了但文字錯了才是 P5 的問題。

## 5. Schema 定義

欄位名稱一律使用英文(與程式碼一致),說明使用中文。「P5 讀取」一欄標示 P5 是否實際用到該欄位。**標示「是」的欄位,其他模組改名或改意義前必須先通知 P5。**

### 5.1 列舉值

**`ClosureTarget`(封閉對象)**

| 值 | 中文 | 說明 |
| --- | --- | --- |
| `traffic_lane` | 車道 | 封閉部分車道,數量見 `lanes_closed` |
| `bike_lane` | 自行車道 | 封閉自行車道,不影響汽車路網 |
| `footpath` | 人行道 | 封閉人行道,會計算行人繞行 |
| `full` | 全封 | 封閉該方向所有車道 |

**`TimeWindow`(每日施工時段)**

| 值 | 中文 | 說明 |
| --- | --- | --- |
| `day` | 日間 | 固定 09:30–15:30(避開尖峰) |
| `night` | 夜間 | 固定 20:00–05:00 |
| `custom` | 自訂 | 時段見 `custom_hours` |

**`WorkType`(施工類型)**

| 值 | 中文 | 說明 |
| --- | --- | --- |
| `excavation` | 開挖 | 需要護欄與行人圍籬 |
| `non_excavation` | 非開挖 | 不需要開挖護欄 |

**`direction`(封閉方向)**:`citybound`(往市區)、`outbound`(往郊區)、`both`(雙向)。

### 5.2 `Location`(施工位置)

| 欄位 | 型別 | 必填 | P5 讀取 | 說明 |
| --- | --- | --- | --- | --- |
| `lat` | number | 是 | 否 | 使用者點選的緯度 |
| `lng` | number | 是 | 否 | 使用者點選的經度 |
| `edge` | `[int, int, int]` \| null | 否 | 否 | 對應到的 OSM 路段編號 `(u, v, key)`,由 `/api/snap` 產生 |
| `road_name` | string \| null | 否 | **是** | 道路名稱,例如 `Flemington Road`。VMS 與公告的道路名稱都來自這裡 |
| `road_class` | string \| null | 否 | 否 | OSM 道路等級,例如 `primary`。P4 用來判斷是否需要 VMS |

### 5.3 `ScenarioParams`(一個施工方案的所有參數,由 P1 表單產生)

| 欄位 | 型別 | 必填 | 預設 | 範圍 | P5 讀取 | 說明 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | string | 否 | `"A"` | | 否 | 方案名稱,例如 A、B |
| `location` | `Location` | 是 | | | **是** | 施工位置(見 5.2) |
| `targets` | `ClosureTarget[]` | 否 | `["traffic_lane"]` | | **是** | 封閉對象,可複選。決定 VMS 內容與公告寫法 |
| `direction` | string | 否 | `"citybound"` | 見 5.1 | **是** | 封閉方向,寫入公告 |
| `lanes_closed` | int | 否 | 1 | 1–4 | 否 | 封閉車道數 |
| `work_length_m` | number | 否 | 30 | >0,≤2000 | 否 | 工區長度(公尺) |
| `start_date` | date | 是 | | | **是** | 開工日期,寫入 VMS 與公告 |
| `duration_days` | int | 否 | 3 | 1–365 | **是** | 工期天數,用來推算結束日期 |
| `time_window` | `TimeWindow` | 否 | `"day"` | | **是** | 每日時段,寫入公告 |
| `custom_hours` | `[int, int]` \| null | 否 | null | 0–24 | **是** | 自訂時段的起訖小時,只在 `custom` 時使用 |
| `speed_limit_kmh` | int \| null | 否 | null | 10–110 | 否 | 速限。預設讀 OSM,使用者可覆寫 |
| `work_type` | `WorkType` | 否 | `"excavation"` | | 否 | 施工類型 |

### 5.4 `NetworkImpact`(P2 車流與行人影響的輸出)

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `affected_trips_pct` | number | 否 | 受影響的旅次比例(改道**或**變慢),0–1 |
| `rerouted_trips_pct` | number | 否 | 必須改走其他路線的旅次比例,0–1 |
| `unreachable_trips_pct` | number | 否 | 封閉後完全無路可走的旅次比例。**不計入**下列延誤統計,也不再用 60 分鐘飽和值假裝成延誤 |
| `avg_extra_min` | number | **是** | 受影響旅次的平均增加時間(分鐘)。**已不再乘上時段係數**:時段透過車流量進入模型。公告四捨五入後使用,為 0 時公告不提 |
| `max_extra_min` | number | 否 | 最大增加時間(分鐘) |
| `time_factor` | number | 否 | 僅供顯示:該時段每小時車流量相對於日間的比值。**不會**乘進延誤 |
| `closed_geometry` | `[lat, lng][]` | 否 | 封閉路段的座標,前端畫地圖用 |
| `closed_edges` | `[int,int,int][]` | 否 | 實際被移除或加罰的路段。分隔道路(如 Flemington Rd)雙向封閉時會有兩條 |
| `closed_aadt` | `AadtRef` \| null | 否 | 封閉路段的實測車流量(VicRoads)。**僅供顯示** |
| `load_increase` | `EdgeLoad[]` | **是** | 吸收繞行車流的街道,依影響大小排序。P5 取前 3 條的 `road_name` 寫入公告 |
| `ped_detour_m` | number \| null | 否 | 行人繞行增加的距離(公尺),只有封人行道時才有值 |
| `ped_detour_basis` | string \| null | 否 | `footway`(真實人行道網)或 `street_centreline`(只有道路中心線,數字偏高) |
| `sensitive_facilities` | `Facility[]` | 否(預留) | 繞行路線附近的醫院、學校、消防站 |
| `is_demo_data` | boolean | 否 | 是否使用示範路網。為 true 時結果不代表真實道路 |
| `note` | string | 否 | 方法說明:旅次為合成,車流量為實測,延誤來自 BPR 容量曲線 |

**`AadtRef`(一條路段的已發布車流量;只查表,不計算)**

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `aadt` | int | 否 | 年平均日交通量 |
| `heavy` | int \| null | 否 | 其中重型車輛數 |
| `year` | int | 否 | 資料年份(目前為 2019,官方最新釋出年份) |
| `direction` | string \| null | 否 | 官方公布的行進方向,例如 `SOUTH EAST BOUND` |
| `method` | string \| null | 否 | `Actual`(實測)或 `Estimated`(推估) |

> ⚠️ **AADT 相關欄位一律不得進入 `CommsFacts`。** 目前 `build_facts()` 只收 `avg_extra_min` 與
> `detour_streets`,因此 `passes_number_guard` 會拒絕任何引用 26,523 之類數字的公告並退回模板。
> 這是刻意的設計:要讓公告能講車流量,必須先由 P5 依 §8 流程擴充事實表。

**`EdgeLoad`(一條吸收繞行車流的街道)**

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `edge` | `[int, int, int]` | 否 | OSM 路段編號 |
| `road_name` | string \| null | **是** | 街道名稱 |
| `delta` | number | 否 | 被改道的旅次中,有多少比例會經過這條街,0–1 |
| `aadt` | `AadtRef` \| null | 否 | 該街道的實測車流量(若有)。僅供顯示 |
| `geometry` | `[lat, lng][]` | 否 | 路段座標 |

**`Facility`(敏感設施)**

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `name` | string | 設施名稱 |
| `kind` | string | 類型:`hospital`、`school`、`fire_station` 等 |
| `lat` / `lng` | number | 位置 |

### 5.5 `TransitImpact`(P3 大眾運輸的輸出)

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `routes` | `AffectedRoute[]` | **是** | 行經封閉路段的路線 |
| `stops` | `NearbyStop[]` | 否 | 封閉路段 400 公尺內的站牌 |
| `is_demo_data` | boolean | 否 | 是否為示範路線 |

**`AffectedRoute`(受影響路線)**

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `route_id` | string | 否 | GTFS 路線編號 |
| `short_name` | string | **是** | 路線顯示名稱,例如電車路線號碼。寫入公告 |
| `mode` | `tram` \| `bus` \| `train` \| `other` | 否 | 運具種類 |
| `needs_replacement` | boolean | **是** | 是否需要替代接駁(電車遇到全封時為 true)。為 true 時公告會加註替代公車 |

**`NearbyStop`(附近站牌)**:`stop_id`(站牌編號)、`name`(站名)、`lat` / `lng`(位置)、`distance_m`(距封閉路段中點的公尺數)。

### 5.6 `EquipmentResult`(P4 器材清單的輸出)

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `items` | `EquipmentItem[]` | 否 | 器材明細 |
| `total_cost_aud` | number | 否 | 預估租金總額(澳幣) |
| `shortages` | string[] | **是**(內部) | 庫存不足的品項名稱。只進事實表,**不會出現在民眾公告** |
| `rules_verified` | boolean | 否 | 規則數值是否已對照法規驗證 |
| `disclaimer` | string | 否 | 免責說明 |

**`EquipmentItem`**:`item_id`(品項代碼)、`name`(品項名稱)、`qty`(數量)、`reason`(為什麼需要這個數量)、`stock`(場站庫存)、`in_stock`(庫存是否足夠)、`daily_rate_aud`(日租金)、`cost_aud`(此行總租金 = 數量 × 日租金 × 工期)。

### 5.7 `CommsRequest`(`/api/comms` 的請求)

| 欄位 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| `scenario` | `ScenarioParams` | 是 | 目前的施工方案 |
| `network` | `NetworkImpact` \| null | 否 | P2 的結果;沒有時公告不提延誤與繞行街道 |
| `transit` | `TransitImpact` \| null | 否 | P3 的結果;沒有時公告不提大眾運輸 |
| `equipment` | `EquipmentResult` \| null | 否 | P4 的結果;目前只用於內部事實表 |

### 5.8 `Comms`(`/api/comms` 的回應)

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `vms_messages` | `string[][]` | VMS 看板訊息。外層每個元素是一則訊息(一個畫面),內層每個字串是一行。每則最多 `VMS_LINES` 行、每行最多 `VMS_CHARS_PER_LINE` 字元,全大寫 |
| `public_notice_md` | string | 民眾公告,Markdown 格式(只用 `#` 標題與 `**粗體**`) |
| `generated_by` | `template` \| `llm` | 公告最後由誰產生。`llm` 表示 AI 潤飾且通過數字防護;`template` 表示固定範本 |
| `disclaimer` | string | 固定免責說明:草稿,需合格交通管理人員審核 |

### 5.9 `ParseRequest` 與 `ParseResult`(`/api/parse`)

**`ParseRequest`**

| 欄位 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| `text` | string | 是 | 使用者輸入的一句話施工描述(建議英文,中文也可) |

**`ParseResult`**

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `fields` | object | 可預填的欄位,鍵只會是 `PARSE_FIELDS` 之一,且都已通過驗證 |
| `missing` | string[] | 句子裡沒提到或值不合法、需要使用者自己填的欄位名稱 |
| `road_hint` | string \| null | 句子裡提到的道路名稱,只作提示,不會自動設定位置 |

`PARSE_FIELDS`(可被預填的欄位白名單):`targets`、`direction`、`lanes_closed`、`work_length_m`、`start_date`、`duration_days`、`time_window`、`custom_hours`、`work_type`。

**刻意不預填**:`location`、`speed_limit_kmh`、`name`。位置必須由使用者在地圖上確認,速限必須來自地圖資料或使用者輸入。

## 6. `CommsFacts`:AI 可用的事實表

這是 P5 內部最重要的資料結構。**公告與 VMS 中出現的每一個數字,都必須能在這張表裡找到。**

| 欄位 | 型別 | 來源 | 說明 |
| --- | --- | --- | --- |
| `road` | string | `scenario.location.road_name` | 道路名稱;沒有時為 `the work site` |
| `start` | string | `scenario.start_date` | 開工日期,英文完整格式,例如 `Tuesday 6 October 2026` |
| `end` | string | `start_date + duration_days - 1` | 完工日期 |
| `hours` | string \| null | `scenario.time_window`、`custom_hours` | 每日施工時段文字,例如 `9:30am to 3:30pm` |
| `duration_days` | int | `scenario.duration_days` | 工期天數 |
| `closures` | string[] | `scenario.targets` | 封閉對象的英文描述 |
| `direction` | string | `scenario.direction` | 封閉方向 |
| `avg_extra_min` | int \| null | `network.avg_extra_min` 四捨五入 | 平均增加分鐘數 |
| `detour_streets` | string[] | `network.load_increase` 前 3 名 | 預期車流增加的街道名稱 |
| `routes` | string[] | `transit.routes[].short_name` | 受影響的大眾運輸路線 |
| `replacement_needed` | boolean | `transit.routes[].needs_replacement` | 是否需要替代接駁 |
| `shortages` | string[] | `equipment.shortages` | 庫存不足品項。**僅供內部,不會送進民眾公告,也不會送給 LLM** |

## 7. P5 的承諾與限制

**P5 承諾**

1. 不計算、不修改任何數量或影響數字。
2. `/api/comms` 在 LLM 失敗時一定退回範本,不回錯誤。
3. 所有公告都附免責說明,並標示 `generated_by`。
4. 產生公告時,送給 LLM 的只有 `CommsFacts`(不含 `shortages`)與範本初稿;預填時只送出使用者輸入的那句話與今天日期。兩者都不會送出座標、路段編號或器材資料。

**其他模組需配合**

1. **P1**:呼叫 `/api/comms` 時,盡量把 `network`、`transit` 的最新結果一起帶上;`/api/parse` 的結果只能當預填值。
2. **P2、P3、P4**:第 5 節中標示「P5 讀取:是」的欄位,改名、改型別或改意義前,先在群組通知 P5,並依第 8 節流程更新。

**設定參數**(`backend/.env` 與 `backend/app/config.py`)

| 參數 | 預設值 | 說明 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | 空 | 設定後才會啟用一句話預填與 AI 潤飾公告 |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | 使用的模型 |
| `LLM_PROVIDER` | `anthropic` | 設為 `none` 可強制只用範本(例如 Demo 現場網路不穩時) |
| `VMS_LINES` | 3 | VMS 每則訊息的行數(**待向 RPM Hire 確認**) |
| `VMS_CHARS_PER_LINE` | 12 | VMS 每行字元數(**待向 RPM Hire 確認**) |

## 8. 變更流程

任何欄位的新增、改名或改型別,都要在**同一個 PR** 裡同時更新以下三處:

1. `backend/app/schemas.py`(後端正式定義)
2. `frontend/src/types.ts`(前端型別,必須與後端一致)
3. 本文件的對應表格,並更新文件開頭的契約版本號

新增欄位且有預設值,屬於相容變更,版本號升第二位(例如 v0.1 → v0.2)。改名、刪除或改型別屬於不相容變更,需要 P1 與 P5 都在 PR 上確認後才能合併。

## 9. 自我測試

```bash
cd backend
pytest -q                                   # 全部測試,含 P5 的數字防護與錯誤碼測試

# 取得示範方案,再產生溝通草稿
curl -s http://127.0.0.1:8000/api/demo-scenario > /tmp/s.json
curl -s -X POST http://127.0.0.1:8000/api/comms \
  -H 'Content-Type: application/json' \
  -d "{\"scenario\": $(cat /tmp/s.json)}"

# 看 AI 能用的事實表
curl -s -X POST http://127.0.0.1:8000/api/comms/facts \
  -H 'Content-Type: application/json' \
  -d "{\"scenario\": $(cat /tmp/s.json)}"
```

P5 相關的測試位於 `backend/tests/test_api.py`:`test_comms_template_without_key`、`test_number_guard`、`test_llm_rewrite_with_new_number_is_rejected`、`test_parse_whitelists_and_validates`、`test_parse_errors`、`test_facts_endpoint`、`test_vms_road_name_fits`。
