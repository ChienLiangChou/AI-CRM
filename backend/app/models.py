from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey
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
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, index=True, nullable=True)
    phone = Column(String, nullable=True)
    company = Column(String, index=True, nullable=True)
    notes = Column(Text, nullable=True)
    lead_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    stage_id = Column(Integer, ForeignKey("pipeline_stages.id"))
    stage = relationship("PipelineStage", back_populates="contacts")
    
    interactions = relationship("Interaction", back_populates="contact", cascade="all, delete-orphan")

class Interaction(Base):
    __tablename__ = "interactions"
    
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"))
    interaction_type = Column(String) # e.g. "email", "call", "meeting"
    notes = Column(Text)
    date = Column(DateTime, default=datetime.utcnow)
    
    contact = relationship("Contact", back_populates="interactions")
