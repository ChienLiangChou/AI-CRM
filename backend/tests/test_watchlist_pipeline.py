import csv
import hashlib
import json
import textwrap
import zipfile
from datetime import timedelta
from io import BytesIO, StringIO

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app import crud, gmail_service, models, schemas
from app.database import Base


def make_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def seed_watchlists(db):
    tom = models.Contact(name="Tom Lin", email="tom@example.com", preferred_language="zh-tw")
    amy = models.Contact(name="Amy Yuen", email="amy@example.com", preferred_language="en")
    db.add_all([tom, amy])
    db.commit()
    db.refresh(tom)
    db.refresh(amy)

    tom_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=tom.id,
            name="Tom Lin - Seller listing + sold comps",
            watch_type="seller_listing_and_sold",
            criteria={
                "areas": ["Thornhill"],
                "types": ["townhouse"],
                "must_haves": ["freehold"],
                "property_address": "107 Brownstone Circle",
            },
            notification_channel="codex_app",
            review_mode="manual_review",
        ),
    )
    amy_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=amy.id,
            name="Amy Yuen - Buyer listing match",
            watch_type="buyer_listing_match",
            criteria={
                "areas": ["Halton Hills", "Mississauga", "Milton"],
                "types": ["detached"],
                "must_haves": ["At least 1-car garage"],
                "deal_breakers": ["Mississauga properties in Malton (excluded)"],
                "max_price": 900000,
                "bedrooms_min": 2,
                "bathrooms_min": 3,
                "parking_min": 1,
            },
            notification_channel="codex_app",
            review_mode="manual_review",
        ),
    )
    return tom_watch, amy_watch


def sample_csv():
    return textwrap.dedent(
        """\
        mls_number,street,city,community,status,property_type,list price,sold price,rent,list date,sold date,beds,baths,parking,url,remarks
        N100001,109 Brownstone Circle,Thornhill,Thornhill,Sold,Townhouse,1150000,1180000,,2026-06-01,2026-06-10,3,3,1,https://example.com/N100001,Freehold townhouse sold comp near 107 Brownstone Circle
        N100002,111 Brownstone Circle,Thornhill,Thornhill,For Sale,Townhouse,1199000,,,2026-06-09,,3,3,1,https://example.com/N100002,Freehold townhouse competing active listing
        W200001,20 Main Street,Milton,Milton,For Sale,Detached,880000,,,2026-06-09,,3,3,1,https://example.com/W200001,Detached with garage
        W200002,99 Malton Road,Mississauga,Malton,For Sale,Detached,875000,,,2026-06-09,,3,3,1,https://example.com/W200002,Detached in Malton should be excluded
        """
    )


def rental_csv():
    return textwrap.dedent(
        """\
        mls_number,street,city,community,status,property_type,list price,sold price,rent,list date,leased date,beds,baths,parking,url,remarks
        R300001,10 Finch Avenue,North York,North York,For Rent,Condo,,,2700,2026-06-09,,2,2,1,https://example.com/R300001,Condo rental with parking
        R300002,12 Finch Avenue,North York,North York,For Rent,Condo,,,3200,2026-06-09,,2,2,1,https://example.com/R300002,Condo rental over budget
        R400001,20 Brownstone Circle,Thornhill,Thornhill,For Rent,Townhouse,,,3900,2026-06-09,,3,3,1,https://example.com/R400001,Townhouse rental near 107 Brownstone
        R400002,22 Brownstone Circle,Thornhill,Thornhill,Leased,Townhouse,,,4100,2026-06-01,2026-06-10,3,3,1,https://example.com/R400002,Leased townhouse comp near 107 Brownstone
        """
    )


def test_contact_update_accepts_email_only_without_clearing_existing_fields():
    db = make_session()
    contact = models.Contact(
        name="Tom Lin",
        client_type="seller",
        preferred_language="zh-tw",
        notes="Needs Thornhill townhouse sold comps.",
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)

    updated = crud.update_contact(
        db,
        contact.id,
        schemas.ContactUpdate(email="tom.lin@example.com"),
    )

    assert updated.email == "tom.lin@example.com"
    assert updated.name == "Tom Lin"
    assert updated.client_type == "seller"
    assert updated.preferred_language == "zh-tw"
    assert updated.notes == "Needs Thornhill townhouse sold comps."


def test_create_contact_writes_structured_lead_qualification():
    db = make_session()

    contact = crud.create_contact(
        db,
        schemas.ContactCreate(
            name="Amy Yuen",
            email="amy@example.com",
            client_type="buyer",
            budget_max=900000,
            preferred_areas='["Milton"]',
            notes="Looking to buy a detached home in Milton within 2-3 weeks with garage parking.",
        ),
    )

    qualification = json.loads(contact.qualification_json)
    assert contact.qualification_status == "qualified"
    assert contact.qualification_route == "watchlist_ready"
    assert qualification["schema_version"] == "lead_qualification_v2"
    assert qualification["intent"] == "buyer"
    assert qualification["recommended_route"] == "watchlist_ready"
    assert "contact method present" in qualification["evidence"]
    assert qualification["missing_fields"] == []


def test_lead_qualification_blocks_delivery_when_contact_method_missing():
    db = make_session()

    contact = crud.create_contact(
        db,
        schemas.ContactCreate(
            name="Tom Lin",
            client_type="seller",
            preferred_areas='["Thornhill"]',
            notes="Seller wants sold comps around 107 Brownstone Circle in Thornhill.",
        ),
    )

    qualification = json.loads(contact.qualification_json)
    assert contact.qualification_status == "needs_clarification"
    assert contact.qualification_route == "clarification_draft"
    assert "email_or_phone" in qualification["missing_fields"]
    assert "missing_contact_method_blocks_direct_client_delivery" in qualification["safe_defaults_applied"]


def test_interaction_refreshes_lead_qualification_route():
    db = make_session()
    contact = crud.create_contact(
        db,
        schemas.ContactCreate(
            name="Cindy Chen",
            email="cindy@example.com",
            client_type="tenant",
            notes="Tenant lead from referral.",
        ),
    )
    assert contact.qualification_route != "watchlist_ready"

    crud.create_contact_interaction(
        db,
        contact.id,
        schemas.InteractionCreate(
            interaction_type="email",
            notes="Looking to rent a condo in North York around $2800 ASAP with one parking spot.",
        ),
    )
    db.refresh(contact)
    qualification = json.loads(contact.qualification_json)

    assert contact.qualification_route == "watchlist_ready"
    assert qualification["intent"] == "tenant"
    assert "interaction history present" in qualification["evidence"]


def test_legacy_voice_memo_review_flags_generic_contacts_without_merging():
    db = make_session()
    tom = models.Contact(name="Tom Lin", email="tom@example.com", preferred_language="zh-tw")
    generic = models.Contact(name="Voice Memo Lead", preferred_language="zh-tw")
    db.add_all([tom, generic])
    db.commit()
    db.refresh(tom)
    db.refresh(generic)

    db.add(
        models.Interaction(
            contact_id=generic.id,
            interaction_type="voice_memo",
            channel="voice_memo",
            direction="inbound",
            notes="Tom Lin,賣家,他要賣的是一個Freehold Townhouse 107 Brownstone Circle, Thornhill.",
            ai_parsed_entities=json.dumps({"client_name": "Voice Memo Lead"}),
        )
    )
    db.commit()

    result = crud.get_legacy_voice_memo_reviews(db)

    assert result.count == 1
    item = result.items[0]
    assert item.contact_id == generic.id
    assert item.suggested_name == "Tom Lin"
    assert item.suggested_existing_contact_id == tom.id
    assert "No automatic merge" in item.safety_note
    assert db.query(models.Contact).filter(models.Contact.id == generic.id).one().name == "Voice Memo Lead"
    assert db.query(models.Contact).filter(models.Contact.id == tom.id).one().email == "tom@example.com"


def test_csv_preview_predicts_matches_without_writing_rows():
    db = make_session()
    seed_watchlists(db)

    result = crud.import_properties_csv(db, sample_csv(), dry_run=True)

    assert result.success is True
    assert result.created == 4
    assert db.query(func.count(models.Property.id)).scalar() == 0
    preview_contacts = {item["contact_name"] for item in result.watchlist_match_preview}
    assert preview_contacts == {"Tom Lin", "Amy Yuen"}
    assert sum(1 for item in result.watchlist_match_preview if item["contact_name"] == "Tom Lin") == 2
    assert sum(1 for item in result.watchlist_match_preview if item["contact_name"] == "Amy Yuen") == 1
    readiness_by_contact = {item["contact_name"]: item for item in result.watchlist_readiness_preview}
    assert readiness_by_contact["Tom Lin"]["readiness_delta"] == "becomes_ready"
    assert readiness_by_contact["Tom Lin"]["source_ready_before"] is False
    assert readiness_by_contact["Tom Lin"]["source_ready_after"] is True
    assert readiness_by_contact["Tom Lin"]["missing_after"] == []
    assert readiness_by_contact["Tom Lin"]["preview_status_counts"] == {"listed_for_sale": 1, "sold": 1}
    assert readiness_by_contact["Amy Yuen"]["readiness_delta"] == "becomes_ready"
    assert readiness_by_contact["Amy Yuen"]["source_ready_after"] is True
    assert readiness_by_contact["Amy Yuen"]["preview_status_counts"] == {"listed_for_sale": 1}


