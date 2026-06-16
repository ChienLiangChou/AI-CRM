from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class PipelineStage(Base):
    __tablename__ = "pipeline_stages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    order = Column(Integer)
    
    contacts = relationship("Contact", back_populates="stage")

class Contact(Base):
    """Client/Lead — supports buyer, seller, investor, tenant, landlord."""
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    name_zh = Column(String, nullable=True)
    email = Column(String, index=True, nullable=True)
    phone = Column(String, nullable=True)
    company = Column(String, index=True, nullable=True)
    preferred_language = Column(String, default="en")  # en, zh-tw, zh-cn

    # Real estate specific
    client_type = Column(String, default="buyer")  # comma-separated: buyer,seller,investor,tenant,landlord
    status = Column(String, default="active")  # active, dormant, closed, archived

    # Budget & Investment
    budget_min = Column(Float, nullable=True)
    budget_max = Column(Float, nullable=True)
    expected_roi = Column(Float, nullable=True)
    investment_focus = Column(String, nullable=True)  # cash_flow, appreciation, flip

    # Preferences (stored as JSON strings for SQLite compat)
    preferred_areas = Column(Text, nullable=True, default="[]")  # JSON array
    property_preferences = Column(Text, nullable=True, default="{}")  # JSON: types, bedrooms_min, must_haves, deal_breakers
    
    # Tags & Scoring
    tags = Column(String, nullable=True, default="")
    lead_score = Column(Float, default=0.0)
    qualification_status = Column(String, nullable=True, default="unqualified")
    qualification_route = Column(String, nullable=True)
    qualification_json = Column(Text, nullable=True, default="{}")
    qualification_updated_at = Column(DateTime, nullable=True)
    mood_score = Column(Integer, nullable=True)  # 1-10
    mood_notes = Column(String, nullable=True)
    source = Column(String, nullable=True)  # referral, open_house, online, cold_call, social_media

    # Notes & AI
    notes = Column(Text, nullable=True)
    ai_summary = Column(Text, nullable=True)

    # Time tracking
    last_contacted_at = Column(DateTime, nullable=True)
    next_followup_at = Column(DateTime, nullable=True)
    followup_priority = Column(String, default="normal")  # urgent, normal, low
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id"))
    stage = relationship("PipelineStage", back_populates="contacts")
    interactions = relationship("Interaction", back_populates="contact", cascade="all, delete-orphan")
    watchlists = relationship("ClientWatchlist", back_populates="contact", cascade="all, delete-orphan")
    watchlist_alerts = relationship("WatchlistAlert", back_populates="contact")
    
    # Properties relationships (as owner or tenant)
    owned_properties = relationship("Property", back_populates="owner", foreign_keys="Property.owner_client_id")
    rented_properties = relationship("Property", back_populates="tenant", foreign_keys="Property.tenant_client_id")


class Property(Base):
    """Real estate property/listing."""
    __tablename__ = "properties"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Address
    unit = Column(String, nullable=True)
    street = Column(String)
    city = Column(String, index=True)  # Toronto, Mississauga, Markham, etc.
    province = Column(String, default="ON")
    postal_code = Column(String, nullable=True)
    neighborhood = Column(String, nullable=True)
    
    # Property info
    property_type = Column(String)  # condo, townhouse, semi, detached, commercial
    status = Column(String, default="off_market")  # listed_for_sale, listed_for_rent, rented, sold, pending_repair, vacant, off_market
    
    # Details
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    sqft = Column(Integer, nullable=True)
    parking = Column(Integer, nullable=True)
    year_built = Column(Integer, nullable=True)
    
    # Financials
    listing_price = Column(Float, nullable=True)
    sold_price = Column(Float, nullable=True)
    monthly_rent = Column(Float, nullable=True)
    monthly_expenses = Column(Float, nullable=True)
    cap_rate = Column(Float, nullable=True)
    annual_roi = Column(Float, nullable=True)
    listed_at = Column(DateTime, nullable=True)
    sold_at = Column(DateTime, nullable=True)
    leased_at = Column(DateTime, nullable=True)
    
    # Links
    mls_number = Column(String, nullable=True)
    listing_url = Column(String, nullable=True)
    photos = Column(Text, nullable=True, default="[]")  # JSON array of URLs
    
    # Maintenance contacts (JSON array of {name, role, phone, email})
    maintenance_contacts = Column(Text, nullable=True, default="[]")
    
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Owner & Tenant relationships
    owner_client_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    tenant_client_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    owner = relationship("Contact", back_populates="owned_properties", foreign_keys=[owner_client_id])
    tenant = relationship("Contact", back_populates="rented_properties", foreign_keys=[tenant_client_id])
    watchlist_alerts = relationship("WatchlistAlert", back_populates="property")


