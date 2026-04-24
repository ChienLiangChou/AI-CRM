from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from ..database import Base


class AgentTask(Base):
    """High-level unit of work for an agent (e.g., follow-up sweep)."""

    __tablename__ = "agent_tasks"

    id = Column(Integer, primary_key=True, index=True)

    # Which logical agent owns this task (e.g. 'follow_up')
    agent_type = Column(String, index=True)

    # Optional subject this task is focused on (e.g. 'contact', 'segment')
    subject_type = Column(String, nullable=True)
    subject_id = Column(Integer, nullable=True)

    # JSON-encoded payload snapshot for this task (kept as text for SQLite)
    payload = Column(Text, nullable=True)

    # queued, waiting_approval, executing, completed, failed
    status = Column(String, default="queued", index=True)
    priority = Column(String, default="normal")  # low, normal, high

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    runs = relationship(
        "AgentRun",
        back_populates="task",
        cascade="all, delete-orphan",
    )


class AgentRun(Base):
    """One concrete execution attempt for an AgentTask."""

    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("agent_tasks.id"), index=True)

    # queued, planning, waiting_approval, executing, completed, failed
    status = Column(String, default="queued", index=True)

    # Optional human-readable summary of what this run is doing
    summary = Column(String, nullable=True)

    # JSON-encoded planning / reasoning steps (kept opaque to DB)
    plan = Column(Text, nullable=True)

    # JSON-encoded result payload
    result = Column(Text, nullable=True)

    # Error text if failed
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    task = relationship("AgentTask", back_populates="runs")
    approvals = relationship(
        "AgentApproval",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    audit_logs = relationship(
        "AgentAuditLog",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class AgentApproval(Base):
    """Represents a high-risk action that requires human approval."""

    __tablename__ = "agent_approvals"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), index=True)

    # e.g. send_email, update_contact, send_push
    action_type = Column(String, index=True)

    # low, medium, high
    risk_level = Column(String, default="medium")

    # JSON-encoded description of the proposed action (email subject/body, diffs, etc.)
    payload = Column(Text, nullable=True)

    # pending, approved, rejected
    status = Column(String, default="pending", index=True)

    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("AgentRun", back_populates="approvals")


class AgentAuditLog(Base):
    """Immutable log of agent-related actions for observability and safety."""

    __tablename__ = "agent_audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("agent_tasks.id"), nullable=True, index=True)

    # 'agent', 'user', or 'system'
    actor_type = Column(String, default="agent", index=True)

    # Short action identifier, e.g. 'generate_followup_recommendations'
    action = Column(String, index=True)

    # JSON-encoded structured details (target ids, before/after, tool name, etc.)
    details = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    run = relationship("AgentRun", back_populates="audit_logs")


class ListingAlertGmailOAuthConnection(Base):
    """Single-mailbox Gmail OAuth connection for Listing Alert intake."""

    __tablename__ = "listing_alert_gmail_oauth_connections"

    id = Column(Integer, primary_key=True, index=True)
    connection_key = Column(String, unique=True, index=True)
    gmail_user_id = Column(String, default="me")
    status = Column(String, default="disconnected", index=True)
    account_email = Column(String, nullable=True)
    granted_scopes = Column(Text, nullable=True)
    encrypted_refresh_token = Column(Text, nullable=True)
    refresh_token_updated_at = Column(DateTime, nullable=True)
    connected_at = Column(DateTime, nullable=True)
    last_refreshed_at = Column(DateTime, nullable=True)
    last_error = Column(String, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ListingAlertGmailOAuthState(Base):
    """One-time OAuth state records used to validate Gmail callbacks."""

    __tablename__ = "listing_alert_gmail_oauth_states"

    id = Column(Integer, primary_key=True, index=True)
    connection_key = Column(String, index=True)
    state_hash = Column(String, unique=True, index=True)
    expires_at = Column(DateTime, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DailyMarketScanWatchlist(Base):
    """Persisted watchlist configuration for scheduled Daily Market Scan runs."""

    __tablename__ = "daily_market_scan_watchlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    enabled = Column(Boolean, default=True, index=True)
    schedule_interval_minutes = Column(Integer, default=60)
    request_payload = Column(Text, nullable=False)
    operator_notes = Column(Text, nullable=True)
    next_run_at = Column(DateTime, nullable=True, index=True)
    last_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=True)
    last_run_status = Column(String, nullable=True, index=True)
    last_run_error = Column(Text, nullable=True)
    last_run_started_at = Column(DateTime, nullable=True)
    last_run_finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DailyMarketScanWatchlistSchedulerState(Base):
    """Singleton-style persisted heartbeat for the watchlist scheduler loop."""

    __tablename__ = "daily_market_scan_watchlist_scheduler_states"

    id = Column(Integer, primary_key=True, index=True)
    scheduler_key = Column(String, unique=True, index=True)
    last_sweep_started_at = Column(DateTime, nullable=True)
    last_sweep_finished_at = Column(DateTime, nullable=True)
    last_status = Column(String, default="idle")
    last_error = Column(Text, nullable=True)
    last_due_count = Column(Integer, default=0)
    last_triggered_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
