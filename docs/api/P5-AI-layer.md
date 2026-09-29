# P5 AI 層 API 介面規格

| 項目 | 內容 |
| --- | --- |
| 契約版本 | v0.5(2026-09-30),見文末「版本紀錄」 |
| 負責人 | P5(AI 層) |
| 程式碼 | `backend/app/ai/llm.py`、`backend/app/schemas.py`、`frontend/src/types.ts` |
| 狀態 | 草案。欄位異動請依第 8 節的變更流程 |

## 1. 目的與範圍

本文件規定 P5 AI 層與其他模組之間的正式介面:P5 **接收**什麼、**回傳**什麼、**依賴**其他模組的哪些欄位,以及出錯時的行為。

P5 負責三件事:

1. **表單預填**:把使用者的一句話轉成表單欄位(`POST /api/parse`)。
2. **溝通草稿**:根據計算結果產生 VMS 看板訊息與民眾公告(`POST /api/comms`)。
3. **事實檢視**:回傳 P5 內部/debug 事實表,方便除錯(`POST /api/comms/facts`)。

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

一個方案(`ScenarioParams`)可以有**多個封閉路段**(`segments`),每段各自在地圖上畫出,各自有封閉對象、方向與車道數。時間(開工日、工期、時段)與施工類型則是整個方案共用。

## 3. 通用約定

| 項目 | 規定 |
| --- | --- |
| 基本路徑 | 開發環境 `http://127.0.0.1:8000`;前端透過 Vite proxy 呼叫 `/api/...` |
| 格式 | 請求與回應皆為 JSON,UTF-8 |
| 日期 | `YYYY-MM-DD`(ISO 8601),例如 `2026-10-06` |
| 單位 | 長度公尺、時間分鐘、速度 km/h、金額澳幣(AUD) |
| 座標 | `[lat, lng]`(緯度在前),WGS84 |
| 路段編號 | `[u, v, key]`,OSM 路網的有向路段 |
| 錯誤格式 | `{"detail": "錯誤說明"}`,欄位驗證錯誤時 `detail` 為陣列(FastAPI 預設格式) |
| 自動文件 | 後端啟動後可在 `http://127.0.0.1:8000/docs` 直接試打所有端點 |

## 4. 端點

### 4.1 `POST /api/comms`:產生 VMS 訊息與民眾公告

**呼叫者**:P1 前端(使用者按下「Draft VMS and notice」時)。

**請求**:`CommsRequest`(第 5.7 節)。`scenario` 必填;`network`、`transit`、`equipment` 可以是 `null`,缺少時公告就不提該部分。

**回應**:`Comms`(第 5.8 節)。

**行為規則**

1. 先由 `build_facts()` 從請求中整理出內部事實表(第 6 節),再由 `public_notice_facts()` 移除 equipment、AADT 等內部欄位。**公開公告與 LLM 只能使用 public notice facts。**
2. 只使用**已畫好的路段**(`edges` 非空)。只點了一下、還沒畫成線的路段不算施工範圍,不會出現在 VMS 或公告裡。
3. 用固定範本產生 VMS 訊息與公告初稿。公告中每個路段各佔一行,封閉對象與方向跟著自己的道路。
4. 如果 `LLM_PROVIDER` 不是 `none` 且有設定 `GEMINI_API_KEY`,再用 Gemini 潤飾公告文字。SDK 會 lazy import,沒有金鑰或 provider 失敗時 `/api/comms` 仍回範本。
5. **數字防護**:LLM 的輸出只要出現任何不在事實表裡的數字,就整份退回範本版本。`generated_by` 會告訴前端最後用的是哪一種。
6. VMS 訊息**永遠**由範本產生,不經過 LLM。每個路段各自產生訊息,重複的訊息只保留一則。路段是否還留有車道,以 `network.full_closure` 為準:沒有車道可走時顯示 `ROAD CLOSED`;沒有 `network` 時只看 `targets` 是否含 `full`。
7. VMS 按官方 screen 規則限制:每個畫面最多 4 個 words/numbers,alternating series 最多 2 個畫面。只輸出目前請求能支持的封閉事實,例如 `LANE CLOSED`、`ROAD CLOSED`、`BIKE LANE CLOSED`、`FOOTPATH CLOSED`;不加入 `USE CAUTION` 或未由事實支持的 `MERGE LEFT`、`MERGE RIGHT`、`USE DETOUR`。`VMS_CHARS_PER_LINE` 只是草案顯示限制,不能為了它截斷長路名或長單字;超過 4 個 words/numbers 的路名不會被部分塞進畫面。