class ClientWatchlist(Base):
    """Saved listing/comp search criteria for one client."""
    __tablename__ = "client_watchlists"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    name = Column(String)
    watch_type = Column(String, index=True)  # buyer_listing_match, seller_listing_and_sold, tenant_rental_match, landlord_rental_market
    status = Column(String, default="active", index=True)  # active, paused
    criteria_json = Column(Text, nullable=True, default="{}")
    schedule_json = Column(Text, nullable=True, default='{"times":["09:00"],"timezone":"America/Toronto"}')
    notification_channel = Column(String, default="codex_app")  # codex_app, app_push, in_app
    review_mode = Column(String, default="manual_review")  # manual_review, auto_create_draft, auto_gmail_draft, auto_send_approved
    data_source = Column(String, default="internal_properties")  # internal_properties, mls_adapter
    source_query = Column(Text, nullable=True)  # optional Gmail/REALM/TRREB search query for this watchlist
    last_checked_at = Column(DateTime, nullable=True)
    next_check_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact = relationship("Contact", back_populates="watchlists")
    alerts = relationship("WatchlistAlert", back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistAlert(Base):
    """Reviewable result produced by a client watchlist check."""
    __tablename__ = "watchlist_alerts"

    id = Column(Integer, primary_key=True, index=True)
    watchlist_id = Column(Integer, ForeignKey("client_watchlists.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True, index=True)
    interaction_id = Column(Integer, ForeignKey("interactions.id"), nullable=True, index=True)
    alert_type = Column(String, index=True)  # new_listing, sold_comp, leased_comp, system_notice
    title = Column(String)
    summary = Column(Text)
    analysis = Column(Text)
    source = Column(String, default="internal_properties")
    source_url = Column(String, nullable=True)
    payload_json = Column(Text, nullable=True, default="{}")
    status = Column(String, default="pending_review", index=True)  # pending_review, draft_created, dismissed
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    watchlist = relationship("ClientWatchlist", back_populates="alerts")
    contact = relationship("Contact", back_populates="watchlist_alerts")
    property = relationship("Property", back_populates="watchlist_alerts")
    interaction = relationship("Interaction")
    notifications = relationship("WatchlistNotification", back_populates="alert", cascade="all, delete-orphan")


class PropertyFeedConfig(Base):
    """Saved listing-feed import settings for scheduled watchlist checks."""
    __tablename__ = "property_feed_configs"

    id = Column(Integer, primary_key=True, index=True)
    gmail_feed_enabled = Column(Boolean, default=False)
    gmail_query = Column(String, default="newer_than:14d (MLS OR listing OR sold OR leased OR REALM OR TRREB)")
    gmail_max_results = Column(Integer, default=10)
    last_import_at = Column(DateTime, nullable=True)
    last_import_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WatchlistNotification(Base):
    """Delivery/audit log for watchlist alert notifications."""
    __tablename__ = "watchlist_notifications"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(Integer, ForeignKey("watchlist_alerts.id"), index=True)
    watchlist_id = Column(Integer, ForeignKey("client_watchlists.id"), index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), index=True)
    channel = Column(String, index=True)  # codex_app, app_push, in_app
    status = Column(String, default="queued", index=True)
    title = Column(String)
    body = Column(Text)
    error = Column(String, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    alert = relationship("WatchlistAlert", back_populates="notifications")
    watchlist = relationship("ClientWatchlist")
    contact = relationship("Contact")


class WatchlistRunLog(Base):
    """Scheduled/manual watchlist run evidence for Kevin review."""
    __tablename__ = "watchlist_run_logs"

    id = Column(Integer, primary_key=True, index=True)
    run_type = Column(String, default="manual", index=True)  # manual, scheduled, codex_automation
    status = Column(String, default="success", index=True)  # success, failed
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    checked_count = Column(Integer, default=0)
    created_alerts = Column(Integer, default=0)
    matched_properties = Column(Integer, default=0)
    active_count = Column(Integer, default=0)
    due_count = Column(Integer, default=0)
    not_due_count = Column(Integer, default=0)
    pending_alert_count = Column(Integer, default=0)
    draft_alert_count = Column(Integer, default=0)
    sent_alert_count = Column(Integer, default=0)
    source_status = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=True, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class Interaction(Base):
    """Interaction log with AI parsing support."""
    __tablename__ = "interactions"
    
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    
    # Channel & direction
    channel = Column(String, default="email")  # voice_memo, email, sms, whatsapp, phone_call, in_person, photo_report
    direction = Column(String, default="outbound")  # inbound, outbound
    interaction_type = Column(String)  # email, call, meeting, voice_memo, maintenance_request
    
    # Raw data
    notes = Column(Text)
    raw_attachments = Column(Text, nullable=True, default="[]")  # JSON array of URLs
    
    # AI parsed results (JSON)
    ai_parsed_intent = Column(String, nullable=True)  # inquiry, complaint, showing_feedback, maintenance_request, etc.
    ai_parsed_sentiment = Column(String, nullable=True)  # positive, neutral, negative, angry, anxious
    ai_parsed_sentiment_score = Column(Float, nullable=True)  # -1.0 to 1.0
    ai_parsed_entities = Column(Text, nullable=True, default="{}")  # JSON: areas, budget, preferences, pain_points
    ai_auto_summary = Column(Text, nullable=True)
    ai_suggested_action = Column(String, nullable=True)
    
    # Generated response
    generated_response_type = Column(String, nullable=True)  # email_draft, sms_draft, vendor_dispatch
    generated_response_content = Column(Text, nullable=True)
    generated_response_status = Column(String, nullable=True)  # pending_review, sent, archived
    
    date = Column(DateTime, default=datetime.utcnow)
    
    contact = relationship("Contact", back_populates="interactions")
    property = relationship("Property")


class PushSubscription(Base):
    """Web Push subscription for notifications."""
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String, unique=True, index=True)
    p256dh = Column(String)
    auth = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class GmailOAuthConnection(Base):
    """Encrypted Gmail OAuth connection for review-gated client email drafts."""
    __tablename__ = "gmail_oauth_connections"

    id = Column(Integer, primary_key=True, index=True)
    connection_key = Column(String, unique=True, index=True)
    gmail_user_id = Column(String, default="me")
    account_email = Column(String, nullable=True)
    status = Column(String, default="disconnected")
    granted_scopes = Column(Text, nullable=True, default="[]")
    encrypted_refresh_token = Column(Text, nullable=True)
    refresh_token_updated_at = Column(DateTime, nullable=True)
    connected_at = Column(DateTime, nullable=True)
    last_refreshed_at = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GmailOAuthState(Base):
    """Short-lived OAuth state guard. Stores only a hash of the browser state."""
    __tablename__ = "gmail_oauth_states"

    id = Column(Integer, primary_key=True, index=True)
    connection_key = Column(String, index=True)
    state_hash = Column(String, unique=True, index=True)
    expires_at = Column(DateTime)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