def test_csv_preview_reports_delivery_gate_after_import():
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    crud.update_watchlist(
        db,
        amy_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    tom = db.query(models.Contact).filter(models.Contact.id == tom_watch.contact_id).one()
    tom.email = None
    db.add(tom)
    db.commit()
    db.expire_all()

    result = crud.import_properties_csv(db, sample_csv(), dry_run=True)

    readiness_by_contact = {item["contact_name"]: item for item in result.watchlist_readiness_preview}
    tom_preview = readiness_by_contact["Tom Lin"]
    amy_preview = readiness_by_contact["Amy Yuen"]
    assert tom_preview["source_ready_after"] is True
    assert tom_preview["delivery_state_after"] == "email_required_after_import"
    assert tom_preview["draft_recipient_ready_after"] is False
    assert tom_preview["contact_email_present"] is False
    assert any("email is missing" in blocker for blocker in tom_preview["delivery_blockers_after"])
    assert "Add the client's email" in tom_preview["delivery_next_step"]
    assert amy_preview["source_ready_after"] is True
    assert amy_preview["delivery_state_after"] == "gmail_draft_recipient_ready_after_import"
    assert amy_preview["draft_recipient_ready_after"] is True
    assert amy_preview["contact_email_present"] is True


def test_csv_preview_reports_import_warnings_without_blocking_rows():
    db = make_session()
    seed_watchlists(db)

    result = crud.import_properties_csv(
        db,
        "mls_number,street,city,community,status,property_type,list price,sold price,rent,beds,baths,parking,url,remarks\n"
        "W300001,10 Main Street,Milton,Milton,For Sale,Detached,,,,3,2,1,https://example.com/W300001,Missing list price\n"
        "W300002,12 Main Street,Milton,Milton,Pending,Detached,850000,,,3,2,1,https://example.com/W300002,Unknown status example\n",
        dry_run=True,
    )

    assert result.success is True
    assert result.created == 2
    assert db.query(func.count(models.Property.id)).scalar() == 0
    assert any("listed_for_sale row is missing list price" in warning for warning in result.warnings)
    assert any("unrecognized status 'pending'" in warning for warning in result.warnings)


def test_csv_import_accepts_common_realm_trreb_export_headers():
    db = make_session()
    seed_watchlists(db)
    export_csv = textwrap.dedent(
        """\
        MLS#,Address,Municipality District,Community,Last Status,TypeOwn1Out,ListPrice,SoldPrice,List Date,Sold Date,Br,Wr,GarSpaces,Virtual Tour URL,Remarks
        N910001,109 Brownstone Circle,Thornhill,Thornhill,Sld,Att/Row/Twnhouse,$1.18M,$1.15M,2026-06-01,2026-06-10,3,3,1,https://example.com/N910001,Sold comp near 107 Brownstone Circle
        N910002,111 Brownstone Circle,Thornhill,Thornhill,A,Att/Row/Twnhouse,"$1,199,000",,2026-06-09,,3,3,1,https://example.com/N910002,Active comp near 107 Brownstone Circle
        """
    )

    result = crud.import_properties_csv(db, export_csv, dry_run=False)

    assert result.success is True
    assert result.created == 2
    rows = db.query(models.Property).order_by(models.Property.mls_number).all()
    assert [row.mls_number for row in rows] == ["N910001", "N910002"]
    sold_row, active_row = rows
    assert sold_row.street == "109 Brownstone Circle"
    assert sold_row.city == "Thornhill"
    assert sold_row.status == "sold"
    assert sold_row.property_type == "townhouse"
    assert sold_row.listing_price == 1_180_000
    assert sold_row.sold_price == 1_150_000
    assert sold_row.bedrooms == 3
    assert sold_row.bathrooms == 3
    assert sold_row.parking == 1
    assert sold_row.listing_url == "https://example.com/N910001"
    assert sold_row.listed_at.date().isoformat() == "2026-06-01"
    assert sold_row.sold_at.date().isoformat() == "2026-06-10"
    assert active_row.status == "listed_for_sale"
    assert active_row.property_type == "townhouse"
    assert active_row.listing_price == 1_199_000
    assert active_row.sold_price is None
    assert active_row.listed_at.date().isoformat() == "2026-06-09"

    tasks = crud.get_watchlist_source_tasks(db)
    tom_task = next(task for task in tasks.tasks if task.contact_name == "Tom Lin")
    assert tom_task.source_ready is True
    assert tom_task.missing_required_statuses == []
    source_setups = {setup.contact_name: setup for setup in crud.get_watchlist_source_setups(db)}
    assert source_setups["Tom Lin"].matching_status_counts == {"listed_for_sale": 1, "sold": 1}


def test_reso_json_preview_maps_odata_value_rows_without_writing_rows():
    db = make_session()
    seed_watchlists(db)
    payload = {
        "value": [
            {
                "ListingKey": "N940001",
                "UnparsedAddress": "109 Brownstone Circle, Thornhill, ON L4J 7P5",
                "City": "Thornhill",
                "CityRegion": "Thornhill",
                "StandardStatus": "Active",
                "TransactionType": "For Sale",
                "PropertySubType": "Att/Row/Twnhouse",
                "ListPrice": 1199000,
                "BedroomsTotal": 3,
                "BathroomsTotalInteger": 3,
                "ParkingTotal": 1,
                "ListingContractDate": "2026-06-11T09:15:00Z",
                "VirtualTourURLUnbranded": "https://example.com/N940001",
                "PublicRemarks": "Freehold townhouse active comp near 107 Brownstone Circle.",
            },
            {
                "ListingKey": "N940002",
                "StreetNumber": "111",
                "StreetName": "Brownstone",
                "StreetSuffix": "Circle",
                "City": "Thornhill",
                "CityRegion": "Thornhill",
                "StandardStatus": "Closed",
                "TransactionType": "For Sale",
                "PropertySubType": "Townhouse",
                "ListPrice": 1129000,
                "ClosePrice": 1150000,
                "BedroomsTotal": 3,
                "BathroomsTotalInteger": 3,
                "ParkingTotal": 1,
                "ListingContractDate": "2026-05-20",
                "CloseDate": "2026-06-10T14:20:00-04:00",
                "ListingURL": "https://example.com/N940002",
                "PublicRemarks": "Sold freehold townhouse comp near Brownstone.",
            },
        ]
    }

    result = crud.import_properties_reso_json(db, payload, dry_run=True)

    assert result.success is True
    assert result.created == 2
    assert result.updated == 0
    assert db.query(func.count(models.Property.id)).scalar() == 0
    preview_by_mls = {row["mls_number"]: row for row in result.preview_rows}
    assert preview_by_mls["N940001"]["status"] == "listed_for_sale"
    assert preview_by_mls["N940001"]["street"] == "109 Brownstone Circle"
    assert preview_by_mls["N940001"]["listing_price"] == 1_199_000
    assert preview_by_mls["N940001"]["listed_at"] == "2026-06-11"
    assert preview_by_mls["N940002"]["status"] == "sold"
    assert preview_by_mls["N940002"]["street"] == "111 Brownstone Circle"
    assert preview_by_mls["N940002"]["sold_price"] == 1_150_000
    assert preview_by_mls["N940002"]["sold_at"] == "2026-06-10"
    readiness_by_contact = {item["contact_name"]: item for item in result.watchlist_readiness_preview}
    assert readiness_by_contact["Tom Lin"]["readiness_delta"] == "becomes_ready"
    assert readiness_by_contact["Tom Lin"]["preview_status_counts"] == {"listed_for_sale": 1, "sold": 1}


def test_reso_json_import_maps_rental_and_leased_rows():
    db = make_session()
    payload = [
        {
            "ListingId": "R950001",
            "UnparsedAddress": "10 Finch Avenue, North York, ON M2N 5R6",
            "City": "North York",
            "Community": "North York",
            "StandardStatus": "Active",
            "TransactionType": "Lease",
            "PropertySubType": "Condo Apartment",
            "ListPrice": 2700,
            "LeaseAmount": 2700,
            "BedroomsTotal": 2,
            "BathroomsTotalInteger": 2,
            "ParkingTotal": 1,
            "ListingContractDate": "2026-06-11T08:00:00Z",
        },
        {
            "ListingId": "R950002",
            "UnparsedAddress": "22 Brownstone Circle, Thornhill, ON L4J 7P5",
            "City": "Thornhill",
            "Community": "Thornhill",
            "StandardStatus": "Closed",
            "TransactionType": "Residential Lease",
            "PropertySubType": "Townhouse",
            "ClosePrice": 4100,
            "BedroomsTotal": 3,
            "BathroomsTotalInteger": 3,
            "ParkingTotal": 1,
            "CloseDate": "2026-06-10",
        },
    ]

    result = crud.import_properties_reso_json(db, payload, dry_run=False)

    assert result.success is True
    assert result.created == 2
    rows = {row.mls_number: row for row in db.query(models.Property).order_by(models.Property.mls_number).all()}
    assert rows["R950001"].status == "listed_for_rent"
    assert rows["R950001"].property_type == "condo"
    assert rows["R950001"].monthly_rent == 2700
    assert rows["R950001"].listing_price is None
    assert rows["R950001"].listed_at.date().isoformat() == "2026-06-11"
    assert rows["R950002"].status == "rented"
    assert rows["R950002"].property_type == "townhouse"
    assert rows["R950002"].monthly_rent == 4100
    assert rows["R950002"].sold_price is None
    assert rows["R950002"].leased_at.date().isoformat() == "2026-06-10"


def test_reso_json_import_rejects_invalid_or_missing_records_payload():
    db = make_session()

    invalid = crud.import_properties_reso_json(db, '{"value": [}', dry_run=True)
    missing = crud.import_properties_reso_json(db, {"metadata": "no records"}, dry_run=True)

    assert invalid.success is False
    assert invalid.created == 0
    assert any("invalid_reso_json" in error for error in invalid.errors)
    assert missing.success is False
    assert missing.created == 0
    assert "reso_json_missing_records_array" in missing.errors


def test_csv_import_counts_identical_rows_as_unchanged_not_updated():
    db = make_session()
    seed_watchlists(db)

    first = crud.import_properties_csv(db, sample_csv(), dry_run=False)
    second_preview = crud.import_properties_csv(db, sample_csv(), dry_run=True)
    second_import = crud.import_properties_csv(db, sample_csv(), dry_run=False)

    assert first.created == 4
    assert first.updated == 0
    assert first.unchanged == 0
    assert second_preview.created == 0
    assert second_preview.updated == 0
    assert second_preview.unchanged == 4
    assert {row["action"] for row in second_preview.preview_rows} == {"unchanged"}
    assert second_import.created == 0
    assert second_import.updated == 0
    assert second_import.unchanged == 4
    assert "unchanged row(s)" in second_import.message
    assert db.query(func.count(models.Property.id)).scalar() == 4


def test_csv_import_updates_only_when_existing_property_fields_change():
    db = make_session()
    seed_watchlists(db)
    crud.import_properties_csv(db, sample_csv(), dry_run=False)

    changed_csv = sample_csv().replace("N100002,111 Brownstone Circle,Thornhill,Thornhill,For Sale,Townhouse,1199000", "N100002,111 Brownstone Circle,Thornhill,Thornhill,For Sale,Townhouse,1189000")

    preview = crud.import_properties_csv(db, changed_csv, dry_run=True)
    imported = crud.import_properties_csv(db, changed_csv, dry_run=False)

    assert preview.updated == 1
    assert preview.unchanged == 3
    preview_by_mls = {row.get("mls_number"): row for row in preview.preview_rows}
    assert preview_by_mls["N100002"]["action"] == "update"
    assert imported.updated == 1
    assert imported.unchanged == 3
    changed_property = db.query(models.Property).filter(models.Property.mls_number == "N100002").one()
    assert changed_property.listing_price == 1_189_000


def test_feed_import_accepts_million_and_k_price_suffixes():
    db = make_session()
    seed_watchlists(db)
    feed_text = textwrap.dedent(
        """\
        Subject: REALM saved search - Brownstone sold comp
        N920001
        Address: 109 Brownstone Circle, Thornhill
        Status: Sld
        Type: Att/Row/Twnhouse
        List Price: $1.18M
        Sold Price: $1.15M
        List Date: 2026-05-28
        Sold Date: Jun 10, 2026
        Br: 3
        Wr: 3
        Parking: 1
        https://example.com/N920001

        Subject: REALM saved search - buyer active match
        W920002
        Address: 20 Main Street, Milton
        Status: A
        Type: Detached
        Price: 850K
        List Date: 06/09/2026
        Beds: 3
        Baths: 3
        Garage Spaces: 1
        https://example.com/W920002
        """
    )

    result = crud.import_properties_feed_text(db, feed_text, dry_run=True)

    assert result.success is True
    assert result.created == 2
    assert result.warnings == []
    assert db.query(func.count(models.Property.id)).scalar() == 0
    preview_by_mls = {row["mls_number"]: row for row in result.preview_rows}
    assert preview_by_mls["N920001"]["sold_price"] == 1_150_000
    assert preview_by_mls["N920001"]["listing_price"] == 1_180_000
    assert preview_by_mls["N920001"]["listed_at"] == "2026-05-28"
    assert preview_by_mls["N920001"]["sold_at"] == "2026-06-10"
    assert preview_by_mls["N920001"]["property_type"] == "townhouse"
    assert preview_by_mls["N920001"]["bathrooms"] == 3
    assert preview_by_mls["W920002"]["listing_price"] == 850_000
    assert preview_by_mls["W920002"]["listed_at"] == "2026-06-09"
    readiness_by_contact = {item["contact_name"]: item for item in result.watchlist_readiness_preview}
    assert readiness_by_contact["Amy Yuen"]["readiness_delta"] == "becomes_ready"
    assert readiness_by_contact["Amy Yuen"]["preview_status_counts"] == {"listed_for_sale": 1}


def test_feed_import_accepts_realm_saved_search_alias_labels():
    db = make_session()
    seed_watchlists(db)
    feed_text = textwrap.dedent(
        """\
        Subject: REALM saved search - Thornhill active comp
        N930001
        Addr: 44 Brownstone Cres, Thornhill
        Municipality District: Thornhill
        Community: Thornhill
        Last Status: A
        TypeOwn1Out: Att/Row/Twnhouse
        LP: $1,088,000
        Br: 3
        Wr: 3
        GarSpaces: 1
        https://example.com/N930001

        Subject: REALM saved search - Halton Hills buyer match
        W930002
        Addr: 15 Cedar Gate, Halton Hills
        Municipality District: Halton Hills
        Last Status: A
        Property Style: Detached
        ListPrice: 875K
        Br: 3
        Washrooms: 3
        Parking Total: 2
        https://example.com/W930002
        """
    )

    result = crud.import_properties_feed_text(db, feed_text, dry_run=True)

    assert result.success is True
    assert result.created == 2
    assert result.warnings == []
    preview_by_mls = {row["mls_number"]: row for row in result.preview_rows}
    assert preview_by_mls["N930001"]["street"] == "44 Brownstone Cres"
    assert preview_by_mls["N930001"]["city"] == "Thornhill"
    assert preview_by_mls["N930001"]["property_type"] == "townhouse"
    assert preview_by_mls["N930001"]["listing_price"] == 1_088_000
    assert preview_by_mls["N930001"]["parking"] == 1
    assert preview_by_mls["W930002"]["street"] == "15 Cedar Gate"
    assert preview_by_mls["W930002"]["city"] == "Halton Hills"
    assert preview_by_mls["W930002"]["property_type"] == "detached"
    assert preview_by_mls["W930002"]["listing_price"] == 875_000
    assert preview_by_mls["W930002"]["parking"] == 2
    readiness_by_contact = {item["contact_name"]: item for item in result.watchlist_readiness_preview}
    assert readiness_by_contact["Amy Yuen"]["preview_status_counts"] == {"listed_for_sale": 1}


def test_watchlist_source_readiness_uses_alert_score_threshold():
    db = make_session()
    contact = models.Contact(name="Broad Buyer", email="broad@example.com", preferred_language="en")
    db.add(contact)
    db.commit()
    db.refresh(contact)
    watchlist = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=contact.id,
            name="Broad buyer watch",
            watch_type="buyer_listing_match",
            criteria={},
            notification_channel="codex_app",
            review_mode="manual_review",
        ),
    )
    db.add(
        models.Property(
            street="1 Main Street",
            city="Toronto",
            province="ON",
            neighborhood="Toronto",
            property_type="detached",
            status="listed_for_sale",
            bedrooms=3,
            bathrooms=2,
            parking=1,
            listing_price=850000,
            mls_number="BROAD001",
            notes="Only the listing status matches; no client targeting criteria are present.",
        )
    )
    db.commit()

    checklist = crud.get_watchlist_data_intake_checklist(db)
    item = next(row for row in checklist.items if row.watchlist_id == watchlist.id)

    assert item.source_ready is False
    assert item.current_matching_rows == 0
    assert item.missing_required_statuses == ["listed_for_sale"]
    check_result = crud.run_watchlist_check(db, watchlist.id)
    assert check_result.matched_properties == 0
    assert check_result.created_count == 0


def test_new_watchlists_default_to_gmail_draft_not_auto_send():
    db = make_session()
    contact = models.Contact(name="Default Draft Client", email="client@example.com", preferred_language="en")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    created = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=contact.id,
            name="Default draft watch",
            watch_type="buyer_listing_match",
            criteria={"areas": ["Milton"], "types": ["detached"]},
        ),
    )
    defaulted = crud.create_default_watchlist_for_contact(db, contact.id)

    assert created.review_mode == "auto_gmail_draft"
    assert defaulted.review_mode == "auto_gmail_draft"
    assert created.review_mode != "auto_send_approved"
    assert defaulted.review_mode != "auto_send_approved"


def test_watchlist_schedule_update_normalizes_custom_times_and_timezone():
    db = make_session()
    _tom_watch, amy_watch = seed_watchlists(db)

    updated = crud.update_watchlist(
        db,
        amy_watch.id,
        schemas.ClientWatchlistUpdate(
            schedule={
                "times": ["9:00", "15:00", "bad", "18:00", "15:00", "25:00"],
                "timezone": "Not/AZone",
            }
        ),
    )

    assert updated.schedule == {"times": ["09:00", "15:00", "18:00"], "timezone": "America/Toronto"}
    row = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.id == amy_watch.id).one()
    assert json.loads(row.schedule_json) == updated.schedule
    assert row.next_check_at is not None


def test_contact_level_schedule_update_updates_all_contact_watchlists_only():
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)
    second_tom_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=tom_watch.contact_id,
            name="Tom Lin - Sold comps backup",
            watch_type="seller_listing_and_sold",
            criteria={"areas": ["Thornhill"], "types": ["townhouse"]},
            notification_channel="codex_app",
            review_mode="auto_gmail_draft",
        ),
    )

    updated = crud.update_contact_watchlist_schedule(
        db,
        tom_watch.contact_id,
        schemas.ContactWatchlistScheduleUpdate(
            schedule={
                "times": ["9:00", "15:00", "bad", "18:00", "15:00"],
                "timezone": "Not/AZone",
            }
        ),
    )

    assert updated is not None
    assert {item.id for item in updated} == {tom_watch.id, second_tom_watch.id}
    assert {tuple(item.schedule["times"]) for item in updated} == {("09:00", "15:00", "18:00")}
    assert {item.schedule["timezone"] for item in updated} == {"America/Toronto"}

    tom_rows = (
        db.query(models.ClientWatchlist)
        .filter(models.ClientWatchlist.contact_id == tom_watch.contact_id)
        .all()
    )
    assert all(json.loads(row.schedule_json)["times"] == ["09:00", "15:00", "18:00"] for row in tom_rows)
    assert all(row.next_check_at is not None for row in tom_rows)

    amy_row = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.id == amy_watch.id).one()
    assert json.loads(amy_row.schedule_json)["times"] == ["09:00"]