**錯誤**

| 狀態碼 | 何時發生 | 前端處理 |
| --- | --- | --- |
| 200 | 正常。LLM 失敗時也會回 200,只是 `generated_by` 為 `template` | 正常顯示 |
| 422 | 請求欄位格式錯誤(例如日期格式不對) | 顯示 `detail`,檢查送出的資料 |

這個端點**不會**因為 LLM 失敗而回錯誤,Demo 時可以放心使用。

**請求範例**(節錄,取自示範方案)

```json
{
  "scenario": {
    "name": "A",
    "segments": [
      {
        "id": "1",
        "waypoints": [[-37.794491, 144.95028], [-37.794491, 144.95062]],
        "edges": [[24, 25, 0]],
        "geometry": [[-37.794491, 144.95028], [-37.794491, 144.95062]],
        "length_m": 30.0,
        "road_name": "Flemington Road",
        "road_class": "primary",
        "speed_limit_kmh": 60,
        "targets": ["traffic_lane", "bike_lane"],
        "direction": "citybound",
        "lanes_closed": 1
      }
    ],
    "start_date": "2026-10-06",
    "duration_days": 3,
    "time_window": "day",
    "custom_hours": null,
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
    ["LANE CLOSED", "FLEMINGTON", "RD"],
    ["BIKE LANE", "CLOSED"]
  ],
  "public_notice_md": "# Roadworks notice: Flemington Road\n\nFrom **Tuesday 6 October 2026** to **Thursday 8 October 2026**, 9:30am to 3:30pm, works will close:\n\n- the traffic lane, bike lane on Flemington Road (citybound)\n\nExpect more traffic on Demo Avenue 4, Demo Street 4, Racecourse Road.\n\nPublic transport: Demo tram B may be affected.\n\nWe apologise for any inconvenience.",
  "generated_by": "template",
  "disclaimer": "Draft only. Must be reviewed by a qualified traffic management practitioner."
}
```

### 4.2 `POST /api/comms/facts`:檢視 P5 事實表

**呼叫者**:開發者或前端除錯工具。

**請求**:`CommsRequest`(第 5.7 節),和 `/api/comms` 相同。

**回應**:第 6 節的內部/debug 事實表。這個端點保留 equipment、warnings、supplier、closed AADT 等內部 facts,方便檢查 P2/P4 結果是否正確進入 P5;正式民眾公告與 LLM prompt 會先移除 internal-only facts。

### 4.3 `POST /api/parse`:一句話預填表單

**呼叫者**:P1 前端(使用者在「Describe the works in one sentence」輸入後按下「Fill the form」)。

**請求**:`ParseRequest`(第 5.9 節)。

**回應**:`ParseResult`(第 5.9 節)。

**行為規則**

1. 只回傳白名單內的欄位(`ParsedFields`,見第 5.9 節)。LLM 多給的欄位(例如 `segments`、`speed_limit_kmh`、`custom_hours`)一律丟掉。
2. 每個欄位**各自**驗證。驗證不過的欄位不會回傳,而是改列在 `missing`,請使用者自己填;其他合法欄位照常回傳。
3. **不預填位置與速限**。句子裡提到的道路名稱放在 `fields.road_name`,只作顯示,位置仍需使用者在地圖上畫。
4. `targets`、`direction`、`lanes_closed` 屬於路段:前端只套用到**目前編輯中的路段**。沒有選取路段時不套用,並提示使用者先選路段,不可顯示為「已填入」。
5. 其餘欄位(`start_date`、`duration_days`、`time_window`、`work_type`)套用到整個方案。
6. `fields` 只作為**預填值**。預填後使用者仍可在表單上修改任何欄位,前端不應把預填結果當作已確認的方案。

