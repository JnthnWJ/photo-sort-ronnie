from photosorter.patterns import date_from_filename
from datetime import date


def test_date_from_filename_contiguous():
    assert date_from_filename("IMG_20240305.jpg") == date(2024, 3, 5)


def test_date_from_filename_with_sep():
    assert date_from_filename("holiday-2024-12-31.png") == date(2024, 12, 31)


def test_date_from_filename_no_match():
    assert date_from_filename("randomfile.jpg") is None

