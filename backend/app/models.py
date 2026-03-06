from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON
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
