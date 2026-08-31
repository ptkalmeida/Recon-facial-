"""Validação de entrada dos nomes de pessoa (2ª camada contra o XSS armazenado)."""

import pytest
from pydantic import ValidationError

from app.models.schemas import UserCreate, UserUpdate, validate_person_name


@pytest.mark.parametrize("name", [
    "Maria Silva",
    "José da Conceição",
    "Ana-Clara O'Brien",
    "Dr. Paulo Jr.",
    "Agente 007",
])
def test_accepts_real_names(name):
    assert validate_person_name(name) == name


@pytest.mark.parametrize("name", [
    '<img src=x onerror="fetch(\'//evil\')">',
    "<script>alert(1)</script>",
    "Maria <b>Silva</b>",
    '=HYPERLINK("http://evil","x")',
    "nome\x00nulo",
    "quebra\nde linha",
    "   ",
])
def test_rejects_markup_and_formula_payloads(name):
    with pytest.raises(ValueError):
        validate_person_name(name)


def test_strips_surrounding_whitespace():
    assert validate_person_name("  Maria Silva  ") == "Maria Silva"


def test_user_create_rejects_xss_payload():
    with pytest.raises(ValidationError):
        UserCreate(name="<script>alert(1)</script>")


def test_user_update_rejects_xss_payload_but_allows_none():
    with pytest.raises(ValidationError):
        UserUpdate(name="<img src=x onerror=alert(1)>")

    assert UserUpdate(name=None).name is None
