from core.claims.engine import (
    check_claims,
    find_unreferenced_attributes,
    find_unsupported_numeric_claims,
)


class TestFindUnsupportedNumericClaims:
    def test_grounded_number_is_not_flagged(self):
        text = "Telefon ima 128GB memorije."
        attributes = {"storage": "128GB"}
        assert find_unsupported_numeric_claims(text, attributes) == ()

    def test_hallucinated_number_is_flagged(self):
        text = "Vodootporan do 50m dubine."
        attributes = {"brand": "Samsung", "color": "crna"}
        issues = find_unsupported_numeric_claims(text, attributes)
        assert len(issues) == 1
        assert issues[0].claim_text == "50m"

    def test_decimal_comma_and_period_are_equivalent(self):
        text = "Ekran je 6,1 inč."
        attributes = {"screen_size": "6.1 inch"}
        assert find_unsupported_numeric_claims(text, attributes) == ()

    def test_mixed_grounded_and_hallucinated(self):
        text = "Baterija 5000mAh. Vodootporno do 100m."
        attributes = {"battery": "5000mAh"}
        issues = find_unsupported_numeric_claims(text, attributes)
        assert len(issues) == 1
        assert issues[0].claim_text == "100m"

    def test_no_numbers_means_no_claims(self):
        text = "Kvalitetna kožna jakna u crnoj boji."
        attributes = {"brand": "Gigatron"}
        assert find_unsupported_numeric_claims(text, attributes) == ()

    def test_number_embedded_in_attribute_value_is_grounded(self):
        text = "Veličina 42 je dostupna."
        attributes = {"size": "42"}
        assert find_unsupported_numeric_claims(text, attributes) == ()


class TestFindUnreferencedAttributes:
    def test_used_attribute_is_referenced(self):
        text = "Crna kožna jakna."
        attributes = {"color": "crna", "material": "koža"}
        unreferenced = find_unreferenced_attributes(text, attributes)
        assert "color" not in unreferenced
        # "koža" (material) is not a literal substring of "kožna" - this is
        # the documented limitation of a literal-text check, not a bug:
        assert "material" in unreferenced

    def test_attribute_not_mentioned_is_unreferenced(self):
        text = "Crna jakna."
        attributes = {"color": "crna", "warranty": "24 meseca"}
        unreferenced = find_unreferenced_attributes(text, attributes)
        assert "warranty" in unreferenced


class TestCheckClaims:
    def test_clean_report_when_fully_grounded(self):
        text = "Telefon sa 128GB memorije."
        attributes = {"storage": "128GB"}
        report = check_claims(text, attributes)
        assert report.is_clean
        assert "storage" in report.referenced_attributes

    def test_report_flags_unsupported_claim(self):
        text = "Vodootporan do 50m."
        attributes = {"brand": "Samsung"}
        report = check_claims(text, attributes)
        assert not report.is_clean
        assert report.unsupported[0].claim_text == "50m"
        assert "brand" in report.unreferenced_attributes
