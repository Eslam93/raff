import uuid

import pytest
from sqlalchemy import select

from app.models import Book, Copy

pytestmark = pytest.mark.integration

SUMMARY_FIELDS = {
    "id",
    "title",
    "author",
    "isbn",
    "category",
    "published_year",
    "copies_total",
    "copies_available",
    "availability",
}
DETAIL_FIELDS = SUMMARY_FIELDS | {
    "description",
    "has_loan_history",
    "archived",
    "created_at",
    "updated_at",
    "copies",
    "holds_waiting",
    "my_hold",
}


def field_errors(response):
    """{field: error type} from a 422 body."""
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "validation_failed"
    return {e["location"][-1]: e["type"] for e in body["error"]["details"]["errors"]}


# Add


async def test_add_book_creates_it_with_its_first_copy(client):
    response = await client.post(
        "/api/books",
        json={
            "title": "  Dune ",
            "author": "Frank Herbert",
            "isbn": "978-0-441-17271-9",
            "category": "Science Fiction",
            "published_year": 1965,
            "description": "Desert planet.",
        },
    )

    assert response.status_code == 201
    book = response.json()
    assert set(book) == DETAIL_FIELDS
    assert book["title"] == "Dune"
    assert book["isbn"] == "9780441172719"
    assert book["copies_total"] == 1
    assert book["copies_available"] == 1
    assert book["availability"] == "available"
    assert book["has_loan_history"] is False
    assert book["archived"] is False
    [copy] = book["copies"]
    assert set(copy) == {"id", "code", "status", "due_at", "active_loan", "held_for"}
    assert copy["status"] == "available"
    assert copy["due_at"] is None
    assert copy["active_loan"] is None
    assert copy["code"].startswith("CP-")
    assert len(copy["code"]) >= len("CP-0001")


async def test_only_title_and_author_are_required(client):
    response = await client.post("/api/books", json={"title": "Dune", "author": "Frank Herbert"})

    assert response.status_code == 201
    book = response.json()
    assert (book["isbn"], book["category"], book["published_year"], book["description"]) == (
        None,
        None,
        None,
        None,
    )


async def test_add_book_with_several_copies_numbers_them_in_order(make_book):
    book = await make_book(copies=3)

    codes = [copy["code"] for copy in book["copies"]]
    numbers = [int(code.removeprefix("CP-")) for code in codes]
    assert book["copies_total"] == 3
    assert numbers == sorted(numbers)
    assert len(set(codes)) == 3


async def test_blank_optional_fields_are_stored_as_null(client):
    response = await client.post(
        "/api/books",
        json={"title": "Dune", "author": "Frank Herbert", "isbn": " ", "category": ""},
    )

    assert response.status_code == 201
    assert response.json()["isbn"] is None
    assert response.json()["category"] is None


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"title": "   "}, {"title": "string_too_short"}),
        ({"author": ""}, {"author": "string_too_short"}),
        ({"title": "x" * 301}, {"title": "string_too_long"}),
        ({"isbn": "978-0-441-17271-0"}, {"isbn": "isbn_checksum"}),
        ({"isbn": "0441172718"}, {"isbn": "isbn_checksum"}),
        ({"isbn": "12345"}, {"isbn": "isbn_format"}),
        ({"published_year": 1449}, {"published_year": "year_out_of_range"}),
        ({"published_year": 9999}, {"published_year": "year_out_of_range"}),
        ({"copies": 0}, {"copies": "greater_than_equal"}),
        ({"copies": 21}, {"copies": "less_than_equal"}),
    ],
)
async def test_invalid_book_fields_are_422_per_field(client, fields, expected):
    body = {"title": "Dune", "author": "Frank Herbert", **fields}

    response = await client.post("/api/books", json=body)

    assert field_errors(response) == expected


