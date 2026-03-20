from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
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

