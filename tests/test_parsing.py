import pytest

import parsing


@pytest.mark.parametrize("text,expected", [
    ("What does P0420 mean?", "P0420"),
    ("p0420", "P0420"),
    ("code P-0420 came up", "P0420"),
    ("the scanner says P 0420", "P0420"),
    ("P 0 4 2 0 on my car", "P0420"),
    ("p zero four two zero", "P0420"),
    ("P oh four twenty", "P0420"),
    ("pee zero three hundred", "P0300"),
    ("P zero one seventy one", "P0171"),
    ("I have a U0100", "U0100"),
    ("it shows P0A80", "P0A80"),
])
def test_finds_code(text, expected):
    assert parsing.pick_code(text) == expected


@pytest.mark.parametrize("text", [
    "my car is making a noise",
    "2015 Honda Accord with 128000 miles",
    "P9999",
    "please help",
])
def test_no_code(text):
    assert parsing.pick_code(text) is None


def test_prefers_known_code():
    text = "my Chevy C1500 is showing P0300"
    assert parsing.pick_code(text) == "C1500"
    assert parsing.pick_code(text, known={"P0300"}) == "P0300"


def test_full_question():
    parsed = parsing.parse_question(
        "What does P0420 mean on my 2015 Honda Accord with 128k miles?")
    assert parsed == {"code": "P0420", "year": 2015, "make": "Honda",
                      "model": "Accord", "mileage": 128000}


@pytest.mark.parametrize("text,mileage", [
    ("128,000 miles", 128000),
    ("128000 miles", 128000),
    ("about 128 thousand miles", 128000),
    ("92k on it", 92000),
    ("85.5k miles", 85500),
    ("no number here", None),
])
def test_mileage(text, mileage):
    assert parsing.parse_question(text)["mileage"] == mileage


@pytest.mark.parametrize("text,make,model", [
    ("2018 ford f-150 with P0300", "Ford", "F-150"),
    ("my chevy silverado has a code", "Chevrolet", "Silverado"),
    ("Jeep Grand Cherokee P0456", "Jeep", "Grand Cherokee"),
    ("a 2020 Tesla Model 3", "Tesla", "Model 3"),
    ("my toyota is showing P0171", "Toyota", None),
    ("VW Jetta", "Volkswagen", "Jetta"),
])
def test_make_and_model(text, make, model):
    parsed = parsing.parse_question(text)
    assert (parsed["make"], parsed["model"]) == (make, model)


def test_year_is_not_taken_from_the_code():
    assert parsing.parse_question("P2015 on a Honda")["year"] is None


def test_describe_unknown_code():
    assert "powertrain" in parsing.describe_code_structure("P0999")
    assert "manufacturer-specific" in parsing.describe_code_structure("P1234")
    assert "network" in parsing.describe_code_structure("U0121")
