from typing import List

from sqlalchemy.orm import Session

from .. import crud, schemas


def generate_smart_nudges_tool(db: Session) -> schemas.NudgesResponse:
    """
    Thin wrapper around existing crud.generate_smart_nudges.

    This is intentionally a very small abstraction so that the agent layer
    can treat this as a reusable tool without changing existing behavior.
    """
    return crud.generate_smart_nudges(db)


def draft_email_tool(db: Session, contact_id: int) -> schemas.EmailDraftResponse | None:
    """
    Wrapper around existing crud.draft_follow_up_email.

    Returns the EmailDraftResponse or None if the contact is not found.
    """
    return crud.draft_follow_up_email(db, contact_id)


def get_contact_tool(db: Session, contact_id: int) -> schemas.Contact | None:
    """
    Wrapper around existing crud.get_contact.
    """
    return crud.get_contact(db, contact_id)


def get_contact_interactions_tool(
    db: Session,
    contact_id: int,
) -> List[schemas.Interaction]:
    """
    Wrapper around existing crud.get_contact_interactions.
    """
    return crud.get_contact_interactions(db, contact_id)


def get_contact_owned_properties_tool(
    db: Session,
    contact_id: int,
) -> List[schemas.Property]:
    """
    Lightweight wrapper to retrieve properties linked to a contact as owner.
    """
    contact = crud.get_contact(db, contact_id)
    if contact is None:
        return []
    return list(contact.owned_properties)


def get_property_tool(db: Session, property_id: int) -> schemas.Property | None:
    """
    Wrapper around existing crud.get_property.
    """
    return crud.get_property(db, property_id)


def get_properties_tool(
    db: Session,
    property_ids: List[int],
) -> List[schemas.Property]:
    """
    Lightweight wrapper to retrieve multiple properties using existing CRUD reads.
    """
    properties: List[schemas.Property] = []
    seen_ids: set[int] = set()
    for property_id in property_ids:
        if property_id in seen_ids:
            continue
        seen_ids.add(property_id)
        property_record = crud.get_property(db, property_id)
        if property_record is not None:
            properties.append(property_record)
    return properties


def call_llm_tool(prompt: str) -> str:
    """
    Wrapper around the existing Gemini-backed LLM helper.
    """
    return crud._call_llm(prompt)
