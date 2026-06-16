from contextlib import asynccontextmanager
import asyncio
import os
import logging

from fastapi import FastAPI, Depends, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session
from typing import List, Optional

from . import crud, gmail_service, models, schemas
from .database import engine, get_db, SessionLocal

logger = logging.getLogger(__name__)

models.Base.metadata.create_all(bind=engine)
crud.ensure_database_schema(engine)


async def _nudge_loop():
    """Background task: check for follow-up nudges every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        try:
            db = SessionLocal()
            result = crud.check_and_send_followup_nudges(db)
            if result["sent"]:
                logger.info(f"Sent {result['sent']} push notifications for {result['contacts']}")
            db.close()
        except Exception as e:
            logger.error(f"Nudge loop error: {e}")


async def _watchlist_loop():
    """Background task: run due listing/client watchlists every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        if os.getenv("WATCHLIST_SCHEDULER_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
            continue
        try:
            db = SessionLocal()
            result = crud.run_due_watchlists(db)
            if result["checked"]:
                logger.info(
                    "Watchlist loop checked %s watchlist(s), created %s alert(s)",
                    result["checked"],
                    result["created_alerts"],
                )
            db.close()
        except Exception as e:
            logger.error(f"Watchlist loop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    nudge_task = asyncio.create_task(_nudge_loop())
    watchlist_task = asyncio.create_task(_watchlist_loop())
    yield
    nudge_task.cancel()
    watchlist_task.cancel()

app = FastAPI(title="AI CRM API", lifespan=lifespan)

# Allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to AI CRM API"}


# --- Pipeline Stages ---
@app.get("/api/stages", response_model=List[schemas.PipelineStage])
def read_stages(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    stages = crud.get_stages(db, skip=skip, limit=limit)
    return stages

@app.post("/api/stages", response_model=schemas.PipelineStage)
def create_stage(stage: schemas.PipelineStageCreate, db: Session = Depends(get_db)):
    return crud.create_stage(db=db, stage=stage)

# --- Contacts ---
@app.post("/api/contacts", response_model=schemas.Contact)
def create_contact(contact: schemas.ContactCreate, db: Session = Depends(get_db)):
    return crud.create_contact(db=db, contact=contact)

@app.get("/api/contacts", response_model=List[schemas.Contact])
def read_contacts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    contacts = crud.get_contacts(db, skip=skip, limit=limit)
    return contacts

@app.get("/api/voice-memo/legacy-review", response_model=schemas.LegacyVoiceMemoReviewResponse)
def read_legacy_voice_memo_review(db: Session = Depends(get_db)):
    return crud.get_legacy_voice_memo_reviews(db)

@app.get("/api/contacts/{contact_id}", response_model=schemas.Contact)
def read_contact(contact_id: int, db: Session = Depends(get_db)):
    db_contact = crud.get_contact(db, contact_id=contact_id)
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

@app.put("/api/contacts/{contact_id}", response_model=schemas.Contact)
def update_contact(contact_id: int, contact: schemas.ContactUpdate, db: Session = Depends(get_db)):
    db_contact = crud.update_contact(db=db, contact_id=contact_id, contact=contact)
    if db_contact is None:
         raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

@app.delete("/api/contacts/{contact_id}", response_model=schemas.Contact)
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    db_contact = crud.delete_contact(db=db, contact_id=contact_id)
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact

# --- Interactions ---
@app.post("/api/contacts/{contact_id}/interactions", response_model=schemas.Interaction)
def create_contact_interaction(contact_id: int, interaction: schemas.InteractionCreate, db: Session = Depends(get_db)):
    db_contact = crud.get_contact(db, contact_id=contact_id)
    if not db_contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return crud.create_contact_interaction(db=db, contact_id=contact_id, interaction=interaction)

@app.get("/api/contacts/{contact_id}/interactions", response_model=List[schemas.Interaction])
def read_contact_interactions(contact_id: int, db: Session = Depends(get_db)):
    db_contact = crud.get_contact(db, contact_id=contact_id)
    if not db_contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return crud.get_contact_interactions(db=db, contact_id=contact_id)

@app.patch("/api/contacts/{contact_id}/stage", response_model=schemas.Contact)
def update_contact_stage(contact_id: int, req: schemas.StageUpdateRequest, db: Session = Depends(get_db)):
    db_contact = crud.update_contact_stage(db=db, contact_id=contact_id, stage_id=req.stage_id)
    if not db_contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return db_contact


@app.post("/api/contacts/{contact_id}/qualify", response_model=schemas.LeadQualificationResponse)
def qualify_contact(contact_id: int, db: Session = Depends(get_db)):
    result = crud.qualify_contact(db=db, contact_id=contact_id)
    if not result:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result

# --- AI Features ---
@app.get("/api/smart-search", response_model=schemas.SmartSearchResult)
def smart_search(q: str, db: Session = Depends(get_db)):
    return crud.perform_smart_search(db=db, query=q)

@app.post("/api/contacts/{contact_id}/draft-email", response_model=schemas.EmailDraftResponse)
def draft_email(contact_id: int, db: Session = Depends(get_db)):
    res = crud.draft_follow_up_email(db, contact_id)
    if not res:
        raise HTTPException(status_code=404, detail="Contact not found")
    return res


@app.get("/api/gmail/oauth/status", response_model=schemas.GmailOAuthStatusResponse)
def gmail_oauth_status(db: Session = Depends(get_db)):
    return gmail_service.get_gmail_oauth_status(db)


@app.post("/api/gmail/oauth/start", response_model=schemas.GmailOAuthStartResponse)
def gmail_oauth_start(db: Session = Depends(get_db)):
    try:
        return gmail_service.start_gmail_oauth(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/gmail/oauth/callback", response_class=HTMLResponse)
def gmail_oauth_callback(state: str, code: str, db: Session = Depends(get_db)):
    try:
        status = gmail_service.handle_gmail_oauth_callback(db, state=state, code=code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    account = status.account_email or status.gmail_user_id
    return f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 32px;">
        <h2>Gmail connected</h2>
        <p>SKC Agent OS is connected to <strong>{account}</strong>.</p>
        <p>You can close this tab and return to the dashboard.</p>
      </body>
    </html>
    """


@app.get("/api/agents/listing-alert-recommendation/gmail/oauth/callback", response_class=HTMLResponse)
def gmail_oauth_legacy_callback(state: str, code: str, db: Session = Depends(get_db)):
    return gmail_oauth_callback(state=state, code=code, db=db)


@app.post("/api/gmail/oauth/disconnect", response_model=schemas.GmailOAuthStatusResponse)
def gmail_oauth_disconnect(db: Session = Depends(get_db)):
    return gmail_service.disconnect_gmail_oauth(db)


@app.get("/api/email-drafts/pending", response_model=schemas.PendingEmailDraftsResponse)
def pending_email_drafts(db: Session = Depends(get_db)):
    return gmail_service.list_pending_email_drafts(db)


@app.post("/api/email-drafts/{interaction_id}/gmail-draft", response_model=schemas.GmailDraftActionResponse)
def create_gmail_draft(
    interaction_id: int,
    req: schemas.GmailDraftActionRequest,
    db: Session = Depends(get_db),
):
    try:
        return gmail_service.create_gmail_draft_for_interaction(
            db,
            interaction_id,
            subject_override=req.subject,
            body_override=req.body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/email-drafts/{interaction_id}/send", response_model=schemas.GmailDraftActionResponse)
def send_gmail_draft(
    interaction_id: int,
    req: schemas.GmailDraftActionRequest,
    db: Session = Depends(get_db),
):
    try:
        return gmail_service.send_gmail_draft_for_interaction(
            db,
            interaction_id,
            confirm_send=bool(req.confirm_send),
            review_confirmation=req.review_confirmation,
            subject_override=req.subject,
            body_override=req.body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.post("/api/contacts/{contact_id}/enrich", response_model=schemas.EnrichProfileResponse)
def enrich_profile(contact_id: int, db: Session = Depends(get_db)):
    res = crud.enrich_contact_profile(db, contact_id)
    if not res:
         raise HTTPException(status_code=404, detail="Contact not found")
    return res

@app.post("/api/prospector/scout", response_model=schemas.ScoutResponse)
def scout_for_leads(req: schemas.ScoutRequest, db: Session = Depends(get_db)):
    return crud.scout_leads(db, req.query)

# --- AI Dashboard Intelligence ---
@app.get("/api/dashboard/nudges", response_model=schemas.NudgesResponse)
def get_smart_nudges(db: Session = Depends(get_db)):
    return crud.generate_smart_nudges(db)

@app.get("/api/dashboard/segments", response_model=schemas.SegmentsResponse)
def get_segments(db: Session = Depends(get_db)):
    return crud.auto_segment_contacts(db)

@app.get("/api/dashboard/insights", response_model=schemas.PipelineInsightsResponse)
def get_pipeline_insights(db: Session = Depends(get_db)):
    return crud.generate_pipeline_insights(db)

# --- Properties ---
@app.get("/api/properties", response_model=List[schemas.Property])
def read_properties(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_properties(db, skip=skip, limit=limit)


@app.get("/api/properties/import-template.csv")
def property_import_template():
    return Response(
        content=crud.build_property_csv_template(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="skc-watchlist-import-template.csv"'},
    )


@app.get("/api/properties/{property_id}", response_model=schemas.Property)
def read_property(property_id: int, db: Session = Depends(get_db)):
    prop = crud.get_property(db, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop

@app.post("/api/properties", response_model=schemas.Property)
def create_property(prop: schemas.PropertyCreate, db: Session = Depends(get_db)):
    return crud.create_property(db=db, prop=prop)


@app.get("/api/property-source/status", response_model=schemas.PropertySourceStatus)
def property_source_status(db: Session = Depends(get_db)):
    return crud.get_property_source_status(db)


@app.get("/api/property-feed/config", response_model=schemas.PropertyFeedConfig)
def property_feed_config(db: Session = Depends(get_db)):
    return crud.get_property_feed_config(db)


@app.patch("/api/property-feed/config", response_model=schemas.PropertyFeedConfig)
def update_property_feed_config(update: schemas.PropertyFeedConfigUpdate, db: Session = Depends(get_db)):
    try:
        return crud.update_property_feed_config(db, update)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/properties/import-csv", response_model=schemas.PropertyImportResult)
async def import_properties_csv(
    dry_run: bool = False,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    try:
        csv_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = raw.decode("latin-1")
    return crud.import_properties_csv(db, csv_text, dry_run=dry_run)


@app.post("/api/properties/import-csv-folder", response_model=schemas.CsvDropFolderImportResult)
def import_properties_csv_folder(
    dry_run: bool = False,
    max_files: int = 10,
    db: Session = Depends(get_db),
):
    return crud.import_properties_csv_drop_folder(db, dry_run=dry_run, max_files=max_files)


@app.post("/api/properties/import-feed-text", response_model=schemas.PropertyImportResult)
def import_properties_feed_text(req: schemas.PropertyFeedImportRequest, db: Session = Depends(get_db)):
    return crud.import_properties_feed_text(db, req.text, dry_run=bool(req.dry_run))


@app.post("/api/properties/import-reso-json", response_model=schemas.PropertyImportResult)
def import_properties_reso_json(req: schemas.PropertyResoJsonImportRequest, db: Session = Depends(get_db)):
    return crud.import_properties_reso_json(db, req.data, dry_run=bool(req.dry_run))


@app.post("/api/properties/import-gmail-feed", response_model=schemas.PropertyImportResult)
def import_properties_gmail_feed(req: schemas.GmailPropertyFeedImportRequest, db: Session = Depends(get_db)):
    if not crud.gmail_feed_read_authorized(db, req.gmail_read_confirmation):
        raise HTTPException(status_code=400, detail="gmail_feed_read_confirmation_required")

    try:
        messages = gmail_service.fetch_property_feed_messages(
            db,
            query=req.query,
            max_results=req.max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    feed_text = "\n\n".join(
        "\n".join(
            part for part in [
                f"Subject: {message.get('subject') or ''}",
                f"From: {message.get('from') or ''}",
                f"Snippet: {message.get('snippet') or ''}",
                message.get("body") or "",
            ]
            if part.strip()
        )
        for message in messages
    )
    if not feed_text.strip():
        result = schemas.PropertyImportResult(
            success=False,
            message="No Gmail listing feed messages matched this query.",
            dry_run=bool(req.dry_run),
            created=0,
            updated=0,
            skipped=0,
            total_rows=0,
            errors=["gmail_feed_no_messages"],
        )
    else:
        result = crud.import_properties_feed_text(db, feed_text, dry_run=bool(req.dry_run))
    if not req.dry_run:
        crud.record_property_feed_import_result(db, result)
    return result


@app.put("/api/properties/{property_id}", response_model=schemas.Property)
def update_property(property_id: int, prop: schemas.PropertyUpdate, db: Session = Depends(get_db)):
    db_prop = crud.update_property(db=db, property_id=property_id, prop=prop)
    if not db_prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return db_prop

@app.delete("/api/properties/{property_id}", response_model=schemas.Property)
def delete_property(property_id: int, db: Session = Depends(get_db)):
    db_prop = crud.delete_property(db=db, property_id=property_id)
    if not db_prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return db_prop

# --- Client Watchlists / Listing Alerts ---
@app.get("/api/watchlists", response_model=List[schemas.ClientWatchlist])
def read_watchlists(contact_id: Optional[int] = None, db: Session = Depends(get_db)):
    return crud.get_watchlists(db, contact_id=contact_id)


@app.get("/api/watchlists/source-setups", response_model=List[schemas.WatchlistSourceSetup])
def read_watchlist_source_setups(contact_id: Optional[int] = None, db: Session = Depends(get_db)):
    return crud.get_watchlist_source_setups(db, contact_id=contact_id)


@app.get("/api/watchlists/safety-status", response_model=schemas.WatchlistSafetyStatus)
def read_watchlist_safety_status(db: Session = Depends(get_db)):
    return crud.get_watchlist_safety_status(db, gmail_status=gmail_service.get_gmail_oauth_status(db))


@app.get("/api/watchlists/delivery-gates", response_model=schemas.WatchlistDeliveryGateList)
def read_watchlist_delivery_gates(db: Session = Depends(get_db)):
    return crud.get_watchlist_delivery_gates(db, gmail_status=gmail_service.get_gmail_oauth_status(db))


@app.get("/api/watchlists/readiness-report", response_model=schemas.WatchlistReadinessReport)
def read_watchlist_readiness_report(db: Session = Depends(get_db)):
    return crud.get_watchlist_readiness_report(db, gmail_status=gmail_service.get_gmail_oauth_status(db))


@app.get("/api/watchlists/data-intake-checklist", response_model=schemas.WatchlistDataIntakeChecklist)
def read_watchlist_data_intake_checklist(db: Session = Depends(get_db)):
    return crud.get_watchlist_data_intake_checklist(db)


@app.get("/api/watchlists/source-tasks", response_model=schemas.WatchlistSourceTaskList)
def read_watchlist_source_tasks(db: Session = Depends(get_db)):
    return crud.get_watchlist_source_tasks(db)


@app.get("/api/watchlists/launch-action-pack", response_model=schemas.WatchlistLaunchActionPack)
def read_watchlist_launch_action_pack(db: Session = Depends(get_db)):
    return crud.get_watchlist_launch_action_pack(db, gmail_status=gmail_service.get_gmail_oauth_status(db))


@app.get("/api/watchlists/operator-handoff", response_model=schemas.WatchlistOperatorHandoffStatus)
def read_watchlist_operator_handoff():
    return crud.get_watchlist_operator_handoff_status()


@app.get("/api/watchlists/source-kit.zip")
def watchlist_source_kit(db: Session = Depends(get_db)):
    filename, content = crud.build_watchlist_source_kit(db)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/watchlists/client-email-tasks.csv")
def watchlist_client_email_tasks_csv(db: Session = Depends(get_db)):
    filename, content = crud.build_client_email_tasks_csv(db)
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/watchlists/{watchlist_id}/source-template.csv")
def watchlist_source_template(watchlist_id: int, db: Session = Depends(get_db)):
    result = crud.build_watchlist_property_csv_template(db, watchlist_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    filename, csv_text = result
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/watchlists", response_model=schemas.ClientWatchlist)
def create_watchlist(watchlist: schemas.ClientWatchlistCreate, db: Session = Depends(get_db)):
    try:
        result = crud.create_watchlist(db, watchlist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@app.get("/api/contacts/{contact_id}/watchlists", response_model=List[schemas.ClientWatchlist])
def read_contact_watchlists(contact_id: int, db: Session = Depends(get_db)):
    db_contact = crud.get_contact(db, contact_id=contact_id)
    if not db_contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return crud.get_watchlists(db, contact_id=contact_id)


@app.patch("/api/contacts/{contact_id}/watchlists/review-mode", response_model=List[schemas.ClientWatchlist])
def update_contact_watchlist_review_mode(
    contact_id: int,
    update: schemas.ContactWatchlistReviewModeUpdate,
    db: Session = Depends(get_db),
):
    try:
        result = crud.update_contact_watchlist_review_mode(db, contact_id, update)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@app.patch("/api/contacts/{contact_id}/watchlists/schedule", response_model=List[schemas.ClientWatchlist])
def update_contact_watchlist_schedule(
    contact_id: int,
    update: schemas.ContactWatchlistScheduleUpdate,
    db: Session = Depends(get_db),
):
    try:
        result = crud.update_contact_watchlist_schedule(db, contact_id, update)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@app.patch("/api/contacts/{contact_id}/watchlists/notification-channel", response_model=List[schemas.ClientWatchlist])
def update_contact_watchlist_notification_channel(
    contact_id: int,
    update: schemas.ContactWatchlistNotificationChannelUpdate,
    db: Session = Depends(get_db),
):
    try:
        result = crud.update_contact_watchlist_notification_channel(db, contact_id, update)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@app.post("/api/contacts/{contact_id}/watchlists/default", response_model=schemas.ClientWatchlist)
def create_default_contact_watchlist(contact_id: int, db: Session = Depends(get_db)):
    result = crud.create_default_watchlist_for_contact(db, contact_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return result


@app.patch("/api/watchlists/{watchlist_id}", response_model=schemas.ClientWatchlist)
def update_watchlist(watchlist_id: int, update: schemas.ClientWatchlistUpdate, db: Session = Depends(get_db)):
    try:
        result = crud.update_watchlist(db, watchlist_id, update)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return result


@app.post("/api/watchlists/{watchlist_id}/check", response_model=schemas.WatchlistCheckResponse)
def check_watchlist(watchlist_id: int, db: Session = Depends(get_db)):
    result = crud.run_watchlist_check(db, watchlist_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return result


@app.post("/api/watchlists/check-due")
def check_due_watchlists(db: Session = Depends(get_db)):
    return crud.run_due_watchlists(db)


@app.post("/api/watchlists/check-all")
def check_all_watchlists(db: Session = Depends(get_db)):
    return crud.run_all_active_watchlists(db)


@app.post("/api/watchlists/{watchlist_id}/digest-draft", response_model=schemas.WatchlistDigestDraftResponse)
def create_watchlist_digest_draft(watchlist_id: int, db: Session = Depends(get_db)):
    result = crud.create_digest_draft_from_watchlist_alerts(db, watchlist_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return result


@app.post("/api/watchlists/{watchlist_id}/digest-gmail-draft", response_model=schemas.GmailDraftActionResponse)
def create_watchlist_digest_gmail_draft(watchlist_id: int, db: Session = Depends(get_db)):
    try:
        result = crud.create_gmail_digest_draft_from_watchlist_alerts(db, watchlist_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return result


@app.get("/api/watchlist-alerts", response_model=List[schemas.WatchlistAlert])
def read_watchlist_alerts(
    status: Optional[str] = None,
    contact_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    return crud.get_watchlist_alerts(db, status=status, contact_id=contact_id)


@app.get("/api/watchlist-notifications", response_model=List[schemas.WatchlistNotification])
def read_watchlist_notifications(
    alert_id: Optional[int] = None,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return crud.get_watchlist_notifications(db, alert_id=alert_id, channel=channel, status=status, limit=limit)


@app.get("/api/watchlist-run-logs", response_model=List[schemas.WatchlistRunLog])
def read_watchlist_run_logs(limit: int = 20, db: Session = Depends(get_db)):
    return crud.get_watchlist_run_logs(db, limit=limit)


@app.post("/api/watchlist-run-logs", response_model=schemas.WatchlistRunLog)
def create_watchlist_run_log(entry: schemas.WatchlistRunLogCreate, db: Session = Depends(get_db)):
    return crud.create_watchlist_run_log(db, entry)


@app.post("/api/watchlist-notifications/mark-reported", response_model=schemas.WatchlistNotificationMarkReportedResponse)
def mark_watchlist_notifications_reported(
    req: schemas.WatchlistNotificationMarkReportedRequest,
    db: Session = Depends(get_db),
):
    return crud.mark_codex_notifications_reported(db, ids=req.ids)


@app.patch("/api/watchlist-alerts/{alert_id}", response_model=schemas.WatchlistAlert)
def update_watchlist_alert(alert_id: int, update: schemas.WatchlistAlertUpdate, db: Session = Depends(get_db)):
    result = crud.update_watchlist_alert(db, alert_id, update)
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist alert not found")
    return result


@app.post("/api/watchlist-alerts/{alert_id}/draft", response_model=schemas.WatchlistDraftResponse)
def create_watchlist_alert_draft(alert_id: int, db: Session = Depends(get_db)):
    result = crud.create_draft_from_watchlist_alert(db, alert_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist alert not found")
    return result


@app.post("/api/watchlist-alerts/{alert_id}/gmail-draft", response_model=schemas.GmailDraftActionResponse)
def create_watchlist_alert_gmail_draft(alert_id: int, db: Session = Depends(get_db)):
    try:
        result = crud.create_gmail_draft_from_watchlist_alert(db, alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist alert not found")
    return result


@app.post("/api/watchlist-alerts/{alert_id}/send", response_model=schemas.GmailDraftActionResponse)
def send_watchlist_alert_gmail(alert_id: int, req: schemas.GmailDraftActionRequest, db: Session = Depends(get_db)):
    try:
        result = crud.send_gmail_from_watchlist_alert(
            db,
            alert_id,
            confirm_send=bool(req.confirm_send),
            review_confirmation=req.review_confirmation,
            subject_override=req.subject,
            body_override=req.body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Watchlist alert not found")
    return result


# --- Workflows ---
@app.post("/api/workflow/voice-memo", response_model=schemas.VoiceMemoResponse)
def voice_memo_workflow(req: schemas.VoiceMemoRequest, db: Session = Depends(get_db)):
    return crud.workflow_voice_memo(db, req.audio_text)

@app.post("/api/workflow/voice-memo/transcribe", response_model=schemas.VoiceMemoTranscriptionResponse)
async def transcribe_voice_memo_audio(file: UploadFile = File(...)):
    audio_bytes = await file.read()
    return crud.transcribe_voice_memo_audio(audio_bytes, file.filename or "voice-memo.webm")

@app.post("/api/workflow/market-trigger", response_model=schemas.MarketTriggerResponse)
def market_trigger_workflow(req: schemas.MarketTriggerRequest, db: Session = Depends(get_db)):
    return crud.workflow_market_trigger(db, req.trigger, req.source)

@app.post("/api/workflow/maintenance-report", response_model=schemas.MaintenanceReportResponse)
def maintenance_report_workflow(req: schemas.MaintenanceReportRequest, db: Session = Depends(get_db)):
    return crud.workflow_maintenance_report(db, req.tenant_email, req.message, req.photos)

# --- Push Notifications ---
@app.get("/api/push/vapid-public-key", response_model=schemas.VapidPublicKeyResponse)
def get_vapid_public_key():
    key = os.getenv("VAPID_PUBLIC_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="VAPID key not configured")
    return {"public_key": key}

@app.post("/api/push/subscribe")
def push_subscribe(sub: schemas.PushSubscriptionRequest, db: Session = Depends(get_db)):
    crud.save_push_subscription(db, sub)
    return {"ok": True}

@app.delete("/api/push/unsubscribe")
def push_unsubscribe(req: schemas.PushUnsubscribeRequest, db: Session = Depends(get_db)):
    crud.remove_push_subscription(db, req.endpoint)
    return {"ok": True}

@app.post("/api/push/test")
def push_test(db: Session = Depends(get_db)):
    """Send a test push notification to all subscribers."""
    subs = db.query(models.PushSubscription).all()
    if not subs:
        raise HTTPException(status_code=404, detail="No push subscriptions found")
    sent = 0
    for sub in subs:
        payload = {
            "title": "AI CRM Test",
            "body": "Push notifications are working!",
            "tag": "test",
            "data": {"url": "/dashboard"},
        }
        if crud._send_push(sub, payload):
            sent += 1
    return {"sent": sent, "total": len(subs)}

@app.post("/api/push/check-nudges")
def manual_check_nudges(db: Session = Depends(get_db)):
    """Manually trigger follow-up nudge check."""
    result = crud.check_and_send_followup_nudges(db)
    return result