def test_watchlist_notification_channel_is_limited_to_supported_destinations():
    db = make_session()
    _tom_watch, amy_watch = seed_watchlists(db)

    for channel in ["codex_app", "app_push", "in_app"]:
        updated = crud.update_watchlist(
            db,
            amy_watch.id,
            schemas.ClientWatchlistUpdate(notification_channel=channel),
        )
        assert updated.notification_channel == channel

    with pytest.raises(ValueError, match="invalid_notification_channel"):
        crud.update_watchlist(
            db,
            amy_watch.id,
            schemas.ClientWatchlistUpdate(notification_channel="sms"),
        )

    contact = models.Contact(name="Bad Channel Client", email="client@example.com")
    db.add(contact)
    db.commit()
    db.refresh(contact)
    with pytest.raises(ValueError, match="invalid_notification_channel"):
        crud.create_watchlist(
            db,
            schemas.ClientWatchlistCreate(
                contact_id=contact.id,
                name="Bad channel",
                watch_type="buyer_listing_match",
                notification_channel="webhook",
            ),
        )

    row = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.id == amy_watch.id).one()
    row.notification_channel = "legacy_bad_channel"
    db.add(row)
    db.commit()

    schema = crud.get_watchlists(db, contact_id=amy_watch.contact_id)[0]
    assert schema.notification_channel == "codex_app"


def test_contact_level_notification_channel_updates_all_contact_watchlists_only():
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)
    second_tom_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=tom_watch.contact_id,
            name="Tom Lin - Rental backup",
            watch_type="landlord_rental_market",
            criteria={"areas": ["Thornhill"], "types": ["townhouse"]},
            notification_channel="codex_app",
            review_mode="auto_gmail_draft",
        ),
    )

    updated = crud.update_contact_watchlist_notification_channel(
        db,
        tom_watch.contact_id,
        schemas.ContactWatchlistNotificationChannelUpdate(notification_channel="in_app"),
    )

    assert updated is not None
    assert {item.id for item in updated} == {tom_watch.id, second_tom_watch.id}
    assert {item.notification_channel for item in updated} == {"in_app"}

    amy_row = crud.get_watchlist(db, amy_watch.id)
    assert amy_row.notification_channel == "codex_app"

    with pytest.raises(ValueError, match="invalid_notification_channel"):
        crud.update_contact_watchlist_notification_channel(
            db,
            tom_watch.contact_id,
            schemas.ContactWatchlistNotificationChannelUpdate(notification_channel="sms"),
        )


def test_voice_memo_creates_named_seller_contact_and_watchlist():
    db = make_session()
    memo = (
        "Tom Lin,賣家,7月15日之後,他的房客會離開。"
        "他要賣的是一個Freehold Townhouse 107 Brownstone Circle,Thom Hill, Ontario。"
        "最好是房客7月15號離開以後我們兩個再進去看看甚至帶裝修師傅去看看"
        "裡面的狀況如何怎麼樣做一個最簡單的整理但是可以比較presentable"
    )

    result = crud.workflow_voice_memo(db, memo)

    assert result.success is True
    assert result.client_name == "Tom Lin"
    assert result.extracted_data is not None
    assert result.extracted_data["watch_type"] == "seller_listing_and_sold"

    contact = db.query(models.Contact).filter(models.Contact.name == "Tom Lin").one()
    assert "seller" in contact.client_type
    assert contact.preferred_language == "zh-tw"
    assert contact.source == "voice_memo"
    assert "107 Brownstone Circle" in contact.ai_summary
    assert "Thornhill" in contact.ai_summary

    areas = json.loads(contact.preferred_areas)
    prefs = json.loads(contact.property_preferences)
    assert areas == ["Thornhill"]
    assert prefs["property_address"] == "107 Brownstone Circle"
    assert prefs["available_after"] == "7月15日後"
    assert prefs["types"] == ["townhouse"]
    assert "freehold" in prefs["must_haves"]

    watchlist = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.contact_id == contact.id).one()
    criteria = json.loads(watchlist.criteria_json)
    schedule = json.loads(watchlist.schedule_json)
    assert watchlist.id == result.extracted_data["watchlist_id"]
    assert watchlist.watch_type == "seller_listing_and_sold"
    assert watchlist.notification_channel == "codex_app"
    assert watchlist.review_mode == "auto_gmail_draft"
    assert watchlist.status == "active"
    assert schedule == {"times": ["09:00", "15:00", "18:00"], "timezone": "America/Toronto"}
    assert criteria["areas"] == ["Thornhill"]
    assert criteria["types"] == ["townhouse"]
    assert criteria["property_address"] == "107 Brownstone Circle"
    assert criteria["available_after"] == "7月15日後"
    assert "freehold" in criteria["must_haves"]


def test_voice_memo_captures_client_email_for_gmail_delivery():
    db = make_session()
    memo = (
        "Tom Lin email tom.lin@example.com, 賣家, Thornhill townhouse, "
        "要看 active listing 和 sold comparable。"
    )

    result = crud.workflow_voice_memo(db, memo)

    assert result.success is True
    assert result.extracted_data["client_email"] == "tom.lin@example.com"
    contact = db.query(models.Contact).filter(models.Contact.name == "Tom Lin").one()
    assert contact.email == "tom.lin@example.com"
    checklist = crud.get_watchlist_data_intake_checklist(db)
    item = next(row for row in checklist.items if row.contact_id == contact.id)
    assert item.contact_email_present is True
    assert item.delivery_ready is True


def test_voice_memo_does_not_overwrite_existing_different_email():
    db = make_session()
    contact = models.Contact(name="Tom Lin", email="original@example.com", preferred_language="en")
    db.add(contact)
    db.commit()

    result = crud.workflow_voice_memo(db, "Tom Lin email new@example.com wants Thornhill townhouse comps.")

    db.refresh(contact)
    assert contact.email == "original@example.com"
    assert result.extracted_data["client_email"] == "new@example.com"
    assert result.extracted_data["client_email_conflict"] is True


def test_voice_memo_creates_buyer_watchlist_with_search_criteria():
    db = make_session()
    memo = (
        "Amy Yuen,買家,她想要在Holden Hill買差不多90萬以內的獨立屋，"
        "至少要有兩個房間，要有一個車庫。"
    )

    result = crud.workflow_voice_memo(db, memo)

    assert result.success is True
    assert result.client_name == "Amy Yuen"
    assert result.extracted_data is not None
    assert result.extracted_data["watch_type"] == "buyer_listing_match"

    contact = db.query(models.Contact).filter(models.Contact.name == "Amy Yuen").one()
    assert "buyer" in contact.client_type
    assert contact.preferred_language == "zh-tw"
    assert contact.budget_max == 900000

    areas = json.loads(contact.preferred_areas)
    prefs = json.loads(contact.property_preferences)
    assert areas == ["Halton Hills"]
    assert prefs["types"] == ["detached"]
    assert prefs["bedrooms_min"] == 2
    assert prefs["parking_min"] == 1
    assert "garage" in prefs["must_haves"]

    watchlist = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.contact_id == contact.id).one()
    criteria = json.loads(watchlist.criteria_json)
    schedule = json.loads(watchlist.schedule_json)
    assert watchlist.id == result.extracted_data["watchlist_id"]
    assert watchlist.watch_type == "buyer_listing_match"
    assert watchlist.notification_channel == "codex_app"
    assert watchlist.review_mode == "auto_gmail_draft"
    assert schedule == {"times": ["09:00", "15:00", "18:00"], "timezone": "America/Toronto"}
    assert criteria["areas"] == ["Halton Hills"]
    assert criteria["types"] == ["detached"]
    assert criteria["max_price"] == 900000
    assert criteria["bedrooms_min"] == 2
    assert criteria["parking_min"] == 1
    assert "garage" in criteria["must_haves"]


def test_voice_memo_creates_tenant_rental_watchlist_with_rent_criteria():
    db = make_session()
    memo = (
        "租客 Cindy Chen 想在 North York 租 condo，"
        "租金2700以內，至少兩個房間，一個停車位。"
    )

    result = crud.workflow_voice_memo(db, memo)

    assert result.success is True
    assert result.client_name == "Cindy Chen"
    assert result.extracted_data is not None
    assert result.extracted_data["watch_type"] == "tenant_rental_match"

    contact = db.query(models.Contact).filter(models.Contact.name == "Cindy Chen").one()
    assert "tenant" in contact.client_type
    assert contact.budget_max == 2700

    areas = json.loads(contact.preferred_areas)
    prefs = json.loads(contact.property_preferences)
    assert areas == ["North York"]
    assert prefs["types"] == ["condo"]
    assert prefs["bedrooms_min"] == 2
    assert prefs["parking_min"] == 1

    watchlist = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.contact_id == contact.id).one()
    criteria = json.loads(watchlist.criteria_json)
    assert watchlist.watch_type == "tenant_rental_match"
    assert watchlist.notification_channel == "codex_app"
    assert watchlist.review_mode == "auto_gmail_draft"
    assert criteria["areas"] == ["North York"]
    assert criteria["types"] == ["condo"]
    assert criteria["max_price"] == 2700
    assert criteria["bedrooms_min"] == 2
    assert criteria["parking_min"] == 1


def test_voice_memo_creates_landlord_rental_market_watchlist():
    db = make_session()
    memo = (
        "房東 David Wong 有一套 townhouse 在 Thornhill，"
        "想知道同社區最近租掉多少錢，也要看新的出租競爭房源。"
    )

    result = crud.workflow_voice_memo(db, memo)

    assert result.success is True
    assert result.client_name == "David Wong"
    assert result.extracted_data is not None
    assert result.extracted_data["watch_type"] == "landlord_rental_market"

    contact = db.query(models.Contact).filter(models.Contact.name == "David Wong").one()
    assert "landlord" in contact.client_type

    areas = json.loads(contact.preferred_areas)
    prefs = json.loads(contact.property_preferences)
    assert areas == ["Thornhill"]
    assert prefs["types"] == ["townhouse"]

    watchlist = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.contact_id == contact.id).one()
    criteria = json.loads(watchlist.criteria_json)
    assert watchlist.watch_type == "landlord_rental_market"
    assert watchlist.notification_channel == "codex_app"
    assert watchlist.review_mode == "auto_gmail_draft"
    assert criteria["areas"] == ["Thornhill"]
    assert criteria["types"] == ["townhouse"]


def test_watchlist_source_template_is_scoped_and_placeholder_safe():
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)

    tom_result = crud.build_watchlist_property_csv_template(db, tom_watch.id)
    assert tom_result is not None
    tom_filename, tom_csv = tom_result
    assert "tom-lin-seller-listing-sold-comps" in tom_filename

    tom_reader = csv.DictReader(StringIO(tom_csv))
    assert tom_reader.fieldnames == crud.PROPERTY_CSV_TEMPLATE_COLUMNS
    tom_rows = list(tom_reader)
    assert len(tom_rows) == 2
    assert {row["status"] for row in tom_rows} == {"For Sale", "Sold"}
    assert {row["property_type"] for row in tom_rows} == {"Townhouse"}
    assert {row["city"] for row in tom_rows} == {"Thornhill"}
    assert all(row["mls_number"].startswith("TEMPLATE_ONLY_") for row in tom_rows)
    assert all("TEMPLATE ONLY" in row["remarks"] for row in tom_rows)

    import_result = crud.import_properties_csv(db, tom_csv, dry_run=False)
    assert import_result.created == 0
    assert import_result.updated == 0
    assert import_result.skipped == 2
    assert db.query(func.count(models.Property.id)).scalar() == 0

    amy_result = crud.build_watchlist_property_csv_template(db, amy_watch.id)
    assert amy_result is not None
    _amy_filename, amy_csv = amy_result
    amy_rows = list(csv.DictReader(StringIO(amy_csv)))
    assert len(amy_rows) == 1
    assert amy_rows[0]["status"] == "For Sale"
    assert amy_rows[0]["property_type"] == "Detached"
    assert amy_rows[0]["list price"] == "900000"


def test_watchlist_source_kit_contains_templates_and_readme():
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    tom = db.query(models.Contact).filter(models.Contact.id == tom_watch.contact_id).one()
    tom.email = None
    db.add(tom)
    db.commit()

    filename, content = crud.build_watchlist_source_kit(db)

    assert filename == "skc-watchlist-source-kit.zip"
    with zipfile.ZipFile(BytesIO(content)) as bundle:
        names = set(bundle.namelist())
        assert "README.txt" in names
        assert "source-tasks.csv" in names
        assert "source-tasks.json" in names
        assert "source-status.json" in names
        assert "launch-action-pack.txt" in names
        assert "gmail-saved-search-feed-setup.txt" in names
        assert "client-email-tasks.csv" in names
        assert "skc-watchlist-import-template.csv" in names
        assert any("tom-lin-seller-listing-sold-comps" in name for name in names)
        assert any("amy-yuen-buyer-listing-match" in name for name in names)
        assert any(name.endswith(".json.disabled") and "tom-lin" in name for name in names)
        assert any(name.startswith("saved-searches/") and "tom-lin" in name for name in names)
        assert any(name.startswith("saved-searches/") and "amy-yuen" in name for name in names)
        readme = bundle.read("README.txt").decode("utf-8")
        assert "CSV drop folder" in readme
        assert "source-tasks.csv" in readme
        assert "source-status.json" in readme
        assert "launch-action-pack.txt" in readme
        assert "gmail-saved-search-feed-setup.txt" in readme
        assert "client-email-tasks.csv" in readme
        assert "Missing client emails: 1" in readme
        assert "saved-searches/*.txt" in readme
        assert "RESO/OData JSON templates" in readme
        assert "Tom Lin" in readme
        assert "Amy Yuen" in readme
        assert "Gmail query" in readme
        assert "Saved search name" in readme
        assert "SKC Tom Lin - Seller Active + Sold Comps" in readme
        assert "REALM/TRREB criteria" in readme
        tasks = list(csv.DictReader(StringIO(bundle.read("source-tasks.csv").decode("utf-8"))))
        assert {row["contact_name"] for row in tasks} == {"Tom Lin", "Amy Yuen"}
        assert any(row["saved_search_name"] == "SKC Tom Lin - Seller Active + Sold Comps" for row in tasks)
        source_status = json.loads(bundle.read("source-status.json").decode("utf-8"))
        assert source_status["reso_connector"]["status"] == "disabled"
        source_tasks_json = json.loads(bundle.read("source-tasks.json").decode("utf-8"))
        assert source_tasks_json["task_count"] == 2
        launch_action_pack = bundle.read("launch-action-pack.txt").decode("utf-8")
        assert "SKC CRM Launch Action Pack" in launch_action_pack
        assert "RESO connector: disabled" in launch_action_pack
        gmail_setup = bundle.read("gmail-saved-search-feed-setup.txt").decode("utf-8")
        assert "Gmail Saved-Search Feed Setup" in gmail_setup
        assert "READ GMAIL" in gmail_setup
        assert "Do not scrape MLS/REALM/TRREB pages" in gmail_setup
        assert "SKC Tom Lin - Seller Active + Sold Comps" in gmail_setup
        email_tasks = list(csv.DictReader(StringIO(bundle.read("client-email-tasks.csv").decode("utf-8"))))
        assert [row["contact_name"] for row in email_tasks] == ["Tom Lin"]
        assert email_tasks[0]["client_email_needed"] == "yes"
        assert "Gmail Draft or Auto Send" in email_tasks[0]["review_mode_blocker"]
        setup_text = bundle.read(
            next(name for name in names if name.startswith("saved-searches/") and "tom-lin" in name)
        ).decode("utf-8")
        reso_template = json.loads(bundle.read(
            next(name for name in names if name.endswith(".json.disabled") and "tom-lin" in name)
        ).decode("utf-8"))
        assert "REALM/TRREB Saved Search Setup" in setup_text
        assert "Required export statuses" in setup_text
        assert "Setup steps" in setup_text
        assert "value" in reso_template
        assert len(reso_template["value"]) == 2
        assert reso_template["value"][0]["PublicRemarks"].startswith("TEMPLATE ONLY")
        assert "Setup steps" in readme


