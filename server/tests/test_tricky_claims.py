"""Disguised scam messages must still be flagged; genuine notices and warnings must not be."""
import pytest

from app.forensics import text

SHOULD_FLAG = [
 "PM Kisan: pay Rs499 to get your installment", "PM Kisan: pay Rs. 499/- registration", "PM Kisan pay 499 rupees only",
 "PM Kisan pay INR499 now", "PM Kisan pay ₹499.00 now", "PM Kisan: fee: 499", "PM Kisan pay ₹४९९", "PM Kisan pay Ｒｓ ４９９",
 "Ayushman card: share 0TP to activate", "Ayushman card: share O.T.P to activate", "Ayushman card: share o t p to activate",
 "Ayushman card: send the 6 digit code you receive", "Pаy Rs 499 (cyrillic a) for scholarship", "scholarship! G-Pay 499 to 98765 43210",
 "PM Kisan ka paisa chahiye to 199 bhejo", "Scholarship registration charges 300 rs pay via phonepe",
 "Click http://pmkisan-gov.in.claim-now.xyz to get Rs 6000", "Send Aadhaar photo and bank PIN on WhatsApp for PM Kisan",
 "आयुष्मान कार्ड के लिए ₹२०० जमा करें",]

SHOULD_PASS = [
 "PM-KISAN: Rs 6,000 per year in three instalments of Rs 2,000. Registration is free. Never share your OTP with anyone. Apply at pmkisan.gov.in",
 "Ayushman Bharat PM-JAY gives Rs 5 lakh hospital cover per family per year. The card is free; do not pay anyone. Check at beneficiary.nha.gov.in",
 "Beware: fraudsters ask for a fee or OTP for PM Kisan. The scheme never charges any fee.",
]


@pytest.mark.parametrize("claim", SHOULD_FLAG)
def test_disguised_scams_are_flagged(claim):
    assert text.analyze_claim(claim)["score"] < 0.4, claim


@pytest.mark.parametrize("claim", SHOULD_PASS)
def test_genuine_notices_and_warnings_pass(claim):
    assert text.analyze_claim(claim)["score"] >= 0.6, claim
