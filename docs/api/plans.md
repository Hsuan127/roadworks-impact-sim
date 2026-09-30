# 共用方案與留言(Shared plans & comments)API 介面規格

| 項目 | 內容 |
| --- | --- |
| 契約版本 | v0.1(2026-09-30) |
| 程式碼 | `backend/app/plans.py`、`backend/app/schemas.py`、`frontend/src/types.ts`、`frontend/src/hooks/useSharedPlan.ts`、`frontend/src/components/People.tsx`、`frontend/src/components/CommentsPanel.tsx` |
| P5 reads | **no** |

## 1. 目的與限制

封路規劃通常不是一個人完成:負責其他路段的人把自己的 segments 加到**同一個**方案,主管或夥伴不畫線也能直接留言。

這是**輕量版**,不是即時共同編輯器:
- 方案存在伺服器記憶體,重啟即消失。
- **最後寫入者勝出(last write wins)**。每個開著的畫面每 2 秒輪詢;使用者停止編輯 1.5 秒後才套用別人的新版本。
  兩人在同一個 2 秒內都修改時,後送出的會覆蓋前者(例如另一人剛加的 segment 可能被蓋掉)。
- 沒有登入;名字存在瀏覽器 localStorage,顏色由名字決定。

## 2. 方案

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| POST | `/api/plans` | body `SharedPlanWrite` `{scenarios: ScenarioParams[1..2], author: Person}` → `SharedPlan`。前端的 **Share** 按鈕 |
| GET | `/api/plans/{id}?who=&color=` | 讀取;帶 `who`、`color` 表示「我在看」,用於線上人員 |
| PUT | `/api/plans/{id}` | body 同 POST,整份覆蓋,`version` + 1 |

`SharedPlan`:`id`、`version`、`scenarios`、`updated_by: Person`、`updated_at`、`viewers: Person[]`(最近 8 秒內輪詢過的人)。
`Person`:`name`(1–40 字)、`color`(`#RRGGBB`)。

前端網址 `/?plan=<id>` 開啟共用方案。`Segment.owner` 記錄畫這段的人。

## 3. 留言

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| GET | `/api/plans/{id}/comments` | 全部留言(依時間) |
| POST | `/api/plans/{id}/comments` | `{author, plan: "A", segment_id: string \| null, text}`;`segment_id` 為 null 表示針對整個方案 |
| PATCH | `/api/plans/{id}/comments/{cid}?resolved=true` | 標記已處理 / 重新開啟 |

找不到方案或留言時回 404。