**錯誤**

| 狀態碼 | 何時發生 | 前端處理 |
| --- | --- | --- |
| 200 | 正常 | 預填表單,顯示 `missing` |
| 422 | LLM 回傳的內容不是合法 JSON,或不是 `{"fields": {...}, "missing": [...]}` 的形狀 | 提示「無法解讀,請直接填表單」 |
| 502 | LLM 服務呼叫失敗(連線失敗、逾時、流量限制或服務錯誤) | 提示「AI 服務暫時無法使用,請直接填表單」 |
| 503 | 伺服器沒有設定 `GEMINI_API_KEY`,或 `LLM_PROVIDER=none` | 隱藏或停用這個功能 |

**請求範例**

```json
{"text": "Next Tuesday for three days, dig up the citybound kerb lane and bike lane on Flemington Rd near Racecourse Rd, about 30 m."}
```

**回應範例**

```json
{
  "fields": {
    "road_name": "Flemington Rd",
    "targets": ["traffic_lane", "bike_lane"],
    "direction": "citybound",
    "lanes_closed": 1,
    "start_date": "2026-10-06",
    "duration_days": 3,
    "time_window": null,
    "work_type": "excavation"
  },
  "missing": ["time_window"]
}
```

## 5. Schema 定義

欄位名稱一律使用英文(與程式碼一致),說明使用中文。「P5 讀取」一欄標示 P5 是否實際用到該欄位。**標示「是」的欄位,其他模組改名或改意義前必須先通知 P5。**

### 5.1 列舉值

**`ClosureTarget`(封閉對象)**

| 值 | 中文 | 說明 |
| --- | --- | --- |
| `traffic_lane` | 車道 | 封閉部分車道,數量見路段的 `lanes_closed` |
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

**`direction`(封閉方向)**:`citybound`(往市區)、`outbound`(往郊區)、`both`(雙向)。單行道選 `both` 時實際只有一個來車方向。

### 5.2 `Segment`(一段封閉路段)

| 欄位 | 型別 | 必填 | 預設 | P5 讀取 | 說明 |
| --- | --- | --- | --- | --- | --- |
| `id` | string | 是 | | 否 | 路段編號,在方案內唯一。介面上的「Segment N」與器材清單的標示都用這個 id |
| `waypoints` | `[lat, lng][]` | 否 | `[]` | 否 | 使用者依序點選的位置(已吸附到街道上),由 `/api/path` 產生 |
| `edges` | `[int, int, int][]` | 否 | `[]` | **是** | 這條線經過的完整路段,順序即車流方向,由 `/api/path` 產生。**空陣列代表還沒畫完,P5 會略過這段** |
| `geometry` | `[lat, lng][]` | 否 | `[]` | 否 | 畫出的線,起訖點就是使用者點的位置 |
| `length_m` | number | 否 | 0 | 否 | 畫出的線長(公尺),即工區長度 |
| `road_name` | string \| null | 否 | null | **是** | 道路名稱,例如 `Flemington Road`。跨多條路時取畫線長度最長的那條。VMS 與公告的道路名稱都來自這裡 |
| `road_class` | string \| null | 否 | null | 否 | OSM 道路等級,例如 `primary`。P4 用來判斷是否需要 VMS |
| `speed_limit_kmh` | int \| null | 否 | null | 否 | 速限,10–110。畫線時由地圖資料帶入;使用者輸入的值不會被重畫覆蓋 |
| `targets` | `ClosureTarget[]` | 否 | `["traffic_lane"]` | **是** | 封閉對象,可複選。決定 VMS 內容與公告寫法 |
| `direction` | string | 否 | `"citybound"` | **是** | 封閉方向,寫入公告 |
| `lanes_closed` | int | 否 | 1 | **是** | 該方向封閉的車道數,1–4。VMS 只在封閉 1 條時寫 `LEFT LANE` |

### 5.3 `ScenarioParams`(一個施工方案的所有參數,由 P1 表單產生)