def test_client_email_tasks_csv_lists_only_missing_email_blockers():
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    tom = db.query(models.Contact).filter(models.Contact.id == tom_watch.contact_id).one()
    tom.email = None
    db.add(tom)
    db.commit()

    filename, content = crud.build_client_email_tasks_csv(db)
    rows = list(csv.DictReader(StringIO(content.decode("utf-8"))))

    assert filename == "client-email-tasks.csv"
    assert [row["contact_name"] for row in rows] == ["Tom Lin"]
    assert rows[0]["contact_id"] == str(tom_watch.contact_id)
    assert rows[0]["watchlist_id"] == str(tom_watch.id)
    assert rows[0]["client_email"] == ""
    assert rows[0]["client_email_needed"] == "yes"
    assert "Gmail Draft or Auto Send" in rows[0]["review_mode_blocker"]


def test_operator_handoff_status_reports_generated_helper_files(tmp_path, monkeypatch):
    drop_folder = tmp_path / "watchlist-imports"
    drop_folder.mkdir()
    (drop_folder / "watchlist-next-actions.md").write_text("# Next\n", encoding="utf-8")
    (drop_folder / "client-email-tasks.template.csv.disabled").write_text(
        "contact_id,contact_name,client_email\n7,Tom Lin,\n",
        encoding="utf-8",
    )
    (drop_folder / "gmail-saved-search-feed-setup.txt").write_text(
        "Gmail saved-search setup\n",
        encoding="utf-8",
    )
    saved_search_dir = drop_folder / "saved-searches"
    saved_search_dir.mkdir()
    (saved_search_dir / "1-tom-lin.txt").write_text("Saved search: SKC Tom Lin\n", encoding="utf-8")
    template_dir = drop_folder / "source-templates"
    template_dir.mkdir()
    (template_dir / "1-tom-lin.template.csv.disabled").write_text(
        "mls_number,street,status\nTEMPLATE_ONLY_TOM,REPLACE,For Sale\n",
        encoding="utf-8",
    )
    automation_path = tmp_path / "automation.toml"
    automation_path.write_text(
        'id = "skc-crm-watchlist-check"\nstatus = "ACTIVE"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_DIR", str(drop_folder))
    monkeypatch.setenv("WATCHLIST_AUTOMATION_CONFIG_PATH", str(automation_path))

    status = crud.get_watchlist_operator_handoff_status()

    assert status.automation_id == "skc-crm-watchlist-check"
    assert status.automation_status == "ACTIVE"
    assert status.drop_folder == str(drop_folder)
    assert status.drop_folder_exists is True
    assert status.helper_files_ready is True
    assert {item.filename for item in status.files} == {
        "watchlist-next-actions.md",
        "client-email-tasks.template.csv.disabled",
        "gmail-saved-search-feed-setup.txt",
        "saved-searches/1-tom-lin.txt",
        "source-templates/1-tom-lin.template.csv.disabled",
    }
    assert all(item.exists for item in status.files)
    assert all(item.importable_csv is False for item in status.files)
    assert status.importable_csv_count == 0
    assert status.pending_csv_count == 0
    assert status.processed_csv_count == 0
    assert status.non_importable_file_count == 5
    assert status.disabled_template_count == 2
    assert status.instruction_file_count == 3
    assert "2 per-client source handoff file" in status.message
    assert "5 helper/template" in status.message
    source_kit_filenames = {item.filename for item in status.source_kit_files}
    assert "README.txt" in source_kit_filenames
    assert "source-status.json" in source_kit_filenames
    assert "launch-action-pack.txt" in source_kit_filenames
    assert "gmail-saved-search-feed-setup.txt" in source_kit_filenames
    assert "client-email-tasks.csv" in source_kit_filenames
    assert any(item.filename == "client-email-tasks.csv" and item.importable for item in status.source_kit_files)
    assert "saved-searches/*.txt" in status.next_step
    assert "09:00, 15:00, 18:00" in status.schedule_summary


def test_watchlist_run_logs_store_summary_and_redact_secret_payload_keys():
    db = make_session()

    first = crud.create_watchlist_run_log(
        db,
        schemas.WatchlistRunLogCreate(
            run_type="codex_automation",
            status="success",
            checked_count=2,
            created_alerts=1,
            matched_properties=3,
            active_count=2,
            due_count=2,
            pending_alert_count=1,
            source_status="No property/listing rows are loaded.",
            message="checked=2, created_alerts=1, matched=3, source_rows=0",
            payload={
                "safe": "visible",
                "refresh_token": "should-not-persist",
                "nested": {"api_key": "also-redacted", "count": 2},
            },
        ),
    )
    second = crud.create_watchlist_run_log(
        db,
        schemas.WatchlistRunLogCreate(
            run_type="manual",
            status="failed",
            error="example failure",
            payload={"ok": False},
        ),
    )

    assert first.payload["safe"] == "visible"
    assert first.payload["refresh_token"] == "[redacted]"
    assert first.payload["nested"]["api_key"] == "[redacted]"
    assert first.payload["nested"]["count"] == 2

    rows = crud.get_watchlist_run_logs(db, limit=10)
    assert [row.id for row in rows] == [second.id, first.id]
    assert rows[0].status == "failed"
    assert rows[1].checked_count == 2
    assert rows[1].created_alerts == 1


def test_property_source_status_reports_csv_drop_folder_pending_files(tmp_path, monkeypatch):
    db = make_session()
    drop_folder = tmp_path / "watchlist-imports"
    drop_folder.mkdir()
    imported_csv = drop_folder / "already-imported.csv"
    pending_csv = drop_folder / "pending.csv"
    imported_csv.write_text("mls_number,street\nN1,One Street\n", encoding="utf-8")
    pending_csv.write_text("mls_number,street\nN2,Two Street\n", encoding="utf-8")
    imported_hash = hashlib.sha256(imported_csv.read_bytes()).hexdigest()
    (drop_folder / "watchlist-next-actions.md").write_text("# Next\n", encoding="utf-8")
    saved_search_dir = drop_folder / "saved-searches"
    saved_search_dir.mkdir()
    (saved_search_dir / "1-tom-lin.txt").write_text("Saved search\n", encoding="utf-8")
    template_dir = drop_folder / "source-templates"
    template_dir.mkdir()
    (template_dir / "1-tom-lin.template.csv.disabled").write_text(
        "mls_number,street\nTEMPLATE_ONLY,REPLACE\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "imported_csv_state.json"
    state_path.write_text(
        json.dumps({"hashes": {imported_hash: {"path": str(imported_csv)}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_DIR", str(drop_folder))
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_STATE_PATH", str(state_path))

    status = crud.get_property_source_status(db)

    assert status.csv_drop_folder == str(drop_folder)
    assert status.csv_drop_folder_exists is True
    assert status.csv_drop_folder_file_count == 2
    assert status.csv_drop_folder_importable_count == 2
    assert status.csv_drop_folder_pending_count == 1
    assert status.csv_drop_folder_processed_count == 1
    assert status.csv_drop_folder_total_file_count == 5
    assert status.csv_drop_folder_non_importable_count == 3
    assert status.csv_drop_folder_disabled_template_count == 1
    assert status.csv_drop_folder_instruction_file_count == 2
    assert status.csv_drop_folder_state_path == str(state_path)


def test_property_source_status_distinguishes_helper_files_from_importable_csv(tmp_path, monkeypatch):
    db = make_session()
    drop_folder = tmp_path / "watchlist-imports"
    drop_folder.mkdir()
    (drop_folder / "watchlist-next-actions.md").write_text("# Next\n", encoding="utf-8")
    saved_search_dir = drop_folder / "saved-searches"
    saved_search_dir.mkdir()
    (saved_search_dir / "1-tom-lin.txt").write_text("Saved search\n", encoding="utf-8")
    template_dir = drop_folder / "source-templates"
    template_dir.mkdir()
    (template_dir / "1-tom-lin.template.csv.disabled").write_text(
        "mls_number,street\nTEMPLATE_ONLY,REPLACE\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "imported_csv_state.json"
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_DIR", str(drop_folder))
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_STATE_PATH", str(state_path))

    status = crud.get_property_source_status(db)

    assert status.csv_drop_folder_file_count == 0
    assert status.csv_drop_folder_importable_count == 0
    assert status.csv_drop_folder_pending_count == 0
    assert status.csv_drop_folder_processed_count == 0
    assert status.csv_drop_folder_total_file_count == 3
    assert status.csv_drop_folder_non_importable_count == 3
    assert status.csv_drop_folder_disabled_template_count == 1
    assert status.csv_drop_folder_instruction_file_count == 2
    assert "no importable REALM/TRREB CSV or RESO JSON" in status.message


def test_csv_drop_folder_import_can_preview_import_and_skip_processed_files(tmp_path, monkeypatch):
    db = make_session()
    seed_watchlists(db)
    drop_folder = tmp_path / "watchlist-imports"
    drop_folder.mkdir()
    csv_path = drop_folder / "realm-export.csv"
    csv_path.write_text(sample_csv(), encoding="utf-8")
    state_path = tmp_path / "imported_csv_state.json"
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_DIR", str(drop_folder))
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_STATE_PATH", str(state_path))

    preview = crud.import_properties_csv_drop_folder(db, dry_run=True)

    assert preview.success is True
    assert preview.dry_run is True
    assert preview.processed_count == 1
    assert preview.pending_before == 1
    assert preview.pending_after == 1
    assert preview.imported[0].status == "previewed"
    assert preview.imported[0].result is not None
    assert len(preview.imported[0].result.watchlist_match_preview) == 3
    assert len(preview.imported[0].result.watchlist_readiness_preview) == 2
    assert db.query(func.count(models.Property.id)).scalar() == 0
    assert not state_path.exists()

    imported = crud.import_properties_csv_drop_folder(db, dry_run=False)

    assert imported.success is True
    assert imported.processed_count == 1
    assert imported.pending_before == 1
    assert imported.pending_after == 0
    assert imported.imported[0].status == "imported"
    assert db.query(func.count(models.Property.id)).scalar() == 4
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["hashes"]) == 1

    duplicate = crud.import_properties_csv_drop_folder(db, dry_run=False)

    assert duplicate.processed_count == 0
    assert duplicate.pending_before == 0
    assert duplicate.pending_after == 0
    assert len(duplicate.skipped) == 1
    assert duplicate.skipped[0].status == "already_imported"
    assert db.query(func.count(models.Property.id)).scalar() == 4


def test_csv_drop_folder_imports_completed_per_client_source_csv_from_subfolders(tmp_path, monkeypatch):
    db = make_session()
    seed_watchlists(db)
    drop_folder = tmp_path / "watchlist-imports"
    template_dir = drop_folder / "source-templates"
    template_dir.mkdir(parents=True)
    disabled_template = template_dir / "1-tom-lin.template.csv.disabled"
    disabled_template.write_text(
        "mls_number,street,status\nTEMPLATE_ONLY,REPLACE,For Sale\n",
        encoding="utf-8",
    )
    completed_csv = template_dir / "1-tom-lin.csv"
    completed_csv.write_text(sample_csv(), encoding="utf-8")
    state_path = tmp_path / "imported_csv_state.json"
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_DIR", str(drop_folder))
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_STATE_PATH", str(state_path))

    status = crud.get_property_source_status(db)

    assert status.csv_drop_folder_file_count == 1
    assert status.csv_drop_folder_importable_count == 1
    assert status.csv_drop_folder_pending_count == 1
    assert status.csv_drop_folder_disabled_template_count == 1

    imported = crud.import_properties_csv_drop_folder(db, dry_run=False)

    assert imported.success is True
    assert imported.processed_count == 1
    assert imported.imported[0].file == str(completed_csv)
    assert imported.imported[0].status == "imported"
    assert db.query(func.count(models.Property.id)).scalar() == 4
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["hashes"]) == 1


def test_drop_folder_imports_authorized_reso_json_from_source_subfolders(tmp_path, monkeypatch):
    db = make_session()
    seed_watchlists(db)
    drop_folder = tmp_path / "watchlist-imports"
    template_dir = drop_folder / "source-templates"
    template_dir.mkdir(parents=True)
    disabled_template = template_dir / "1-tom-lin.template.json.disabled"
    disabled_template.write_text(
        json.dumps({"value": [{"ListingKey": "TEMPLATE_ONLY_1"}]}),
        encoding="utf-8",
    )
    completed_json = template_dir / "1-tom-lin.json"
    completed_json.write_text(
        json.dumps(
            {
                "value": [
                    {
                        "ListingKey": "N960001",
                        "UnparsedAddress": "109 Brownstone Circle, Thornhill, ON L4J 7P5",
                        "City": "Thornhill",
                        "CityRegion": "Thornhill",
                        "StandardStatus": "Active",
                        "TransactionType": "For Sale",
                        "PropertySubType": "Townhouse",
                        "ListPrice": 1199000,
                        "BedroomsTotal": 3,
                        "BathroomsTotalInteger": 3,
                        "ParkingTotal": 1,
                        "ListingContractDate": "2026-06-11T09:00:00Z",
                    },
                    {
                        "ListingKey": "N960002",
                        "UnparsedAddress": "111 Brownstone Circle, Thornhill, ON L4J 7P5",
                        "City": "Thornhill",
                        "CityRegion": "Thornhill",
                        "StandardStatus": "Closed",
                        "TransactionType": "For Sale",
                        "PropertySubType": "Townhouse",
                        "ListPrice": 1129000,
                        "ClosePrice": 1150000,
                        "BedroomsTotal": 3,
                        "BathroomsTotalInteger": 3,
                        "ParkingTotal": 1,
                        "CloseDate": "2026-06-10T12:00:00Z",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    state_path = tmp_path / "imported_csv_state.json"
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_DIR", str(drop_folder))
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_STATE_PATH", str(state_path))

    status = crud.get_property_source_status(db)

    assert status.csv_drop_folder_file_count == 1
    assert status.csv_drop_folder_importable_count == 1
    assert status.csv_drop_folder_pending_count == 1
    assert status.csv_drop_folder_disabled_template_count == 1
    assert "RESO JSON" in status.message

    preview = crud.import_properties_csv_drop_folder(db, dry_run=True)

    assert preview.success is True
    assert preview.processed_count == 1
    assert preview.imported[0].status == "reso_json_previewed"
    assert preview.imported[0].result is not None
    assert preview.imported[0].result.created == 2
    assert db.query(func.count(models.Property.id)).scalar() == 0

    imported = crud.import_properties_csv_drop_folder(db, dry_run=False)

    assert imported.success is True
    assert imported.processed_count == 1
    assert imported.imported[0].file == str(completed_json)
    assert imported.imported[0].status == "reso_json_imported"
    assert db.query(func.count(models.Property.id)).scalar() == 2
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert next(iter(state["hashes"].values()))["source_type"] == "reso_json"

    duplicate = crud.import_properties_csv_drop_folder(db, dry_run=False)

    assert duplicate.processed_count == 0
    assert duplicate.pending_before == 0
    assert len(duplicate.skipped) == 1
    assert duplicate.skipped[0].status == "already_imported"


def test_csv_drop_folder_imports_client_email_task_csv(tmp_path, monkeypatch):
    db = make_session()
    contact = models.Contact(name="Tom Lin", preferred_language="zh-tw")
    db.add(contact)
    db.commit()
    db.refresh(contact)
    drop_folder = tmp_path / "watchlist-imports"
    drop_folder.mkdir()
    email_csv = drop_folder / "client-email-tasks.csv"
    email_csv.write_text(
        "contact_id,contact_name,client_email,watchlist_id,watchlist_name,review_mode_blocker,client_email_needed,next_action\n"
        f"{contact.id},Tom Lin,tom.lin@example.com,1,Tom Watch,Gmail Draft cannot be addressed,yes,Add email\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "imported_csv_state.json"
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_DIR", str(drop_folder))
    monkeypatch.setenv("WATCHLIST_CSV_IMPORT_STATE_PATH", str(state_path))

    imported = crud.import_properties_csv_drop_folder(db, dry_run=False)

    assert imported.success is True
    assert imported.processed_count == 1
    assert imported.imported[0].status == "contact_email_imported"
    assert imported.imported[0].result is not None
    assert imported.imported[0].result.updated == 1
    assert db.query(models.Contact).filter(models.Contact.id == contact.id).one().email == "tom.lin@example.com"
    assert db.query(func.count(models.Property.id)).scalar() == 0

    duplicate = crud.import_properties_csv_drop_folder(db, dry_run=False)

    assert duplicate.processed_count == 0
    assert len(duplicate.skipped) == 1
    assert duplicate.skipped[0].status == "already_imported"


def test_manual_csv_import_accepts_client_email_task_csv():
    db = make_session()
    contact = models.Contact(name="Tom Lin", preferred_language="zh-tw")
    db.add(contact)
    db.commit()
    db.refresh(contact)
    email_csv = (
        "contact_id,contact_name,client_email,watchlist_id,watchlist_name,review_mode_blocker,client_email_needed,next_action\n"
        f"{contact.id},Tom Lin,tom.lin@example.com,1,Tom Watch,Gmail Draft cannot be addressed,yes,Add email\n"
    )

    preview = crud.import_properties_csv(db, email_csv, dry_run=True)

    assert preview.success is True
    assert preview.dry_run is True
    assert preview.updated == 1
    assert preview.preview_rows[0]["action"] == "update_contact_email"
    assert db.query(models.Contact).filter(models.Contact.id == contact.id).one().email is None
    assert db.query(func.count(models.Property.id)).scalar() == 0

    imported = crud.import_properties_csv(db, email_csv, dry_run=False)

    assert imported.success is True
    assert imported.updated == 1
    assert "contact email update" in imported.message
    assert db.query(models.Contact).filter(models.Contact.id == contact.id).one().email == "tom.lin@example.com"
    assert db.query(func.count(models.Property.id)).scalar() == 0


def test_watchlist_pipeline_creates_notifications_drafts_and_dedupes_alerts():
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)

    import_result = crud.import_properties_csv(db, sample_csv(), dry_run=False)
    assert import_result.success is True
    assert import_result.created == 4

    tom_result = crud.run_watchlist_check(db, tom_watch.id)
    amy_result = crud.run_watchlist_check(db, amy_watch.id)

    assert tom_result.created_count == 2
    assert amy_result.created_count == 1
    assert db.query(func.count(models.WatchlistAlert.id)).scalar() == 3
    assert db.query(func.count(models.WatchlistNotification.id)).scalar() == 2
    notification_statuses = {
        row.status for row in db.query(models.WatchlistNotification).all()
    }
    assert notification_statuses == {"queued_for_codex_report"}
    notifications = db.query(models.WatchlistNotification).order_by(models.WatchlistNotification.id.asc()).all()
    digest_notification = notifications[0]
    single_notification = notifications[1]
    assert "Digest: 2 matching item(s) for Tom Lin." in digest_notification.body
    assert "Why notify:" in digest_notification.body
    assert "Draft:" in digest_notification.body
    assert "Freshness:" in digest_notification.body
    assert (
        f"Review in CRM: /watchlists?contact_id={tom_watch.contact_id}"
        f"&alert_id={digest_notification.alert_id}&watchlist_id={tom_watch.id}"
    ) in digest_notification.body
    assert "Next: review the digest draft and source rows before sending any client email." in digest_notification.body
    assert "Property:" in single_notification.body
    assert "Why it matches:" in single_notification.body
    assert "Freshness:" in single_notification.body
    assert (
        f"Review in CRM: /watchlists?contact_id={amy_watch.contact_id}"
        f"&alert_id={single_notification.alert_id}&watchlist_id={amy_watch.id}"
    ) in single_notification.body
    assert "Next: review the alert and draft before sending any client email." in single_notification.body

    alert = (
        db.query(models.WatchlistAlert)
        .filter(models.WatchlistAlert.contact_id == tom_watch.contact_id)
        .order_by(models.WatchlistAlert.id.asc())
        .first()
    )
    payload = json.loads(alert.payload_json)
    assert payload["match_score"] >= 35
    assert any("status:" in item for item in payload["matched_criteria"])
    assert payload["source_date"] in {"2026-06-09", "2026-06-10"}
    assert any(item.startswith("date: 2026-06-") for item in payload["matched_criteria"])
    assert payload["kevin_review_items"]
    assert "比對分數" in alert.analysis
    draft_result = crud.create_draft_from_watchlist_alert(db, alert.id)
    assert draft_result.success is True
    db.refresh(alert)
    assert alert.status == "draft_created"
    assert alert.interaction_id is not None
    interaction = db.query(models.Interaction).filter(models.Interaction.id == alert.interaction_id).one()
    assert interaction.generated_response_status == "pending_review"
    assert interaction.generated_response_type == "email_draft"
    draft_payload = json.loads(interaction.generated_response_content)
    assert "符合條件：" in draft_payload["body"]
    assert "寄出前我會再確認：" in draft_payload["body"]

    duplicate_result = crud.run_watchlist_check(db, tom_watch.id)
    assert duplicate_result.created_count == 0
    assert duplicate_result.matched_properties == 2
    assert db.query(func.count(models.WatchlistAlert.id)).scalar() == 3


def test_watchlist_digest_draft_explains_why_items_are_sent():
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.import_properties_csv(db, sample_csv(), dry_run=False)
    crud.run_watchlist_check(db, tom_watch.id)

    digest = crud.create_digest_draft_from_watchlist_alerts(db, tom_watch.id)

    assert digest.success is True
    assert digest.alert_count == 2
    assert digest.body is not None
    assert "這次值得寄給你" in digest.body
    assert "附近競爭房源" in digest.body
    assert "成交參考" in digest.body
    assert "$1,180,000 to $1,199,000" in digest.body
    assert "107 Brownstone Circle" in digest.body
    assert "符合條件：" in digest.body
    assert "寄出前我會再確認：" in digest.body


def test_buyer_digest_draft_explains_client_fit_before_sending():
    db = make_session()
    _tom_watch, amy_watch = seed_watchlists(db)
    amy = db.query(models.Contact).filter(models.Contact.id == amy_watch.contact_id).one()
    amy.preferred_language = "zh-tw"
    db.add(amy)
    db.commit()
    crud.import_properties_csv(db, sample_csv(), dry_run=False)
    crud.run_watchlist_check(db, amy_watch.id)

    digest = crud.create_digest_draft_from_watchlist_alerts(db, amy_watch.id)

    assert digest.success is True
    assert digest.body is not None
    assert "這次值得寄給你" in digest.body
    assert "符合買房條件的房源" in digest.body
    assert "$880,000" in digest.body
    assert "Halton Hills" in digest.body
    assert "detached" in digest.body
    assert "符合條件：" in digest.body
    assert "寄出前我會再確認：" in digest.body


def test_rental_digest_drafts_explain_tenant_and_landlord_reasons():
    db = make_session()
    tenant = models.Contact(name="Cindy Chen", email="tenant@example.com", preferred_language="zh-tw")
    landlord = models.Contact(name="David Wong", email="landlord@example.com", preferred_language="zh-tw")
    db.add_all([tenant, landlord])
    db.commit()
    db.refresh(tenant)
    db.refresh(landlord)

    tenant_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=tenant.id,
            name="Cindy Chen - Rental match",
            watch_type="tenant_rental_match",
            criteria={
                "areas": ["North York"],
                "types": ["condo"],
                "max_price": 2800,
                "bedrooms_min": 2,
                "parking_min": 1,
            },
            notification_channel="codex_app",
            review_mode="manual_review",
        ),
    )
    landlord_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=landlord.id,
            name="David Wong - Rental market",
            watch_type="landlord_rental_market",
            criteria={
                "areas": ["Thornhill"],
                "types": ["townhouse"],
            },
            notification_channel="codex_app",
            review_mode="manual_review",
        ),
    )
    crud.import_properties_csv(db, rental_csv(), dry_run=False)
    crud.run_watchlist_check(db, tenant_watch.id)
    crud.run_watchlist_check(db, landlord_watch.id)

    tenant_digest = crud.create_digest_draft_from_watchlist_alerts(db, tenant_watch.id)
    landlord_digest = crud.create_digest_draft_from_watchlist_alerts(db, landlord_watch.id)

    assert tenant_digest.success is True
    assert tenant_digest.body is not None
    assert "這次值得寄給你" in tenant_digest.body
    assert "符合租屋條件的租盤" in tenant_digest.body
    assert "$2,700/mo" in tenant_digest.body
    assert "North York" in tenant_digest.body
    assert "符合條件：" in tenant_digest.body
    assert "寄出前我會再確認：" in tenant_digest.body

    assert landlord_digest.success is True
    assert landlord_digest.body is not None
    assert "這次值得寄給你" in landlord_digest.body
    assert "附近租賃市場資料" in landlord_digest.body
    assert "競爭租盤" in landlord_digest.body
    assert "已租出參考" in landlord_digest.body
    assert "$3,900/mo to $4,100/mo" in landlord_digest.body
    assert "Thornhill" in landlord_digest.body
    assert "符合條件：" in landlord_digest.body
    assert "寄出前我會再確認：" in landlord_digest.body


def test_watchlist_alert_marks_stale_source_rows_as_context_not_new_update():
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    old_sold = (crud._utcnow() - timedelta(days=75)).date().isoformat()
    old_listed = (crud._utcnow() - timedelta(days=90)).date().isoformat()
    csv_text = textwrap.dedent(
        f"""\
        mls_number,street,city,community,status,property_type,list price,sold price,rent,list date,sold date,beds,baths,parking,url,remarks
        NOLD999,88 Brownstone Circle,Thornhill,Thornhill,Sold,Townhouse,1080000,1100000,,{old_listed},{old_sold},3,3,1,https://example.com/NOLD999,Freehold townhouse older sold comp near 107 Brownstone Circle
        """
    )
    crud.import_properties_csv(db, csv_text, dry_run=False)

    result = crud.run_watchlist_check(db, tom_watch.id)

    assert result.created_count == 1
    alert = db.query(models.WatchlistAlert).one()
    payload = json.loads(alert.payload_json)
    assert payload["freshness_status"] == "stale"
    assert payload["source_age_days"] >= 75
    assert "older sold/leased comp context" in payload["freshness_note"]
    notification = db.query(models.WatchlistNotification).one()
    assert "Freshness:" in notification.body
    assert "older sold/leased comp context" in notification.body


def test_watchlist_alerts_notifications_and_digest_are_newest_source_date_first():
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    csv_text = textwrap.dedent(
        """\
        mls_number,street,city,community,status,property_type,list price,sold price,rent,list date,sold date,beds,baths,parking,url,remarks
        NOLD001,101 Brownstone Circle,Thornhill,Thornhill,Sold,Townhouse,1120000,1130000,,2026-05-20,2026-06-01,3,3,1,https://example.com/NOLD001,Freehold townhouse older sold comp near 107 Brownstone Circle
        NNEW001,103 Brownstone Circle,Thornhill,Thornhill,Sold,Townhouse,1160000,1185000,,2026-06-01,2026-06-11,3,3,1,https://example.com/NNEW001,Freehold townhouse newest sold comp near 107 Brownstone Circle
        """
    )
    crud.import_properties_csv(db, csv_text, dry_run=False)

    result = crud.run_watchlist_check(db, tom_watch.id)

    assert result.created_count == 2
    assert [alert.summary.split(" | ")[0] for alert in result.alerts] == [
        "103 Brownstone Circle, Thornhill, ON",
        "101 Brownstone Circle, Thornhill, ON",
    ]
    notification = db.query(models.WatchlistNotification).one()
    assert notification.body.index("103 Brownstone Circle") < notification.body.index("101 Brownstone Circle")

    digest = crud.create_digest_draft_from_watchlist_alerts(db, tom_watch.id)

    assert digest.success is True
    assert digest.body.index("103 Brownstone Circle") < digest.body.index("101 Brownstone Circle")
    assert "最新資料日期：2026-06-11；資料期間：2026-06-01 至 2026-06-11。" in digest.body
    assert "日期： 2026-06-11" in digest.body
    assert "日期： 2026-06-01" in digest.body


def test_auto_gmail_draft_creates_gmail_metadata_without_sending(monkeypatch):
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    crud.import_properties_csv(db, sample_csv(), dry_run=False)

    created_drafts: list[int] = []
    send_calls: list[int] = []

    def fake_create_gmail_draft(db_arg, interaction_id, **_kwargs):
        interaction = db_arg.query(models.Interaction).filter(models.Interaction.id == interaction_id).one()
        draft = json.loads(interaction.generated_response_content)
        draft["gmail"] = {"draft_id": f"draft-{interaction_id}", "message_id": f"msg-{interaction_id}"}
        interaction.generated_response_content = json.dumps(draft)
        interaction.generated_response_status = "gmail_draft_created"
        db_arg.add(interaction)
        db_arg.commit()
        created_drafts.append(interaction_id)
        return schemas.GmailDraftActionResponse(
            success=True,
            message="Gmail draft created.",
            interaction_id=interaction_id,
            status="gmail_draft_created",
            account_email="superkevinchou@gmail.com",
            to_email="tom@example.com",
            gmail_draft_id=f"draft-{interaction_id}",
            gmail_message_id=f"msg-{interaction_id}",
        )

    def fake_send_gmail_draft(_db_arg, interaction_id, **_kwargs):
        send_calls.append(interaction_id)
        raise AssertionError("auto_gmail_draft must not send Gmail")

    monkeypatch.setattr(gmail_service, "create_gmail_draft_for_interaction", fake_create_gmail_draft)
    monkeypatch.setattr(gmail_service, "send_gmail_draft_for_interaction", fake_send_gmail_draft)

    result = crud.run_watchlist_check(db, tom_watch.id)

    assert result.created_count == 2
    assert len(created_drafts) == 1
    assert send_calls == []
    alerts = db.query(models.WatchlistAlert).order_by(models.WatchlistAlert.id.asc()).all()
    assert {alert.status for alert in alerts} == {"draft_created"}
    interaction_ids = {alert.interaction_id for alert in alerts}
    assert len(interaction_ids) == 1
    interaction = db.query(models.Interaction).filter(models.Interaction.id == created_drafts[0]).one()
    assert interaction.generated_response_status == "gmail_draft_created"
    assert interaction.interaction_type == "listing_alert_digest"
    draft = json.loads(interaction.generated_response_content)
    assert draft["watchlist_alert_ids"] == [alert.id for alert in alerts]
    assert "附近房源與成交參考整理" in draft["subject"]
    assert "這次值得寄給你" in draft["body"]
    assert "附近競爭房源" in draft["body"]
    assert "成交參考" in draft["body"]
    assert "符合條件：" in draft["body"]
    assert "寄出前我會再確認：" in draft["body"]
    notification = db.query(models.WatchlistNotification).one()
    assert "Digest: 2 matching item(s) for Tom Lin." in notification.body
    assert "Gmail draft created and waiting for Kevin review" in notification.body
    assert "Why notify:" in notification.body
    assert (
        f"Review in CRM: /watchlists?contact_id={tom_watch.contact_id}"
        f"&alert_id={notification.alert_id}&watchlist_id={tom_watch.id}"
    ) in notification.body
    assert notification.title == "Tom Lin: 2 watchlist update(s)"


def test_manual_watchlist_send_marks_sent_only_after_gmail_reports_sent(monkeypatch):
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.import_properties_csv(db, sample_csv(), dry_run=False)
    result = crud.run_watchlist_check(db, tom_watch.id)
    alert = result.alerts[0]
    draft = crud.create_draft_from_watchlist_alert(db, alert.id)
    assert draft.success is True
    interaction_id = draft.interaction_id
    assert interaction_id is not None

    interaction = db.query(models.Interaction).filter(models.Interaction.id == interaction_id).one()
    content = json.loads(interaction.generated_response_content)
    content["gmail"] = {"draft_id": "draft-123", "message_id": "msg-123"}
    interaction.generated_response_content = json.dumps(content)
    interaction.generated_response_status = "gmail_draft_created"
    db.add(interaction)
    db.commit()

    def fake_send_gmail_draft(db_arg, received_interaction_id, *, confirm_send, review_confirmation=None, **_kwargs):
        assert received_interaction_id == interaction_id
        assert confirm_send is True
        assert review_confirmation == "OK"
        return schemas.GmailDraftActionResponse(
            success=True,
            message="Gmail draft still exists.",
            interaction_id=interaction_id,
            status="gmail_draft_created",
            account_email="superkevinchou@gmail.com",
            to_email="tom@example.com",
            gmail_draft_id="draft-123",
            gmail_message_id="msg-123",
        )

    monkeypatch.setattr(gmail_service, "send_gmail_draft_for_interaction", fake_send_gmail_draft)

    send_action = crud.send_gmail_from_watchlist_alert(
        db,
        alert.id,
        confirm_send=True,
        review_confirmation="OK",
    )

    assert send_action.status == "gmail_draft_created"
    unchanged_alert = db.query(models.WatchlistAlert).filter(models.WatchlistAlert.id == alert.id).one()
    assert unchanged_alert.status == "draft_created"


def test_manual_digest_send_marks_all_alerts_sent_for_shared_gmail_draft(monkeypatch):
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.import_properties_csv(db, sample_csv(), dry_run=False)
    result = crud.run_watchlist_check(db, tom_watch.id)
    assert result.created_count == 2

    digest = crud.create_digest_draft_from_watchlist_alerts(db, tom_watch.id)
    assert digest.success is True
    interaction_id = digest.interaction_id
    assert interaction_id is not None

    interaction = db.query(models.Interaction).filter(models.Interaction.id == interaction_id).one()
    content = json.loads(interaction.generated_response_content)
    content["gmail"] = {"draft_id": "digest-draft-123", "message_id": "digest-msg-123"}
    interaction.generated_response_content = json.dumps(content)
    interaction.generated_response_status = "gmail_draft_created"
    db.add(interaction)
    db.commit()

    def fake_send_gmail_draft(db_arg, received_interaction_id, *, confirm_send, review_confirmation=None, **_kwargs):
        assert received_interaction_id == interaction_id
        assert confirm_send is True
        assert review_confirmation == "沒有問題"
        interaction_row = db_arg.query(models.Interaction).filter(models.Interaction.id == received_interaction_id).one()
        draft = json.loads(interaction_row.generated_response_content)
        draft.setdefault("gmail", {})["sent_message_id"] = "sent-digest-123"
        interaction_row.generated_response_content = json.dumps(draft)
        interaction_row.generated_response_status = "sent"
        db_arg.add(interaction_row)
        db_arg.commit()
        return schemas.GmailDraftActionResponse(
            success=True,
            message="Email sent via Gmail.",
            interaction_id=interaction_id,
            status="sent",
            account_email="superkevinchou@gmail.com",
            to_email="tom@example.com",
            gmail_draft_id="digest-draft-123",
            gmail_message_id="sent-digest-123",
        )

    monkeypatch.setattr(gmail_service, "send_gmail_draft_for_interaction", fake_send_gmail_draft)

    send_action = crud.send_gmail_from_watchlist_alert(
        db,
        digest.alert_ids[0],
        confirm_send=True,
        review_confirmation="沒有問題",
    )

    assert send_action.status == "sent"
    alerts = db.query(models.WatchlistAlert).order_by(models.WatchlistAlert.id.asc()).all()
    assert {alert.status for alert in alerts} == {"sent"}
    assert {alert.interaction_id for alert in alerts} == {interaction_id}
    assert all(alert.reviewed_at is not None for alert in alerts)


def test_watchlist_safety_status_requires_server_flag_and_gmail_connection(monkeypatch):
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_send_approved", auto_send_confirmation="AUTO SEND"),
    )
    gmail_status = schemas.GmailOAuthStatusResponse(
        connection_key="test",
        gmail_user_id="me",
        status="connected",
        account_email="superkevinchou@gmail.com",
        granted_scopes=[],
        oauth_configured=True,
        has_refresh_token=True,
        reconnect_required=False,
    )

    monkeypatch.delenv("WATCHLIST_AUTO_SEND_ENABLED", raising=False)
    draft_only = crud.get_watchlist_safety_status(db, gmail_status=gmail_status)
    assert draft_only.auto_send_armed_count == 1
    assert len(draft_only.auto_send_armed_watchlists) == 1
    assert draft_only.auto_send_armed_watchlists[0].contact_name == "Tom Lin"
    assert draft_only.auto_send_armed_watchlists[0].can_auto_send is False
    assert draft_only.auto_send_armed_watchlists[0].action_required == "Server auto-send is off; matches stay Gmail draft-only."
    assert draft_only.gmail_connected is True
    assert draft_only.auto_send_server_enabled is False
    assert draft_only.can_auto_send is False
    assert draft_only.draft_only is True

    monkeypatch.setenv("WATCHLIST_AUTO_SEND_ENABLED", "true")
    can_send = crud.get_watchlist_safety_status(db, gmail_status=gmail_status)
    assert can_send.auto_send_server_enabled is True
    assert can_send.can_auto_send is True
    assert can_send.draft_only is False
    assert can_send.auto_send_armed_watchlists[0].can_auto_send is True
    assert can_send.auto_send_armed_watchlists[0].action_required is None


def test_watchlist_safety_status_names_armed_watchlist_email_blocker(monkeypatch):
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    tom = db.query(models.Contact).filter(models.Contact.id == tom_watch.contact_id).one()
    tom.email = None
    db.add(tom)
    db.commit()
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_send_approved", auto_send_confirmation="AUTO SEND"),
    )
    gmail_status = schemas.GmailOAuthStatusResponse(
        connection_key="test",
        gmail_user_id="me",
        status="connected",
        account_email="superkevinchou@gmail.com",
        granted_scopes=[],
        oauth_configured=True,
        has_refresh_token=True,
        reconnect_required=False,
    )
    monkeypatch.setenv("WATCHLIST_AUTO_SEND_ENABLED", "true")

    status = crud.get_watchlist_safety_status(db, gmail_status=gmail_status)

    assert status.auto_send_armed_count == 1
    assert status.can_auto_send is True
    armed = status.auto_send_armed_watchlists[0]
    assert armed.contact_name == "Tom Lin"
    assert armed.contact_email_present is False
    assert armed.can_auto_send is False
    assert armed.action_required == "Add the client's email before Auto Send can be used."


def test_auto_send_arm_requires_explicit_confirmation():
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)

    with pytest.raises(ValueError, match="auto_send_confirmation_required"):
        crud.update_watchlist(
            db,
            tom_watch.id,
            schemas.ClientWatchlistUpdate(review_mode="auto_send_approved"),
        )

    unchanged = db.query(models.ClientWatchlist).filter(models.ClientWatchlist.id == tom_watch.id).one()
    assert unchanged.review_mode == "manual_review"

    updated = crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_send_approved", auto_send_confirmation="AUTO SEND"),
    )
    assert updated.review_mode == "auto_send_approved"


def test_contact_level_auto_send_arm_and_disarm_updates_all_contact_watchlists():
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)
    second_tom_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=tom_watch.contact_id,
            name="Tom Lin - Rental market backup",
            watch_type="landlord_rental_market",
            criteria={"areas": ["Thornhill"], "types": ["townhouse"]},
            notification_channel="codex_app",
            review_mode="auto_gmail_draft",
        ),
    )

    with pytest.raises(ValueError, match="auto_send_confirmation_required"):
        crud.update_contact_watchlist_review_mode(
            db,
            tom_watch.contact_id,
            schemas.ContactWatchlistReviewModeUpdate(review_mode="auto_send_approved"),
        )

    armed = crud.update_contact_watchlist_review_mode(
        db,
        tom_watch.contact_id,
        schemas.ContactWatchlistReviewModeUpdate(
            review_mode="auto_send_approved",
            auto_send_confirmation="AUTO SEND",
        ),
    )

    assert {item.id for item in armed} == {tom_watch.id, second_tom_watch.id}
    assert {item.review_mode for item in armed} == {"auto_send_approved"}
    amy_row = crud.get_watchlist(db, amy_watch.id)
    assert amy_row.review_mode == "manual_review"

    disarmed = crud.update_contact_watchlist_review_mode(
        db,
        tom_watch.contact_id,
        schemas.ContactWatchlistReviewModeUpdate(review_mode="auto_gmail_draft"),
    )

    assert {item.id for item in disarmed} == {tom_watch.id, second_tom_watch.id}
    assert {item.review_mode for item in disarmed} == {"auto_gmail_draft"}


