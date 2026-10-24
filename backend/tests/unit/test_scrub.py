from bellhop.services.scrub import scrub


def test_resident_name_becomes_a_neutral_label():
    out = scrub("Margaret Alvarez said Margaret likes tea", resident_name="Margaret Alvarez")
    assert "Margaret" not in out
    assert "the resident" in out


def test_family_first_names_are_kept_because_they_are_the_memory():
    out = scrub("My grandson Mateo visits on Sundays", resident_name="Margaret Alvarez")
    assert "Mateo" in out


def test_phone_numbers_and_emails_are_masked():
    out = scrub("Call me on (415) 555-0132 or mail ana@example.com", resident_name=None)
    assert "555" not in out
    assert "example.com" not in out


def test_long_digit_runs_such_as_ids_are_masked():
    assert "123456789" not in scrub("My number is 123456789", resident_name=None)


def test_short_numbers_are_kept():
    assert "two sugars" in scrub("tea with two sugars at 3 o'clock", resident_name=None)
    assert "3 o'clock" in scrub("tea with two sugars at 3 o'clock", resident_name=None)