| 欄位 | 型別 | 必填 | 預設 | 範圍 | P5 讀取 | 說明 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | string | 否 | `"A"` | | 否 | 方案名稱,例如 A、B |
| `segments` | `Segment[]` | 否 | `[]` | | **是** | 封閉路段(見 5.2),可以共用街道或路口 |
| `start_date` | date | 是 | | | **是** | 開工日期,寫入 VMS 與公告 |
| `duration_days` | int | 否 | 3 | 1–365 | **是** | 工期天數,用來推算結束日期 |
| `time_window` | `TimeWindow` | 否 | `"day"` | | **是** | 每日時段,寫入公告 |
| `custom_hours` | `[int, int]` \| null | 否 | null | 0–24 | **是** | 自訂時段的起訖小時,只在 `custom` 時使用 |
| `work_type` | `WorkType` | 否 | `"excavation"` | | 否 | 施工類型 |

### 5.4 `NetworkImpact`(P2 車流與行人影響的輸出)

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `affected_trips_pct` | number | 否 | 受影響的合成旅次比例,0–1。例如 0.16 代表 16%。等於 `rerouted_trips_pct` + `slowed_trips_pct` + `unreachable_trips_pct` |
| `avg_extra_min` | number | **是** | 改道或變慢旅次的平均增加時間(分鐘)= 繞遠路多花的時間(自由車流)+ 壅塞延誤(VicRoads 公布車流量經 BPR 容量曲線)。時段只透過每小時車流量影響結果,**不再乘上時段係數**。不含封閉後無路可走的旅次;沒有公布車流量的道路不計壅塞延誤,因此偏低估。公告四捨五入後使用,為 0 時公告不提 |
| `max_extra_min` | number | 否 | 最大增加時間(分鐘) |
| `time_factor` | number | 否 | 此時段每小時車流量相對日間(09:30–15:30)的比例,例如夜間約 0.26。**只供說明,不乘入延誤** |
| `full_closure` | `{[segment id]: boolean}` | **是** | 每段是否完全禁止車輛通行(true)或仍可通行的工區(false)。VMS 依此決定寫 `ROAD CLOSED` 或 `LANE CLOSED` |
| `rerouted_trips_pct` | number | 否 | 所有旅次中改走其他路線的比例。封閉後完全沒有路線可走的旅次不算在內 |
| `slowed_trips_pct` | number | 否 | 所有旅次中維持原路線但變慢的比例:經過工區,或行經吸收了繞行車流、變擁擠的街道 |
| `unreachable_trips_pct` | number | 否 | 封閉前有路線、封閉後在研究範圍內無路可走的旅次比例。算在 `affected_trips_pct` 內,不計入延誤統計;預設 0 |
| `segment_traffic` | `{[segment id]: SegmentTraffic}` | 否 | 每段仍通過的旅次比例與行車時間倍數 |
| `unmodelled_segments` | string[] | 否 | 位於研究範圍路網之外(單行道、死巷、匝道等)的路段 id,**其影響不在上述數字中**,前端需提示 |
| `load_increase` | `EdgeLoad[]` | **是** | 吸收繞行車流的街道,依影響大小排序。P5 取前 3 條的 `road_name` 寫入公告 |
| `ped_detour_m` | number \| null | 否 | 行人繞行增加的距離(公尺),各段取最長;只有封人行道時才有值 |
| `ped_detour_basis` | `footway` \| `street_centreline` \| null | 否 | `ped_detour_m` 的量測依據:`footway` 為 OSM 步行網路(人行道、巷弄、穿越道);`street_centreline` 為道路中心線,結果偏高估 |
| `closed_aadt` | `{[segment id]: AadtRef}` | 否 | 每段封閉道路上最繁忙路段的 VicRoads 公布年平均日交通量,只供顯示;沒有公布數據的路段不會出現。**刻意不放入事實表**,數字防護會擋下公告中的這些數字 |
| `sensitive_facilities` | `Facility[]` | 否(預留) | 工區旁或繞行路線附近的醫院、學校、消防站 |
| `is_demo_data` | boolean | 否 | 是否使用示範路網。為 true 時結果不代表真實道路 |
| `note` | string | 否 | 方法說明:旅次為合成;延誤來自公布車流量與 BPR 容量曲線,單次指派、不重新選路,只適用有公布車流量的道路 |