def test_auto_send_can_be_disarmed_without_confirmation():
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)

    armed = crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_send_approved", auto_send_confirmation="AUTO SEND"),
    )
    assert armed.review_mode == "auto_send_approved"

    disarmed = crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    assert disarmed.review_mode == "auto_gmail_draft"


def test_watchlist_delivery_gates_show_draft_ready_and_missing_email(monkeypatch):
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    crud.update_watchlist(
        db,
        amy_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    tom = db.query(models.Contact).filter(models.Contact.id == tom_watch.contact_id).one()
    tom.email = None
    db.add(tom)
    db.commit()
    db.expire_all()
    gmail_status = schemas.GmailOAuthStatusResponse(
        connection_key="test",
        gmail_user_id="me",
        status="connected",
        account_email="superkevinchou@gmail.com",
        granted_scopes=[],
        oauth_configured=True,
        has_refresh_token=True,
        reconnect_required=False,
    )
    monkeypatch.delenv("WATCHLIST_AUTO_SEND_ENABLED", raising=False)

    gates = crud.get_watchlist_delivery_gates(db, gmail_status=gmail_status)

    assert gates.overall_status == "blocked"
    by_watchlist = {item.watchlist_id: item for item in gates.items}
    assert by_watchlist[tom_watch.id].delivery_state == "email_required"
    assert by_watchlist[tom_watch.id].can_create_gmail_draft is False
    assert by_watchlist[tom_watch.id].action_required
    assert by_watchlist[amy_watch.id].delivery_state == "gmail_draft_ready"
    assert by_watchlist[amy_watch.id].can_create_gmail_draft is True
    assert by_watchlist[amy_watch.id].can_auto_send is False


def test_watchlist_delivery_gates_keep_auto_send_draft_only_until_server_flag(monkeypatch):
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_send_approved", auto_send_confirmation="AUTO SEND"),
    )
    gmail_status = schemas.GmailOAuthStatusResponse(
        connection_key="test",
        gmail_user_id="me",
        status="connected",
        account_email="superkevinchou@gmail.com",
        granted_scopes=[],
        oauth_configured=True,
        has_refresh_token=True,
        reconnect_required=False,
    )

    monkeypatch.delenv("WATCHLIST_AUTO_SEND_ENABLED", raising=False)
    draft_only = crud.get_watchlist_delivery_gates(db, gmail_status=gmail_status)
    tom_gate = next(item for item in draft_only.items if item.watchlist_id == tom_watch.id)
    assert tom_gate.delivery_state == "auto_send_armed_draft_only"
    assert tom_gate.can_create_gmail_draft is True
    assert tom_gate.can_auto_send is False

    monkeypatch.setenv("WATCHLIST_AUTO_SEND_ENABLED", "true")
    can_send = crud.get_watchlist_delivery_gates(db, gmail_status=gmail_status)
    tom_gate = next(item for item in can_send.items if item.watchlist_id == tom_watch.id)
    assert tom_gate.delivery_state == "auto_send_ready"
    assert tom_gate.can_auto_send is True


