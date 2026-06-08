"""Production-ready Flask webhook for a JSON-backed WhatsApp FAQ bot.

Startup flow:
1. Load data/company_data.json once.
2. Build FAQ mappings once from the loaded JSON.
3. Keep both objects cached in RAM for every webhook request.

Request flow:
1. Twilio posts Body and From to /whatsapp.
2. The message is matched with RapidFuzz against cached FAQ questions.
3. A reply is returned only when the score meets the configured threshold.
4. The reply is split if needed and sent through the Twilio WhatsApp API.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify, request

from config import DATA_FILE, FLASK_DEBUG, FLASK_HOST, FLASK_PORT, LOG_FILE, SAFE_FALLBACK_RESPONSE
from faq_engine import CompanyDataError, build_faqs, find_best_answer, load_company_data, GREETINGS
from twilio_service import send_whatsapp_reply,send_welcome_template
from lead_service import save_lead

def configure_logging() -> None:
    """Configure rotating file logs for webhook activity and errors."""

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger("twilio").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


configure_logging()

try:
    COMPANY_DATA = load_company_data(DATA_FILE)
    FAQS = build_faqs(COMPANY_DATA)
    logging.info("Loaded company data from %s and built %s FAQ mappings", DATA_FILE, len(FAQS))
except CompanyDataError:
    logging.exception("Application startup failed because company data could not be loaded")
    raise



def get_company_info() -> str:
    return (
    f"{COMPANY_DATA.get('company_name', '')}\n\n"
    f"{COMPANY_DATA.get('tagline', '')}\n\n"
    f"{COMPANY_DATA.get('about_company', '')}\n\n"
    f"Experience: {COMPANY_DATA.get('experience', '')}\n\n"
    )

def get_services_menu() -> str:
    services = COMPANY_DATA.get("services", [])


    if not services:
        return "No services are currently available."

    return (
        "Our Services:\n\n"
        + "\n".join(f"• {service}" for service in services)
        + "\n\nType the service name you want to know more about."
    )

def get_contact_info() -> str:
    return (
    "Thank you for your interest.\n\n"
    "Please share:\n"
    "• Your Name\n"
    "• Business Name\n"
    "• Service Required\n"
    "• Contact Number\n"
    "• Email Address\n"
    "• City\n\n"
    "Our team will contact you shortly."
    )




app = Flask(__name__)


@app.get("/health")
def health_check():
    """Small health endpoint for hosting platforms and uptime checks."""

    return jsonify(
        {
            "status": "ok",
            "company": COMPANY_DATA.get("company_name"),
            "faq_count": len(FAQS),
        }
    )


@app.post("/whatsapp")
def whatsapp_webhook():
    """Twilio WhatsApp webhook endpoint.

    The endpoint returns JSON for observability, while the actual WhatsApp
    reply is sent through Twilio's REST API. All user-facing answers come from
    cached FAQ data generated from company_data.json.
    """

    user_number = request.form.get("From", "").strip()
    incoming_message = request.form.get("Body", "").strip()
    profile_name = request.form.get("ProfileName", "Unknown")



    matched_faq = None
    match_score = 0
    bot_reply = SAFE_FALLBACK_RESPONSE

    try:
        message = incoming_message.lower().strip()

        if any(keyword in message for keyword in GREETINGS):
            save_lead(
                profile_name=profile_name,
                phone=user_number,
            )
            
            logging.info(
                "Lead Saved | Name=%s | Phone=%s",
                profile_name,
                user_number,
            )

            send_welcome_template(user_number)

            return jsonify(
                {
                    "ok": True,
                    "template_sent": True,
                }
            ), 200  
              
        elif message in {"about company", "about_company"}:
            matched_faq = "about_company"
            match_score = 100
            bot_reply = get_company_info()

        elif message in {"services", "services_menu"}:
            matched_faq = "services"
            match_score = 100
            bot_reply = get_services_menu()

        elif message in {"contact us", "contact_us"}:
            matched_faq = "contact"
            match_score = 100
            bot_reply = get_contact_info()

        else:
            match_result = find_best_answer(incoming_message, FAQS)
            matched_faq = match_result.matched_question
            match_score = match_result.score
            bot_reply = match_result.answer


        send_result = send_whatsapp_reply(user_number, bot_reply)
        if not send_result.success:
            logging.error("Twilio send failed for %s: %s", user_number, send_result.error)

        logging.info(
            "User Number: %s | Incoming Message: %s | Matched FAQ: %s | "
            "Match Score: %.2f | Bot Reply: %s",
            user_number,
            incoming_message,
            matched_faq,
            match_score,
            bot_reply.replace("\n", "\\n"),
        )
 
        status_code = 200 if send_result.success else 502
        return jsonify(
            {
                "ok": send_result.success,
                "matched_faq": matched_faq,
                "match_score": match_score,
                "messages_sent": send_result.sent_count,
            }
        ), status_code
    except Exception:
        logging.exception(
            "Unexpected webhook error | User Number: %s | Incoming Message: %s | "
            "Matched FAQ: %s | Match Score: %.2f | Bot Reply: %s",
            user_number,
            incoming_message,
            matched_faq,
            match_score,
            bot_reply.replace("\n", "\\n"),
        )
        return jsonify({"ok": False, "error": "safe_fallback_applied"}), 500


if __name__ == "__main__":
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