**`SegmentTraffic`**:`through_trips_pct`(仍開車通過這段的旅次比例,全封時為 0)、`slowdown_factor`(行車時間倍數;`null` 表示禁止車輛通行,1 表示不變)。

**`EdgeLoad`(一條吸收繞行車流的街道)**

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `edge` | `[int, int, int]` | 否 | OSM 路段編號 |
| `road_name` | string \| null | **是** | 街道名稱 |
| `delta` | number | 否 | 被影響的旅次中,有多少比例會多經過這條街,0–1 |
| `geometry` | `[lat, lng][]` | 否 | 路段座標 |
| `aadt` | `AadtRef` \| null | 否 | 這條街的 VicRoads 公布交通量,只供顯示 |

**`AadtRef`(一筆公布的交通量,只查表、不計算)**:`aadt`(年平均日交通量)、`heavy`(其中重車數,可為 null)、`year`(資料年份,目前最新為 2019)、`direction`(公布的行車方向)、`both_directions`(是否為雙向合計)、`section`(路段描述)、`method`(`Actual` 實測或 `Estimated` 估計)、`match_confidence`(與 OSM 路段配對的信心)、`source`(資料來源)。

**`Facility`(敏感設施)**

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `name` | string | 設施名稱 |
| `kind` | string | 類型:`hospital`、`school`、`fire_station` 等 |
| `lat` / `lng` | number | 位置 |
| `near` | `works` \| `detour` \| null | 在工區旁,或在繞行街道旁 |

### 5.5 `TransitImpact`(P3 大眾運輸的輸出)

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `routes` | `AffectedRoute[]` | **是** | 行經封閉路段的路線 |
| `stops` | `NearbyStop[]` | 否 | 封閉路段附近的站牌 |
| `is_demo_data` | boolean | 否 | 沒有載入 GTFS 資料時為 true:示範路網上是示範路線,真實路網上則沒有路線 |
| `note` | string \| null | 否 | 例如為什麼完全沒有路線 |

**`AffectedRoute`(受影響路線)**

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `route_id` | string | 否 | GTFS 路線編號 |
| `short_name` | string | **是** | 路線顯示名稱,例如電車路線號碼。寫入公告 |
| `mode` | `tram` \| `bus` \| `train` \| `other` | 否 | 運具種類 |
| `needs_replacement` | boolean | **是** | 是否需要替代接駁(電車遇到全封時為 true)。為 true 時公告會加註替代公車 |

**`NearbyStop`(附近站牌)**:`stop_id`(站牌編號)、`name`(站名)、`lat` / `lng`(位置)、`distance_m`(距封閉路段最近處的公尺數)、`routes`(停靠此站的路線名稱)。有受影響路線時,只列這些路線的站牌(沒有路線資料的站牌仍會列出)。

`note` 只在真實路網上沒有 GTFS 資料時出現:此時不產生示範路線,`routes` 為空,`is_demo_data` 為 true。

### 5.6 `EquipmentResult`(P4 器材清單的輸出)

| 欄位 | 型別 | P5 讀取 | 說明 |
| --- | --- | --- | --- |
| `items` | `EquipmentItem[]` | 否 | 器材明細。多段時 `reason` 以 `Segment <id>:` 開頭,與地圖上的標示一致 |
| `total_cost_aud` | number | 否 | 預估租金總額(澳幣) |
| `shortages` | string[] | 否 | 庫存不足的品項名稱。**不會出現在民眾公告** |
| `warnings` | string[] | 否 | 規劃警告,例如依 AGTTM Table 2.4 此時段剩餘車道不足以承載車流。多段時以 `Segment <id>:` 開頭。**不會出現在民眾公告** |
| `rules_verified` | boolean | 否 | 規則數值是否已對照法規驗證 |
| `disclaimer` | string | 否 | 免責說明 |