def test_watchlist_readiness_report_explains_missing_source_rows(monkeypatch):
    db = make_session()
    seed_watchlists(db)
    gmail_status = schemas.GmailOAuthStatusResponse(
        connection_key="test",
        gmail_user_id="me",
        status="connected",
        account_email="superkevinchou@gmail.com",
        granted_scopes=[],
        oauth_configured=True,
        has_refresh_token=True,
        reconnect_required=False,
    )
    monkeypatch.delenv("WATCHLIST_AUTO_SEND_ENABLED", raising=False)

    report = crud.get_watchlist_readiness_report(db, gmail_status=gmail_status)

    assert report.overall_status == "blocked"
    assert report.active_count == 2
    assert report.ready_count == 0
    assert report.blocked_count == 2
    assert report.property_rows == 0
    assert report.safety.draft_only is True
    assert len(report.items) == 2
    assert all(item.matching_source_rows == 0 for item in report.items)
    assert any("REALM/TRREB CSV" in action for action in report.next_actions)
    assert any("Tom Lin" in blocker for blocker in report.blockers)


def test_watchlist_data_intake_checklist_names_source_and_delivery_blockers():
    db = make_session()
    seed_watchlists(db)

    checklist = crud.get_watchlist_data_intake_checklist(db)

    assert checklist.overall_status == "blocked"
    assert checklist.active_count == 2
    assert checklist.ready_count == 0
    assert checklist.blocked_count == 2
    assert checklist.source_rows == 0
    assert "REALM/TRREB CSV" in (checklist.recommended_next_action or "")

    by_contact = {item.contact_name: item for item in checklist.items}
    tom = by_contact["Tom Lin"]
    amy = by_contact["Amy Yuen"]
    assert tom.source_ready is False
    assert tom.delivery_ready is True
    assert tom.missing_required_statuses == ["listed_for_sale", "sold"]
    assert "listed for sale" in tom.primary_next_step
    assert "sold" in tom.primary_next_step
    assert amy.missing_required_statuses == ["listed_for_sale"]


