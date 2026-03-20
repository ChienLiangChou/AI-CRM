# SKC Agent OS 系統組織介紹

> 供外部或新成員快速了解系統架構、模組與資料流。最後更新：2025-03。

---

## 1. 系統定位

**SKC Agent OS** 是一套以房地產經紀／投資為場景的營運系統，整合 AI 輔助（Gemini LLM、inference.sh）與 Web Push 通知，支援買方、賣方、投資人、房東、房客等多種客戶類型。

目前 repo 與部分技術識別仍保留 `ai-crm` 命名，以避免部署與程式碼風險；本文件先更新對外/產品層命名。

---

## 2. 技術架構總覽

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React + Vite)                    │
│  Dashboard │ Contacts │ Pipeline │ Prospector (Leads)              │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    │ REST API (axios)
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI + Python 3.13)                │
│  CRUD │ AI Logic │ Workflows │ Push Notifications │ Background   │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    │ SQLAlchemy ORM
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SQLite (持久化於 /data 或本地)                 │
└─────────────────────────────────────────────────────────────────┘
```

- **前端**：React 19、Vite 7、Tailwind、React Router、Lucide Icons
- **後端**：FastAPI、SQLAlchemy、Pydantic、Uvicorn
- **AI**：Google Gemini 2.0 Flash Lite、inference.sh（部分功能）
- **部署**：Render（`render.yaml`），後端掛載 1GB 磁碟存 SQLite

---

## 3. 目錄結構

```
ai-crm/
├── frontend/                    # React SPA
│   ├── src/
│   │   ├── App.tsx              # 路由：/dashboard, /contacts, /pipeline, /find-leads
│   │   ├── components/          # Layout, ContactModal, AddContactModal, NotificationToggle
│   │   ├── pages/               # Dashboard, Contacts, Pipeline, Prospector
│   │   └── services/            # api.ts (crmService), pushNotifications.ts
│   ├── public/                  # sw.js (Service Worker), manifest.json, icons
│   └── vite.config.ts
│
├── backend/
│   └── app/
│       ├── main.py              # FastAPI 應用、路由、CORS、lifespan
│       ├── database.py          # SQLite engine、SessionLocal、get_db
│       ├── models.py            # ORM 模型
│       ├── schemas.py           # Pydantic 請求/回應 schema
│       └── crud.py              # 業務邏輯、AI 呼叫、Push 發送
│
├── render.yaml                  # Render 部署設定
└── SYSTEM_OVERVIEW.md           # 本文件
```

---

## 4. 核心資料模型

| 模型 | 用途 |
|------|------|
| **PipelineStage** | 銷售階段（如 Lead、Qualified、Proposal、Closed） |
| **Contact** | 客戶／潛在客戶，含 client_type、budget、preferred_areas、lead_score、mood_score、ai_summary 等 |
| **Property** | 房產，含地址、類型、狀態、財務指標、owner/tenant 關聯 |
| **Interaction** | 互動紀錄，支援 AI 解析 intent、sentiment、entities、suggested_action |
| **PushSubscription** | Web Push 訂閱（endpoint、p256dh、auth） |

關聯：`Contact` ↔ `PipelineStage`（多對一）、`Contact` ↔ `Interaction`（一對多）、`Contact` ↔ `Property`（owner/tenant）。

---

## 5. API 模組劃分

### 5.1 基礎 CRUD

| 路徑 | 功能 |
|------|------|
| `/api/stages` | Pipeline 階段 CRUD |
| `/api/contacts` | 聯絡人 CRUD、`PATCH /contacts/{id}/stage` 更新階段 |
| `/api/contacts/{id}/interactions` | 互動紀錄 CRUD |
| `/api/properties` | 房產 CRUD |

### 5.2 AI 功能

| 路徑 | 功能 |
|------|------|
| `GET /api/smart-search?q=` | 智慧搜尋（關鍵字、warm/cold 等語意） |
| `POST /api/contacts/{id}/draft-email` | 依聯絡人產生跟進郵件草稿 |
| `POST /api/contacts/{id}/enrich` | 依公司/姓名做 AI 背景補充 |
| `POST /api/prospector/scout` | 依查詢產生潛在客戶並寫入 DB |

### 5.3 AI Dashboard 智慧

| 路徑 | 功能 |
|------|------|
| `GET /api/dashboard/nudges` | 產生待跟進提醒（nudges） |
| `GET /api/dashboard/segments` | 自動分群（RFM、階段等） |
| `GET /api/dashboard/insights` | Pipeline 洞察、瓶頸、建議 |

### 5.4 工作流程（Workflows）

| 路徑 | 功能 |
|------|------|
| `POST /api/workflow/voice-memo` | 語音備忘錄 → 解析 → 建立/更新聯絡人、產生郵件草稿 |
| `POST /api/workflow/market-trigger` | 市場事件觸發 → 找出投資人、產生草稿 |
| `POST /api/workflow/maintenance-report` | 租客維修回報 → 解析、回覆租客、通知廠商 |

### 5.5 Push 通知

| 路徑 | 功能 |
|------|------|
| `GET /api/push/vapid-public-key` | 取得 VAPID 公鑰 |
| `POST /api/push/subscribe` | 儲存訂閱 |
| `DELETE /api/push/unsubscribe` | 取消訂閱 |
| `POST /api/push/test` | 測試推播 |
| `POST /api/push/check-nudges` | 手動觸發 follow-up nudge 檢查 |

---

## 6. 背景任務

- **Nudge Loop**：每 30 分鐘執行 `check_and_send_followup_nudges`，對逾期未跟進的聯絡人發送 Web Push。
- 實作於 `main.py` 的 `lifespan`，以 `asyncio.create_task` 啟動。

---

## 7. 前端頁面與導覽

| 路徑 | 頁面 | 說明 |
|------|------|------|
| `/` | 重導向 | 自動導向 `/dashboard` |
| `/dashboard` | Dashboard | Nudges、Segments、Pipeline Insights |
| `/contacts` | Contacts | 聯絡人列表、新增/編輯、互動紀錄 |
| `/pipeline` | Pipeline | 看板式階段管理、拖曳更新階段 |
| `/find-leads` | Prospector | AI 潛在客戶搜尋與匯入 |

側邊欄含 NotificationToggle（Push 訂閱開關）與使用者資訊區塊。

---

## 8. 環境變數（後端）

| 變數 | 用途 |
|------|------|
| `GOOGLE_API_KEY` | Gemini API（AI 功能） |
| `VAPID_PUBLIC_KEY` | Web Push 公鑰 |
| `VAPID_PRIVATE_KEY` | Web Push 私鑰（發送用，不暴露給前端） |

前端透過 `VITE_API_URL` 指定 API 基底 URL（預設 `http://localhost:8000/api`）。

---

## 9. 關鍵依賴

**Backend**：fastapi、sqlalchemy、pydantic、uvicorn、python-dotenv、google-generativeai、pywebpush、inferencesh

**Frontend**：react、react-router-dom、axios、lucide-react、tailwindcss

---

## 10. 快速啟動

```bash
# 後端
cd backend && uvicorn app.main:app --reload

# 前端
cd frontend && npm run dev
```

預設：前端 `http://localhost:5173`，後端 `http://localhost:8000`。