**`EquipmentItem`**:`item_id`(品項代碼)、`name`(品項名稱)、`supplier`(`RPM` 表示 RPM Hire 可出租,`other` 表示需向其他廠商租用,null 表示未標示)、`qty`(數量)、`reason`(為什麼需要這個數量)、`stock`(場站庫存)、`in_stock`(庫存是否足夠)、`daily_rate_aud`(日租金)、`cost_aud`(此行總租金 = 數量 × 日租金 × 工期)。

### 5.7 `CommsRequest`(`/api/comms` 的請求)

| 欄位 | 型別 | 必填 | 說明 |
| --- | --- | --- | --- |
| `scenario` | `ScenarioParams` | 是 | 目前的施工方案 |
| `network` | `NetworkImpact` \| null | 否 | P2 的結果;沒有時公告不提延誤與繞行街道 |
| `transit` | `TransitImpact` \| null | 否 | P3 的結果;沒有時公告不提大眾運輸 |
| `equipment` | `EquipmentResult` \| null | 否 | P4 的結果;只進內部 facts 和 equipment explanation,不進民眾公告或 LLM prompt |

### 5.8 `Comms`(`/api/comms` 的回應)

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `vms_messages` | `string[][]` | VMS 看板訊息。外層每個元素是一則訊息(一個畫面),內層每個字串是一行。官方規則:每個畫面最多 `VMS_WORDS_PER_SCREEN` 個 words/numbers,alternating series 最多 `VMS_MAX_SCREENS` 個畫面。草案顯示限制仍保留:每則最多 `VMS_LINES` 行、每行最多 `VMS_CHARS_PER_LINE` 字元;長單字或長路名 token 不會被截斷 |
| `public_notice_md` | string | 民眾公告,Markdown 格式(`#` 標題、`**粗體**`、每個路段一個 `-` 項目) |
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
| `fields` | `ParsedFields` | 可預填的欄位,都已通過驗證;找不到的欄位為 `null` |
| `missing` | string[] | 句子裡沒提到或值不合法、需要使用者自己填的欄位名稱(只會是 `ParsedFields` 的欄位) |

**`ParsedFields`**(可被預填的欄位白名單)

| 欄位 | 型別 | 套用到 | 說明 |
| --- | --- | --- | --- |
| `road_name` | string \| null | 不套用 | 句子裡的道路名稱,只作提示 |
| `targets` | `ClosureTarget[]` \| null | 編輯中的路段 | 至少一項;空陣列視為不合法,列入 `missing` |
| `direction` | string \| null | 編輯中的路段 | 見 5.1 |
| `lanes_closed` | int \| null | 編輯中的路段 | 1–4 |
| `start_date` | date \| null | 方案 | 相對日期(例如 next Tuesday)以今天推算 |
| `duration_days` | int \| null | 方案 | 1–365 |
| `time_window` | `TimeWindow` \| null | 方案 | 為 `custom` 時,前端沿用或補上預設 `custom_hours` |
| `work_type` | `WorkType` \| null | 方案 | |

**刻意不預填**:`segments`(位置)、`speed_limit_kmh`、`custom_hours`、`name`。位置必須由使用者在地圖上畫,速限必須來自地圖資料或使用者輸入。

## 6. 事實表:AI 可用的事實

由 `build_facts()` 產生,是 P5 內部最重要的資料結構。**公告與 VMS 中出現的每一個數字,都必須能在這張表裡找到。** 只使用已畫好的路段(`edges` 非空)。