def test_watchlist_source_tasks_convert_readiness_into_export_steps():
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)

    tasks = crud.get_watchlist_source_tasks(db)

    assert tasks.overall_status == "blocked"
    assert tasks.task_count == 2
    assert tasks.source_rows == 0
    by_watchlist = {task.watchlist_id: task for task in tasks.tasks}
    assert by_watchlist[tom_watch.id].priority == "source_required"
    assert by_watchlist[tom_watch.id].required_statuses == ["listed_for_sale", "sold"]
    assert by_watchlist[tom_watch.id].missing_required_statuses == ["listed_for_sale", "sold"]
    assert "107 Brownstone Circle" in by_watchlist[tom_watch.id].gmail_query
    assert by_watchlist[tom_watch.id].saved_search_name == "SKC Tom Lin - Seller Active + Sold Comps"
    assert any("Subject/reference address: 107 Brownstone Circle" in item for item in by_watchlist[tom_watch.id].realm_criteria)
    assert any("Create or update a REALM/TRREB saved search" in step for step in by_watchlist[tom_watch.id].realm_steps)
    assert by_watchlist[tom_watch.id].export_statuses == ["listed_for_sale", "sold"]
    assert any("Export rows for" in step for step in by_watchlist[tom_watch.id].steps)
    assert by_watchlist[amy_watch.id].required_statuses == ["listed_for_sale"]
    assert by_watchlist[amy_watch.id].client_email_needed is False


def test_watchlist_launch_action_pack_summarizes_source_delivery_and_connector_blockers(monkeypatch):
    monkeypatch.delenv("WATCHLIST_RESO_CONNECTOR_ENABLED", raising=False)
    monkeypatch.delenv("WATCHLIST_RESO_CONNECTOR_URL", raising=False)
    monkeypatch.delenv("WATCHLIST_RESO_CONNECTOR_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("RESO_ACCESS_TOKEN", raising=False)
    db = make_session()
    tom_watch, amy_watch = seed_watchlists(db)
    tom_contact = db.query(models.Contact).filter(models.Contact.id == tom_watch.contact_id).one()
    tom_contact.email = None
    db.add(tom_contact)
    db.commit()
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_gmail_draft"),
    )
    db.expire_all()

    pack = crud.get_watchlist_launch_action_pack(
        db,
        gmail_status=schemas.GmailOAuthStatusResponse(
            connection_key="superkevin_primary",
            gmail_user_id="me",
            status="connected",
            account_email="superkevinchou@gmail.com",
            granted_scopes=["https://www.googleapis.com/auth/gmail.compose"],
            oauth_configured=True,
            has_refresh_token=True,
        ),
    )

    assert pack.overall_status == "blocked"
    assert pack.active_count == 2
    assert pack.ready_count == 0
    assert pack.source_rows == 0
    assert pack.missing_email_count == 1
    assert pack.source_task_count == 2
    assert pack.gmail_feed_enabled is False
    assert pack.gmail_connected is True
    assert pack.auto_send_server_enabled is False
    assert pack.reso_connector.status == "disabled"
    assert pack.reso_connector.ready is False
    assert "saved-search emails or CSV exports first" in pack.recommended_method
    assert "Gmail saved-search feed import is disabled" in pack.copy_text
    assert "RESO connector: disabled" in pack.copy_text
    assert "Auto-send server switch is off" in pack.copy_text
    assert "Preflight checks:" in pack.copy_text
    assert "SKC Tom Lin - Seller Active + Sold Comps" in pack.copy_text
    assert "SKC Amy Yuen - Buyer Active Listings" in pack.copy_text
    preflight = {item.key: item for item in pack.preflight_checks}
    assert preflight["authorized_source_data"].status == "blocked"
    assert "0 source row" in preflight["authorized_source_data"].detail
    assert preflight["watchlist_readiness"].status == "blocked"
    assert preflight["client_delivery_emails"].status == "blocked"
    assert "1 active watchlist" in preflight["client_delivery_emails"].detail
    assert preflight["gmail_draft_connection"].status == "passed"
    assert preflight["gmail_saved_search_feed"].status == "warning"
    assert preflight["reso_odata_connector"].status == "info"
    assert preflight["auto_send_safety"].status == "info"
    by_watchlist = {item.watchlist_id: item for item in pack.items}
    assert by_watchlist[tom_watch.id].priority == "source_required"
    assert by_watchlist[tom_watch.id].missing_required_statuses == ["listed_for_sale", "sold"]
    assert by_watchlist[tom_watch.id].client_email_needed is True
    assert "Client email: missing" in by_watchlist[tom_watch.id].copy_text
    assert by_watchlist[amy_watch.id].gmail_query


def test_watchlist_launch_action_pack_reports_configured_reso_connector(monkeypatch):
    monkeypatch.setenv("WATCHLIST_RESO_CONNECTOR_ENABLED", "true")
    monkeypatch.setenv("WATCHLIST_RESO_CONNECTOR_URL", "https://reso.example.test/odata/Property?$top=25&token=secret")
    monkeypatch.setenv("WATCHLIST_RESO_CONNECTOR_BEARER_TOKEN", "secret-token")
    db = make_session()
    seed_watchlists(db)

    pack = crud.get_watchlist_launch_action_pack(db)
    preflight = {item.key: item for item in pack.preflight_checks}

    assert pack.reso_connector.ready is True
    assert pack.reso_connector.status == "configured"
    assert pack.reso_connector.auth_configured is True
    assert pack.reso_connector.endpoint == "https://reso.example.test/odata/Property?[redacted]"
    assert preflight["reso_odata_connector"].status == "passed"
    assert "RESO connector configured" in pack.summary


def test_watchlist_source_tasks_show_ready_after_matching_import():
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.import_properties_csv(db, sample_csv(), dry_run=False)

    tasks = crud.get_watchlist_source_tasks(db)

    tom_task = next(task for task in tasks.tasks if task.watchlist_id == tom_watch.id)
    assert tom_task.source_ready is True
    assert tom_task.priority == "ready"
    assert tom_task.missing_required_statuses == []
    assert any("Source rows are present" in step for step in tom_task.steps)


def test_watchlist_readiness_ignores_unrelated_source_rows(monkeypatch):
    db = make_session()
    seed_watchlists(db)
    monkeypatch.delenv("WATCHLIST_AUTO_SEND_ENABLED", raising=False)

    crud.import_properties_csv(
        db,
        "mls_number,street,city,community,status,property_type,list price,sold price,rent,beds,baths,parking,url,remarks\n"
        "X900001,1 Lake Shore Blvd,Toronto,Waterfront,For Sale,Condo,650000,,,1,1,0,https://example.com/X900001,Unrelated condo row\n",
        dry_run=False,
    )

    source_setups = crud.get_watchlist_source_setups(db)
    assert {setup.contact_name: setup.current_matching_rows for setup in source_setups} == {
        "Tom Lin": 0,
        "Amy Yuen": 0,
    }

    report = crud.get_watchlist_readiness_report(db)
    assert report.property_rows == 1
    assert report.ready_count == 0
    assert report.blocked_count == 2
    assert all(item.matching_source_rows == 0 for item in report.items)


def test_seller_readiness_requires_listing_and_sold_status_matches(monkeypatch):
    db = make_session()
    seed_watchlists(db)
    monkeypatch.delenv("WATCHLIST_AUTO_SEND_ENABLED", raising=False)

    crud.import_properties_csv(
        db,
        "mls_number,street,city,community,status,property_type,list price,sold price,rent,beds,baths,parking,url,remarks\n"
        "N100002,111 Brownstone Circle,Thornhill,Thornhill,For Sale,Townhouse,1199000,,,3,3,1,https://example.com/N100002,Freehold townhouse competing active listing\n",
        dry_run=False,
    )

    source_setups = {setup.contact_name: setup for setup in crud.get_watchlist_source_setups(db)}
    tom_setup = source_setups["Tom Lin"]
    assert tom_setup.current_matching_rows == 1
    assert tom_setup.matching_status_counts == {"listed_for_sale": 1, "sold": 0}
    assert tom_setup.missing_required_statuses == ["sold"]
    assert tom_setup.readiness == "missing_statuses"

    report = crud.get_watchlist_readiness_report(db)
    tom_item = next(item for item in report.items if item.contact_name == "Tom Lin")
    assert report.overall_status == "blocked"
    assert tom_item.ready is False
    assert tom_item.severity == "blocked"
    assert tom_item.matching_source_rows == 1
    assert tom_item.matching_status_counts == {"listed_for_sale": 1, "sold": 0}
    assert tom_item.missing_required_statuses == ["sold"]
    assert any("sold" in step for step in tom_item.next_steps)


def test_watchlist_readiness_counts_only_criteria_matches():
    db = make_session()
    seed_watchlists(db)
    crud.import_properties_csv(db, sample_csv(), dry_run=False)

    source_setups = crud.get_watchlist_source_setups(db)
    assert {setup.contact_name: setup.current_matching_rows for setup in source_setups} == {
        "Tom Lin": 2,
        "Amy Yuen": 1,
    }

    report = crud.get_watchlist_readiness_report(db)
    assert report.overall_status == "ready"
    assert report.ready_count == 2
    assert report.blocked_count == 0
    assert {item.contact_name: item.matching_source_rows for item in report.items} == {
        "Tom Lin": 2,
        "Amy Yuen": 1,
    }
    assert {item.contact_name: item.missing_required_statuses for item in report.items} == {
        "Tom Lin": [],
        "Amy Yuen": [],
    }

    checklist = crud.get_watchlist_data_intake_checklist(db)
    assert checklist.overall_status == "ready"
    assert checklist.ready_count == 2
    assert checklist.blocked_count == 0
    assert all(item.source_ready for item in checklist.items)
    assert all(item.delivery_ready for item in checklist.items)


def test_watchlist_readiness_warns_when_auto_gmail_draft_contact_has_no_email():
    db = make_session()
    contact = models.Contact(name="No Email Buyer", preferred_language="en", client_type="buyer")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=contact.id,
            name="No Email Buyer - Buyer listing match",
            watch_type="buyer_listing_match",
            criteria={"areas": ["Milton"], "types": ["detached"], "max_price": 900000},
            review_mode="auto_gmail_draft",
            notification_channel="codex_app",
        ),
    )
    crud.import_properties_csv(
        db,
        "mls_number,street,city,community,status,property_type,list price,sold price,rent,beds,baths,parking,url,remarks\n"
        "W200001,20 Main Street,Milton,Milton,For Sale,Detached,880000,,,3,3,1,https://example.com/W200001,Detached with garage\n",
        dry_run=False,
    )

    readiness = crud.get_watchlists(db, contact_id=contact.id)[0].readiness
    assert readiness["severity"] == "warning"
    assert readiness["ready"] is False
    assert readiness["matching_source_rows"] == 1
    assert readiness["contact_email_present"] is False
    assert readiness["delivery_ready"] is False
    assert readiness["delivery_issues"] == ["Contact email is missing; Gmail drafts cannot be addressed to the client."]
    assert any("Contact email is missing" in issue for issue in readiness["issues"])
    assert any("client-email-tasks.csv" in step for step in readiness["next_steps"])

    report = crud.get_watchlist_readiness_report(db)
    assert report.overall_status == "warning"
    item = report.items[0]
    assert item.severity == "warning"
    assert item.matching_source_rows == 1
    assert item.contact_email_present is False
    assert item.delivery_ready is False
    assert item.delivery_issues == ["Contact email is missing; Gmail drafts cannot be addressed to the client."]
    assert any("client-email-tasks.csv" in step for step in item.next_steps)


