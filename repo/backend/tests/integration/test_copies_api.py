"""Finding a copy by the code on its label, as staff type or scan it."""

import pytest

pytestmark = pytest.mark.integration

LOOKUP_FIELDS = {"copy", "book", "status", "archived", "active_loan", "held_for"}


def number_of(code: str) -> str:
    """The copy number alone: CP-0042 -> "42"."""
    return str(int(code.removeprefix("CP-")))


async def lookup(client, code):
    response = await client.get(f"/api/copies/by-code/{code}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_an_available_copy_shows_its_book(make_book, client):
    book = await make_book(title="Dune", author="Frank Herbert")
    copy = book["copies"][0]

    found = await lookup(client, copy["code"])

    assert set(found) == LOOKUP_FIELDS
    assert found["copy"] == {"id": copy["id"], "code": copy["code"]}
    assert found["book"] == {"id": book["id"], "title": "Dune", "author": "Frank Herbert"}
    assert (found["status"], found["archived"], found["active_loan"]) == (
        "available",
        False,
        None,
    )


async def test_a_borrowed_copy_shows_its_active_loan(make_book, make_member, borrow, client):
    book = await make_book(copies=2)
    maya = await make_member("Maya Hassan")
    loan = (await borrow(book["copies"][1]["id"], maya["id"])).json()

    found = await lookup(client, book["copies"][1]["code"])

    assert found["status"] == "borrowed"
    assert found["active_loan"] == loan
    assert found["active_loan"]["member"] == {"id": maya["id"], "full_name": "Maya Hassan"}


async def test_a_returned_copy_is_available_again(make_book, make_member, borrow, client):
    book = await make_book()
    loan = (await borrow(book["copies"][0]["id"], (await make_member())["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")

    found = await lookup(client, book["copies"][0]["code"])

    assert (found["status"], found["active_loan"]) == ("available", None)


async def test_a_copy_of_an_archived_book_is_found_and_marked_archived(
    make_book, make_member, borrow, client
):
    book = await make_book()
    loan = (await borrow(book["copies"][0]["id"], (await make_member())["id"])).json()
    await client.post(f"/api/loans/{loan['id']}/return")
    await client.delete(f"/api/books/{book['id']}")

    found = await lookup(client, book["copies"][0]["code"])

    assert (found["archived"], found["status"]) == (True, "available")


@pytest.mark.parametrize(
    "typed",
    [
        lambda code: code.lower(),
        lambda code: number_of(code),
        lambda code: f"cp{number_of(code)}",
        lambda code: f"CP-{number_of(code)}",
        lambda code: f" {code} ",
    ],
    ids=["lower case", "number alone", "prefix without dash", "unpadded", "spaces"],
)
async def test_the_code_can_be_typed_loosely(make_book, client, typed):
    copy = (await make_book())["copies"][0]

    found = await lookup(client, typed(copy["code"]))

    assert found["copy"]["id"] == copy["id"]


@pytest.mark.parametrize("code", ["CP-99999999", "99999999", "not-a-code"])
async def test_an_unknown_code_is_404(client, code):
    response = await client.get(f"/api/copies/by-code/{code}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_the_404_names_the_code_that_was_looked_up(client):
    response = await client.get("/api/copies/by-code/99999999")

    assert response.json()["error"]["message"] == "No copy has the code CP-99999999."


async def test_an_overlong_code_is_422(client):
    response = await client.get(f"/api/copies/by-code/{'9' * 41}")

    assert response.status_code == 422