| 欄位 | 型別 | 來源 | 說明 |
| --- | --- | --- | --- |
| `road` | string | 各路段的 `road_name` | 不重複的道路名稱以 ` and ` 串接;都沒有時為 `the work site` |
| `start` | string | `scenario.start_date` | 開工日期,英文完整格式,例如 `Tuesday 6 October 2026` |
| `end` | string | `start_date + duration_days - 1` | 完工日期 |
| `hours` | string \| null | `scenario.time_window`、`custom_hours` | 每日施工時段文字,例如 `9:30am to 3:30pm` |
| `duration_days` | int | `scenario.duration_days` | 工期天數 |
| `closures` | `{segment_id, road, closed, direction}[]` | 每個已畫好的路段 | 每段一筆:路段 id、道路名稱、封閉對象的英文描述、方向。讓每個封閉對象跟著自己的道路與方向 |
| `avg_extra_min` | int | `network.avg_extra_min` 四捨五入 | 平均增加分鐘數;沒有 `network` 時不存在 |
| `detour_streets` | string[] | `network.load_increase` 前 3 名 | 預期車流增加的街道名稱 |
| `unmodelled_segments` | string[] | `network.unmodelled_segments` | 交通模型未涵蓋的封閉路段 id;公開公告只作限制說明,不轉成影響數字 |
| `closed_aadt` | object | `network.closed_aadt` | 內部/debug facts。公開公告與 LLM prompt 會移除 |
| `unreachable_trips_pct` | number | `network.unreachable_trips_pct` | 內部/debug facts。公開公告與 LLM prompt 會移除 |
| `routes` | string[] | `transit.routes[].short_name` | 受影響的大眾運輸路線 |
| `replacement_needed` | boolean | `transit.routes[].needs_replacement` | 是否需要替代接駁 |
| `equipment` | object | `equipment` | 內部/debug facts,含 items、supplier、warnings、shortages、cost。公開公告與 LLM prompt 會移除 |

## 7. P5 的承諾與限制

**P5 承諾**

1. 不計算、不修改任何數量或影響數字。
2. `/api/comms` 在 LLM 失敗時一定退回範本,不回錯誤。
3. 所有公告都附免責說明,並標示 `generated_by`。
4. 產生公告時,送給 LLM 的只有 public notice facts 與範本初稿;預填時只送出使用者輸入的那句話與今天日期。兩者都不會送出座標、路段編號、器材數量、庫存或成本。
5. `/api/parse` 只回傳 `ParsedFields` 裡的欄位,且每個都已驗證。

**其他模組需配合**

1. **P1**:呼叫 `/api/comms` 時,盡量把 `network`、`transit` 的最新結果一起帶上;`/api/parse` 的結果只能當預填值,且只套用 `ParsedFields` 列出的欄位。
2. **P2、P3、P4**:第 5 節中標示「P5 讀取:是」的欄位,改名、改型別或改意義前,先在群組通知 P5,並依第 8 節流程更新。

**設定參數**(`backend/.env` 與 `backend/app/config.py`)

| 參數 | 預設值 | 說明 |
| --- | --- | --- |
| `GEMINI_API_KEY` | 空 | 設定後才會啟用一句話預填與 AI 潤飾公告 |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | 使用的模型 |
| `LLM_PROVIDER` | `gemini` | 設為 `none` 可強制只用範本(例如 Demo 現場網路不穩時) |
| `VMS_MAX_SCREENS` | 2 | 官方 screen 規則:alternating series 最多 2 個畫面 |
| `VMS_WORDS_PER_SCREEN` | 4 | 官方 screen 規則:每個畫面最多 4 個 words/numbers |
| `VMS_LINES` | 3 | VMS 每則訊息的草案顯示行數(**TODO_VERIFY:待向 RPM Hire 確認實際硬體格式**) |
| `VMS_CHARS_PER_LINE` | 12 | VMS 每行草案顯示字元數(**TODO_VERIFY:待向 RPM Hire 確認實際硬體格式**) |

## 8. 變更流程

任何欄位的新增、改名或改型別,都要在**同一個 PR** 裡同時更新以下三處:

1. `backend/app/schemas.py`(後端正式定義)
2. `frontend/src/types.ts`(前端型別,必須與後端一致)
3. 本文件的對應表格,並更新文件開頭的契約版本號

新增欄位且有預設值,屬於相容變更,版本號升第二位(例如 v0.1 → v0.2)。改名、刪除或改型別屬於不相容變更,需要 P1 與 P5 都在 PR 上確認後才能合併。

本文件是共用規格,**必須 commit 在 `docs/api/`**,不可加入 `.gitignore`,也不可只留本機副本。

## 9. 自我測試