def test_auto_gmail_draft_skips_gmail_service_when_contact_email_missing(monkeypatch):
    db = make_session()
    contact = models.Contact(name="No Email Buyer", preferred_language="en", client_type="buyer")
    db.add(contact)
    db.commit()
    db.refresh(contact)

    watchlist = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=contact.id,
            name="No Email Buyer - Buyer listing match",
            watch_type="buyer_listing_match",
            criteria={"areas": ["Milton"], "types": ["detached"], "max_price": 900000},
            review_mode="auto_gmail_draft",
            notification_channel="codex_app",
        ),
    )
    crud.import_properties_csv(
        db,
        "mls_number,street,city,community,status,property_type,list price,sold price,rent,beds,baths,parking,url,remarks\n"
        "W200001,20 Main Street,Milton,Milton,For Sale,Detached,880000,,,3,3,1,https://example.com/W200001,Detached with garage\n",
        dry_run=False,
    )

    def fail_create_gmail_draft(*_args, **_kwargs):
        raise AssertionError("Gmail draft should not be attempted when contact email is missing")

    monkeypatch.setattr(gmail_service, "create_gmail_draft_for_interaction", fail_create_gmail_draft)

    result = crud.run_watchlist_check(db, watchlist.id)

    assert result.created_count == 1
    alert = db.query(models.WatchlistAlert).one()
    assert alert.status == "draft_created"
    assert alert.interaction_id is not None
    interaction = db.query(models.Interaction).filter(models.Interaction.id == alert.interaction_id).one()
    assert interaction.generated_response_status == "pending_review"
    notification = db.query(models.WatchlistNotification).one()
    assert "client email is missing" in notification.body


def test_rental_watchlists_match_tenant_and_landlord_market_rows():
    db = make_session()
    tenant = models.Contact(name="Tenant Client", email="tenant@example.com", preferred_language="en")
    landlord = models.Contact(name="Landlord Client", email="landlord@example.com", preferred_language="zh-tw")
    db.add_all([tenant, landlord])
    db.commit()
    db.refresh(tenant)
    db.refresh(landlord)

    tenant_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=tenant.id,
            name="Tenant Client - Rental match",
            watch_type="tenant_rental_match",
            criteria={
                "areas": ["North York"],
                "types": ["condo"],
                "max_price": 2800,
                "bedrooms_min": 2,
                "parking_min": 1,
            },
            notification_channel="codex_app",
            review_mode="manual_review",
        ),
    )
    landlord_watch = crud.create_watchlist(
        db,
        schemas.ClientWatchlistCreate(
            contact_id=landlord.id,
            name="Landlord Client - Rental market",
            watch_type="landlord_rental_market",
            criteria={
                "areas": ["Thornhill"],
                "types": ["townhouse"],
            },
            notification_channel="codex_app",
            review_mode="manual_review",
        ),
    )

    import_result = crud.import_properties_csv(db, rental_csv(), dry_run=False)
    assert import_result.created == 4

    source_setups = {setup.contact_name: setup for setup in crud.get_watchlist_source_setups(db)}
    tenant_setup = source_setups["Tenant Client"]
    landlord_setup = source_setups["Landlord Client"]
    assert tenant_setup.current_matching_rows == 1
    assert tenant_setup.matching_status_counts == {"listed_for_rent": 1}
    assert tenant_setup.missing_required_statuses == []
    assert landlord_setup.current_matching_rows == 2
    assert landlord_setup.matching_status_counts == {"listed_for_rent": 1, "rented": 1}
    assert landlord_setup.missing_required_statuses == []

    tenant_result = crud.run_watchlist_check(db, tenant_watch.id)
    landlord_result = crud.run_watchlist_check(db, landlord_watch.id)
    assert tenant_result.created_count == 1
    assert landlord_result.created_count == 2

    assert [alert.alert_type for alert in tenant_result.alerts] == ["new_rental_listing"]
    assert [alert.alert_type for alert in landlord_result.alerts] == [
        "leased_comp",
        "new_rental_listing",
    ]


def test_auto_send_armed_creates_draft_but_does_not_send_without_server_flag(monkeypatch):
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_send_approved", auto_send_confirmation="AUTO SEND"),
    )
    crud.import_properties_csv(db, sample_csv(), dry_run=False)

    created_drafts: list[int] = []
    send_calls: list[int] = []

    def fake_create_gmail_draft(db_arg, interaction_id, **_kwargs):
        interaction = db_arg.query(models.Interaction).filter(models.Interaction.id == interaction_id).one()
        draft = json.loads(interaction.generated_response_content)
        draft["gmail"] = {"draft_id": f"draft-{interaction_id}", "message_id": f"msg-{interaction_id}"}
        interaction.generated_response_content = json.dumps(draft)
        interaction.generated_response_status = "gmail_draft_created"
        db_arg.add(interaction)
        db_arg.commit()
        created_drafts.append(interaction_id)
        return schemas.GmailDraftActionResponse(
            success=True,
            message="Gmail draft created.",
            interaction_id=interaction_id,
            status="gmail_draft_created",
            account_email="superkevinchou@gmail.com",
            to_email="tom@example.com",
            gmail_draft_id=f"draft-{interaction_id}",
            gmail_message_id=f"msg-{interaction_id}",
        )

    def fake_send_gmail_draft(_db_arg, interaction_id, **_kwargs):
        send_calls.append(interaction_id)
        raise AssertionError("auto_send_approved must not send when WATCHLIST_AUTO_SEND_ENABLED is off")

    monkeypatch.delenv("WATCHLIST_AUTO_SEND_ENABLED", raising=False)
    monkeypatch.setattr(gmail_service, "create_gmail_draft_for_interaction", fake_create_gmail_draft)
    monkeypatch.setattr(gmail_service, "send_gmail_draft_for_interaction", fake_send_gmail_draft)

    result = crud.run_watchlist_check(db, tom_watch.id)

    assert result.created_count == 2
    assert len(created_drafts) == 1
    assert send_calls == []
    alerts = db.query(models.WatchlistAlert).order_by(models.WatchlistAlert.id.asc()).all()
    assert {alert.status for alert in alerts} == {"draft_created"}
    interaction = db.query(models.Interaction).filter(models.Interaction.id == created_drafts[0]).one()
    assert interaction.generated_response_status == "gmail_draft_created"


def test_auto_send_armed_sends_only_when_server_flag_is_enabled(monkeypatch):
    db = make_session()
    tom_watch, _amy_watch = seed_watchlists(db)
    crud.update_watchlist(
        db,
        tom_watch.id,
        schemas.ClientWatchlistUpdate(review_mode="auto_send_approved", auto_send_confirmation="AUTO SEND"),
    )
    crud.import_properties_csv(db, sample_csv(), dry_run=False)

    created_drafts: list[int] = []
    sent_interactions: list[int] = []

    def fake_create_gmail_draft(db_arg, interaction_id, **_kwargs):
        interaction = db_arg.query(models.Interaction).filter(models.Interaction.id == interaction_id).one()
        draft = json.loads(interaction.generated_response_content)
        draft["gmail"] = {"draft_id": f"draft-{interaction_id}", "message_id": f"msg-{interaction_id}"}
        interaction.generated_response_content = json.dumps(draft)
        interaction.generated_response_status = "gmail_draft_created"
        db_arg.add(interaction)
        db_arg.commit()
        created_drafts.append(interaction_id)
        return schemas.GmailDraftActionResponse(
            success=True,
            message="Gmail draft created.",
            interaction_id=interaction_id,
            status="gmail_draft_created",
            account_email="superkevinchou@gmail.com",
            to_email="tom@example.com",
            gmail_draft_id=f"draft-{interaction_id}",
            gmail_message_id=f"msg-{interaction_id}",
        )

    def fake_send_gmail_draft(db_arg, interaction_id, *, confirm_send, **_kwargs):
        assert confirm_send is True
        interaction = db_arg.query(models.Interaction).filter(models.Interaction.id == interaction_id).one()
        draft = json.loads(interaction.generated_response_content)
        gmail = draft.setdefault("gmail", {})
        assert gmail.get("draft_id") == f"draft-{interaction_id}"
        gmail["sent_message_id"] = f"sent-{interaction_id}"
        interaction.generated_response_content = json.dumps(draft)
        interaction.generated_response_status = "sent"
        db_arg.add(interaction)
        db_arg.commit()
        sent_interactions.append(interaction_id)
        return schemas.GmailDraftActionResponse(
            success=True,
            message="Email sent via Gmail.",
            interaction_id=interaction_id,
            status="sent",
            account_email="superkevinchou@gmail.com",
            to_email="tom@example.com",
            gmail_draft_id=f"draft-{interaction_id}",
            gmail_message_id=f"sent-{interaction_id}",
        )

    monkeypatch.setenv("WATCHLIST_AUTO_SEND_ENABLED", "true")
    monkeypatch.setattr(gmail_service, "create_gmail_draft_for_interaction", fake_create_gmail_draft)
    monkeypatch.setattr(gmail_service, "send_gmail_draft_for_interaction", fake_send_gmail_draft)

    result = crud.run_watchlist_check(db, tom_watch.id)

    assert result.created_count == 2
    assert len(created_drafts) == 1
    assert sent_interactions == created_drafts
    alerts = db.query(models.WatchlistAlert).order_by(models.WatchlistAlert.id.asc()).all()
    assert {alert.status for alert in alerts} == {"sent"}
    assert all(alert.reviewed_at is not None for alert in alerts)
    assert {alert.interaction_id for alert in alerts} == set(sent_interactions)
    interaction = db.query(models.Interaction).filter(models.Interaction.id == sent_interactions[0]).one()
    assert interaction.generated_response_status == "sent"


def test_manual_gmail_send_confirmation_requires_review_phrase():
    assert gmail_service._manual_send_confirmation_valid("沒有問題")
    assert gmail_service._manual_send_confirmation_valid("OK")
    assert gmail_service._manual_send_confirmation_valid(" ok ")
    assert gmail_service._manual_send_confirmation_valid("没问题")
    assert not gmail_service._manual_send_confirmation_valid(None)
    assert not gmail_service._manual_send_confirmation_valid("")
    assert not gmail_service._manual_send_confirmation_valid("send it")


def test_manual_gmail_send_rejects_boolean_without_review_phrase():
    db = make_session()
    with pytest.raises(ValueError, match="gmail_send_review_confirmation_required"):
        gmail_service.send_gmail_draft_for_interaction(db, 999, confirm_send=True)


def test_gmail_draft_rejects_connected_wrong_expected_account(monkeypatch):
    db = make_session()
    contact = models.Contact(name="Wrong Account Client", email="client@example.com")
    db.add(contact)
    db.flush()
    interaction = models.Interaction(
        contact_id=contact.id,
        channel="email",
        direction="outbound",
        interaction_type="listing_alert_digest",
        generated_response_type="email_draft",
        generated_response_status="pending_review",
        generated_response_content=json.dumps({"subject": "Market update", "body": "Draft body"}),
    )
    connection = models.GmailOAuthConnection(
        connection_key=gmail_service.GMAIL_CONNECTION_KEY,
        gmail_user_id=gmail_service.GMAIL_USER_ID,
        status="connected",
        account_email="wrong-account@example.com",
        granted_scopes=json.dumps([gmail_service.GMAIL_COMPOSE_SCOPE]),
        encrypted_refresh_token="not-used-before-account-check",
    )
    db.add_all([interaction, connection])
    db.commit()

    monkeypatch.setenv("GMAIL_EXPECTED_ACCOUNT_EMAIL", "superkevinchou@gmail.com")

    with pytest.raises(ValueError, match="gmail_oauth_wrong_account"):
        gmail_service.create_gmail_draft_for_interaction(db, interaction.id)


def test_gmail_saved_search_feed_enable_requires_explicit_confirmation():
    db = make_session()

    config = crud.get_property_feed_config(db)
    assert config.gmail_feed_enabled is False

    with pytest.raises(ValueError, match="gmail_feed_confirmation_required"):
        crud.update_property_feed_config(
            db,
            schemas.PropertyFeedConfigUpdate(gmail_feed_enabled=True),
        )

    unchanged = crud.get_property_feed_config(db)
    assert unchanged.gmail_feed_enabled is False

    enabled = crud.update_property_feed_config(
        db,
        schemas.PropertyFeedConfigUpdate(
            gmail_feed_enabled=True,
            gmail_feed_confirmation="READ GMAIL",
        ),
    )
    assert enabled.gmail_feed_enabled is True

    disabled = crud.update_property_feed_config(
        db,
        schemas.PropertyFeedConfigUpdate(gmail_feed_enabled=False),
    )
    assert disabled.gmail_feed_enabled is False


def test_gmail_saved_search_manual_read_requires_enabled_config_confirmation_or_env(monkeypatch):
    monkeypatch.delenv("WATCHLIST_GMAIL_FEED_IMPORT_ENABLED", raising=False)
    db = make_session()

    assert crud.gmail_feed_read_authorized(db) is False
    assert crud.gmail_feed_read_authorized(db, "READ GMAIL") is True

    enabled = crud.update_property_feed_config(
        db,
        schemas.PropertyFeedConfigUpdate(
            gmail_feed_enabled=True,
            gmail_feed_confirmation="READ GMAIL",
        ),
    )
    assert enabled.gmail_feed_enabled is True
    assert crud.gmail_feed_read_authorized(db) is True

    crud.update_property_feed_config(db, schemas.PropertyFeedConfigUpdate(gmail_feed_enabled=False))
    assert crud.gmail_feed_read_authorized(db) is False

    monkeypatch.setenv("WATCHLIST_GMAIL_FEED_IMPORT_ENABLED", "true")
    assert crud.gmail_feed_read_authorized(db) is True


def test_gmail_saved_search_feed_rejects_broad_queries_before_reading_gmail():
    db = make_session()

    with pytest.raises(ValueError, match="gmail_feed_query_requires_recency"):
        crud.update_property_feed_config(
            db,
            schemas.PropertyFeedConfigUpdate(gmail_query="REALM saved search"),
        )

    with pytest.raises(ValueError, match="gmail_feed_query_requires_listing_terms"):
        crud.update_property_feed_config(
            db,
            schemas.PropertyFeedConfigUpdate(gmail_query="newer_than:14d from:friend@example.com"),
        )

    with pytest.raises(ValueError, match="gmail_feed_query_requires_listing_terms"):
        gmail_service.fetch_property_feed_messages(
            db,
            query="newer_than:14d from:friend@example.com",
        )

    updated = crud.update_property_feed_config(
        db,
        schemas.PropertyFeedConfigUpdate(
            gmail_query='newer_than:14d (REALM OR TRREB OR MLS OR listing) ("Thornhill")',
        ),
    )
    assert updated.gmail_query == 'newer_than:14d (REALM OR TRREB OR MLS OR listing) ("Thornhill")'
