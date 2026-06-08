import logging
import requests

FORM_URL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSf4HvBlIWFQpQy8DunLwRBOXpS8HSSYVoqM4yCxbsaltj0iKg/formResponse"
)


def save_lead(
    profile_name: str,
    phone: str,
    business_name: str = "Not Provided",
    service: str = "Not Provided",
    email: str = "Not Provided",
    city: str = "Not Provided",
):
    data = {
        "entry.1897550423": profile_name,
        "entry.1278195571": phone,
        "entry.1719208359": business_name,
        "entry.106808123": service,
        "entry.1916819408": email,
        "entry.1368285891": city,
    }

    try:
        response = requests.post(
            FORM_URL,
            data=data,
            timeout=10,
        )

        logging.info(
            "Lead Saved | Name=%s | Phone=%s | Response=%s",
            profile_name,
            phone,
            response.status_code,
        )

    except Exception as exc:
        logging.exception("Lead save failed: %s", exc)