```bash
cd backend
pytest -q                                   # 全部測試,含 P5 的數字防護與預填白名單測試

# 取得示範方案,再產生溝通草稿
curl -s http://127.0.0.1:8000/api/demo-scenario > /tmp/s.json
curl -s -X POST http://127.0.0.1:8000/api/comms \
  -H 'Content-Type: application/json' \
  -d "{\"scenario\": $(cat /tmp/s.json)}"
```

P5 相關的測試位於 `backend/tests/test_api.py` 的 `/api/comms`、`/api/comms/facts`、`/api/parse` 和 VMS/數字防護案例;`backend/tests/test_llm_facts.py` 的 segment facts、equipment facts、public prompt isolation、LLM fallback、`LLM_PROVIDER=none` 和 VMS wording/limit 測試;以及 `backend/tests/test_demo_integration.py` 的固定 demo template-mode 端到端測試。

## 版本紀錄

| 版本 | 內容 |
| --- | --- |
| v0.5 | 相容變更,新增欄位皆有預設值;P1–P4 已全部合併到 main。**P2**:`NetworkImpact` 新增 `unreachable_trips_pct`、`ped_detour_basis`、`closed_aadt`,`EdgeLoad` 新增 `aadt`(`AadtRef`);`NetworkRequest` 新增 `custom_hours`,`SegmentClosure.lanes_closed` 限 1–4。**P5 讀取欄位的意義變更(依第 8 節須通知 P5)**:`avg_extra_min` 改為繞路時間 + 壅塞延誤,不再乘上時段係數;`time_factor` 改為僅供說明的車流量比例;`slowed_trips_pct` 也包含行經擁擠街道而變慢的旅次。**P3**:`NearbyStop` 新增 `routes`;真實路網上無 GTFS 時不再產生示範路線。**P4**:`EquipmentItem` 新增 `supplier`,`EquipmentResult` 新增 `warnings`,器材與配置請求新增 `custom_hours`。**P5**:LLM provider 改為 Gemini;`LLM_PROVIDER=none` 強制範本;`/api/comms/facts` 定位為 internal/debug facts;公開公告與 LLM prompt 會排除 equipment、closed AADT、unreachable trip percent 等 internal-only facts;VMS 套用每畫面 4 個 words/numbers、最多 2 個畫面,並移除無事實支持的 `USE CAUTION`、`USE DETOUR`、`MERGE LEFT/RIGHT`;避免無支持的替代公車與出入承諾 |
| v0.4 | 相容變更,欄位不變。`/api/parse` 在 LLM 服務失敗時回 502(原為 500)。`ParsedFields.targets` 不接受空陣列。VMS 改讀 `network.full_closure` 與路段的 `lanes_closed`(兩者改標「P5 讀取:是」),不再對沒有車道可併入的路段顯示 `MERGE RIGHT`;用語仍沿用 scaffold。`avg_extra_min`、`max_extra_min`、`rerouted_trips_pct`、`slowed_trips_pct` 不再計入封閉後無路可走的旅次 |
| v0.3 | **不相容變更。** 位置與封閉設定從方案層級移到 `segments[]`:移除 `location`、`targets`、`direction`、`lanes_closed`、`work_length_m`(改為各段的 `length_m`)、`speed_limit_kmh`(移到各段)。事實表的 `closures` 改為每段一筆,並移除 `direction`。`ParseResult.fields` 改為有型別的 `ParsedFields`(`road_hint` 併入 `fields.road_name`)。`NetworkImpact` 新增 `full_closure`、`rerouted_trips_pct`、`slowed_trips_pct`、`segment_traffic`、`unmodelled_segments`,移除 `closed_geometry`。v0.1 草案中的 `/api/comms/facts` 尚未實作,先從規格移除。VMS 不再截斷行或路名(`FLEMINGTON` → `FLEMINGTON RD`);VMS 用語沿用 scaffold,P5 分支的畫面規則(每畫面最多 4 個字、最多 2 個交替畫面)會在共用變更合併後移植 |
| v0.2 | `Location.edge` 改為 `waypoints` 與 `edges`,可封閉多段連續路段(不相容變更) |
| v0.1 | 初版 |