async def test_validation_error_names_body_fields_with_messages(client):
    response = await client.post("/api/books", json={"author": "", "isbn": "9780441172710"})

    errors = response.json()["error"]["details"]["errors"]
    assert {tuple(e["location"]) for e in errors} == {
        ("body", "title"),
        ("body", "author"),
        ("body", "isbn"),
    }
    assert all(set(e) == {"location", "message", "type"} for e in errors)
    isbn_error = next(e for e in errors if e["location"] == ["body", "isbn"])
    assert "check digit" in isbn_error["message"]


async def test_isbn_10_with_final_x_is_accepted(make_book):
    book = await make_book(isbn="0-8044-2957-x")

    assert book["isbn"] == "080442957X"


async def test_isbn_already_in_the_catalog_is_409(make_book, client):
    await make_book(isbn="9780441172719")

    response = await client.post(
        "/api/books", json={"title": "Dune (copy)", "author": "F. H.", "isbn": "978 0441172719"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "isbn_taken"


# Read


async def test_list_shows_title_author_and_availability(make_book, client):
    await make_book(title="Dune", copies=2)

    response = await client.get("/api/books")

    assert response.status_code == 200
    page = response.json()
    assert set(page) == {"items", "total", "limit", "offset"}
    assert (page["total"], page["limit"], page["offset"]) == (1, 20, 0)
    [item] = page["items"]
    assert set(item) == SUMMARY_FIELDS
    assert (item["title"], item["author"]) == ("Dune", "Frank Herbert")
    assert (item["copies_total"], item["copies_available"], item["availability"]) == (
        2,
        2,
        "available",
    )


async def test_book_detail_404_for_unknown_id(client):
    response = await client.get(f"/api/books/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_book_detail_rejects_a_malformed_id(client):
    response = await client.get("/api/books/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error"]["details"]["errors"][0]["location"] == ["path", "book_id"]


async def test_limit_above_100_is_422(client):
    response = await client.get("/api/books?limit=101")

    assert response.status_code == 422


# Edit


async def test_edit_changes_only_the_fields_sent(make_book, client):
    book = await make_book(isbn="9780441172719", category="Science Fiction", published_year=1965)

    response = await client.patch(
        f"/api/books/{book['id']}", json={"title": "Dune (40th anniversary)", "category": None}
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "Dune (40th anniversary)"
    assert updated["category"] is None
    assert updated["isbn"] == "9780441172719"
    assert updated["published_year"] == 1965


async def test_edit_validates_like_add(make_book, client):
    book = await make_book()

    response = await client.patch(
        f"/api/books/{book['id']}",
        json={"title": None, "author": " ", "isbn": "9780441172710", "published_year": 1200},
    )

    assert field_errors(response) == {
        "title": "missing",
        "author": "string_too_short",
        "isbn": "isbn_checksum",
        "published_year": "year_out_of_range",
    }


async def test_edit_to_an_isbn_another_book_has_is_409(make_book, client):
    await make_book(title="Dune", isbn="9780441172719")
    other = await make_book(title="Neuromancer", author="William Gibson")

    response = await client.patch(f"/api/books/{other['id']}", json={"isbn": "9780441172719"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "isbn_taken"


async def test_edit_keeping_its_own_isbn_is_fine(make_book, client):
    book = await make_book(isbn="9780441172719")

    response = await client.patch(
        f"/api/books/{book['id']}", json={"isbn": "9780441172719", "title": "Dune!"}
    )

    assert response.status_code == 200


async def test_edit_unknown_book_is_404(client):
    response = await client.patch(f"/api/books/{uuid.uuid4()}", json={"title": "x"})

    assert response.status_code == 404


# Delete and archive


async def test_book_that_never_had_a_loan_is_deleted_with_its_copies(make_book, client, empty_db):
    book = await make_book(copies=2)

    response = await client.delete(f"/api/books/{book['id']}")

    assert response.status_code == 200
    assert response.json() == {"outcome": "deleted"}
    assert (await client.get(f"/api/books/{book['id']}")).status_code == 404
    copies = await empty_db.scalars(select(Copy).where(Copy.book_id == uuid.UUID(book["id"])))
    assert copies.all() == []


async def test_book_with_loan_history_is_archived(make_book, make_member, borrow, client, empty_db):
    book = await make_book(isbn="9780441172719", copies=2)
    member = await make_member()
    loan = (await borrow(book["copies"][0]["id"], member["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")

    response = await client.delete(f"/api/books/{book['id']}")

    assert response.json() == {"outcome": "archived"}
    detail = (await client.get(f"/api/books/{book['id']}")).json()
    assert detail["archived"] is True
    assert detail["has_loan_history"] is True
    listed = (await client.get("/api/books")).json()
    assert listed["total"] == 0
    archived_copies = await empty_db.scalars(
        select(Copy.archived_at).where(Copy.book_id == uuid.UUID(book["id"]))
    )
    assert all(archived_at is not None for archived_at in archived_copies)
    # The loan record is still there.
    assert (await client.post(f"/api/loans/{loan['id']}/return")).status_code == 409


async def test_archiving_frees_the_isbn_for_a_new_book(make_book, make_member, borrow, client):
    book = await make_book(isbn="9780441172719")
    member = await make_member()
    loan = (await borrow(book["copies"][0]["id"], member["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")
    await client.delete(f"/api/books/{book['id']}")

    again = await make_book(isbn="9780441172719")

    assert again["id"] != book["id"]


async def test_delete_is_refused_while_a_copy_is_on_loan(
    make_book, make_member, borrow, client, empty_db
):
    book = await make_book(copies=2)
    member = await make_member()
    await borrow(book["copies"][1]["id"], member["id"])

    response = await client.delete(f"/api/books/{book['id']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "book_has_active_loans"
    stored = await empty_db.get(Book, uuid.UUID(book["id"]))
    assert stored is not None
    assert stored.archived_at is None


async def test_deleting_an_archived_book_again_changes_nothing(
    make_book, make_member, borrow, client
):
    book = await make_book()
    member = await make_member()
    loan = (await borrow(book["copies"][0]["id"], member["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")
    await client.delete(f"/api/books/{book['id']}")
    events_before = len((await client.get("/api/activity")).json())

    response = await client.delete(f"/api/books/{book['id']}")

    assert response.json() == {"outcome": "archived"}
    assert len((await client.get("/api/activity")).json()) == events_before


async def test_archived_book_cannot_be_edited_or_given_copies(
    make_book, make_member, borrow, client
):
    book = await make_book()
    member = await make_member()
    loan = (await borrow(book["copies"][0]["id"], member["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")
    await client.delete(f"/api/books/{book['id']}")

    edit = await client.patch(f"/api/books/{book['id']}", json={"title": "Dune 2"})
    copies = await client.post(f"/api/books/{book['id']}/copies", json={"count": 1})

    assert edit.status_code == 409
    assert edit.json()["error"]["code"] == "book_archived"
    assert copies.status_code == 409
    assert copies.json()["error"]["code"] == "book_archived"


async def test_delete_unknown_book_is_404(client):
    response = await client.delete(f"/api/books/{uuid.uuid4()}")

    assert response.status_code == 404


# Copies


async def test_add_copies_returns_the_book_with_new_copies(make_book, client):
    book = await make_book()

    response = await client.post(f"/api/books/{book['id']}/copies", json={"count": 2})

    assert response.status_code == 201
    detail = response.json()
    assert detail["copies_total"] == 3
    assert len({copy["code"] for copy in detail["copies"]}) == 3


async def test_add_copies_defaults_to_one(make_book, client):
    book = await make_book()

    response = await client.post(f"/api/books/{book['id']}/copies", json={})

    assert response.json()["copies_total"] == 2


@pytest.mark.parametrize("count", [0, 21])
async def test_add_copies_count_must_be_1_to_20(make_book, client, count):
    book = await make_book()

    response = await client.post(f"/api/books/{book['id']}/copies", json={"count": count})

    assert response.status_code == 422


async def test_add_copies_to_unknown_book_is_404(client):
    response = await client.post(f"/api/books/{uuid.uuid4()}/copies", json={"count": 1})

    assert response.status_code == 404
