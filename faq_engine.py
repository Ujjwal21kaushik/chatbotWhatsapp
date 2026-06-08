"""FAQ loading, generation, and RapidFuzz matching.

The engine is deliberately extractive: every answer is generated from
company_data.json at startup and cached in memory. No external AI service is
called, and no answer is invented at request time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from config import MATCH_THRESHOLD, SAFE_FALLBACK_RESPONSE


class CompanyDataError(RuntimeError):
    """Raised when company_data.json is missing, invalid, or unusable."""


GENERIC_TOKENS = {
    "a",
    "about",
    "address",
    "all",
    "an",
    "and",
    "any",
    "are",
    "can",
    "company",
    "contact",
    "details",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "give",
    "have",
    "help",
    "how",
    "i",
    "in",
    "info",
    "information",
    "is",
    "it",
    "know",
    "looking",
    "may",
    "me",
    "my",
    "number",
    "of",
    "offer",
    "provide",
    "services",
    "share",
    "show",
    "tell",
    "the",
    "to",
    "want",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "work",
    "you",
    "your",
}

MIN_TOKEN_LENGTH = 3
HIGH_CONFIDENCE_SCORE = 95

REQUIREMENT_INTENT_TOKENS = {
    "need",
    "require",
    "requirement",
    "requirements",
    "want",
    "manage",
}

SERVICE_CANONICAL_QUESTIONS = {
    "What services do you provide?",
    "Can you build a website for me?",
    "What website design features do you provide?",
    "Do you provide SEO services?",
}

GREETINGS = {
    "hi",
    "hii",
    "hiii",
    "hello",
    "hey",
    "heyy",
    "start",
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
    "gm",
    "gn",
    "greetings",
    "sup",
    "what's up",
    "whats up",
    "howdy",
}


@dataclass(frozen=True)
class FAQEntry:
    """One searchable user question mapped to one safe company-data answer."""

    question: str
    answer: str
    canonical_question: str

    
@dataclass(frozen=True)
class MatchResult:
    """Result returned by the matcher for logging and webhook handling."""

    answer: str
    matched_question: str | None
    score: float
    accepted: bool


def load_company_data(path: Path) -> dict[str, Any]:
    """Load company data once during Flask startup.

    The JSON file is not read inside request handlers, which keeps webhook
    latency predictable and avoids repeated disk I/O.
    """

    try:
        with path.open("r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except FileNotFoundError as exc:
        raise CompanyDataError(f"Company data file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CompanyDataError(f"Company data file contains invalid JSON: {path}") from exc
    except OSError as exc:
        raise CompanyDataError(f"Could not read company data file: {path}") from exc

    if not isinstance(data, dict):
        raise CompanyDataError("Company data must be a JSON object.")

    if not data.get("company_name"):
        raise CompanyDataError("Company data must include company_name.")

    return data


def normalize_text(text: str) -> str:
    """Normalize user and FAQ text for capitalization and punctuation changes."""

    normalized = text.casefold()
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _content_tokens(text: str) -> set[str]:
    """Return meaningful tokens used by the safety guard."""

    return {
        token
        for token in normalize_text(text).split()
        if len(token) >= MIN_TOKEN_LENGTH and token not in GENERIC_TOKENS
    }


def _join_items(items: list[Any]) -> str:
    """Format JSON list values into a readable WhatsApp answer."""

    safe_items = [str(item).strip() for item in items if str(item).strip()]
    return "\n".join(f"- {item}" for item in safe_items)


def _get_contact(company_data: dict[str, Any]) -> dict[str, str]:
    """Support both nested contact data and older top-level email/website fields."""

    contact = company_data.get("contact") if isinstance(company_data.get("contact"), dict) else {}
    return {
        "phone": str(contact.get("phone") or company_data.get("phone") or "").strip(),
        "email": str(contact.get("email") or company_data.get("email") or "").strip(),
        "website": str(contact.get("website") or company_data.get("website") or "").strip(),
    }


def _add_variations(
    faqs: list[FAQEntry],
    canonical_question: str,
    answer: str,
    variations: list[str],
) -> None:
    """Add one answer behind several wording variations and synonyms."""

    if not answer.strip():
        return

    for question in variations:
        faqs.append(
            FAQEntry(
                question=question,
                answer=answer,
                canonical_question=canonical_question,
            )
        )


def build_faqs(company_data: dict[str, Any]) -> list[FAQEntry]:
    """Generate all FAQs from company_data.json during application startup.

    Static company facts are turned into answers here, then matched from RAM.
    Custom FAQ items in the JSON are also included, but prompt-like fields are
    ignored because this bot must never generate AI-style fallback answers.
    """

    faqs: list[FAQEntry] = []
    company_name = str(company_data.get("company_name", "RightAds Digital")).strip()
    tagline = str(company_data.get("tagline", "")).strip()
    about = str(company_data.get("about_company", "")).strip()
    experience = str(company_data.get("experience", "")).strip()
    services = company_data.get("services", [])
    industries = company_data.get("industries_served", [])
    website_features = company_data.get("website_design_features", [])
    seo_services = company_data.get("seo_services", [])
    locations = company_data.get("target_locations", [])
    reasons = company_data.get("why_choose_us", [])
    vision = str(company_data.get("vision", "")).strip()
    mission = str(company_data.get("mission", "")).strip()
    contact = _get_contact(company_data)

    company_answer = f"{company_name}"
    if tagline:
        company_answer += f" - {tagline}"
    if about:
        company_answer += f"\n\n{about}"

    _add_variations(
        faqs,
        "Tell me about the company.",
        company_answer,
        [
            "Tell me about the company.",
            "What is RightAds Digital?",
            "Who are you?",
            "Tell me about RightAds Digital.",
            "Company information",
            "About your company",
        ],
    )

    if isinstance(services, list) and services:
        services_answer = f"{company_name} provides these services:\n{_join_items(services)}"
        _add_variations(
            faqs,
            "What services do you provide?",
            services_answer,
            [
                "What services do you provide?",
                "Tell me your services",
                "What do you offer?",
                "Can you explain your services?",
                "Services",
                "Your offerings",
                "What digital marketing services do you provide?",
                "Do you provide marketing services?",
            ],
        )

        service_names = {str(service).casefold() for service in services}
        if any("website" in service for service in service_names):
            website_answer = (
                f"Yes. {company_name} provides Website Design and Website Development services."
            )
            if isinstance(website_features, list) and website_features:
                website_answer += "\n\nWebsite features include:\n" + _join_items(website_features)

            _add_variations(
                faqs,
                "Can you build a website for me?",
                website_answer,
                [
                    "Can you build website for me?",
                    "Can you build a website for me?",
                    "Can you make website for me?",
                    "Can you create a website?",
                    "I need a website",
                    "I want website development",
                    "Do you build websites?",
                    "Do you make websites?",
                    "Website development",
                    "Website design",
                    "Can you redesign my website?",
                    "I want an animated website",
                    "I need an animated website",
                    "I have a website requirement",
                    "I have a requirement for website design",
                    "I want a responsive website",
                    "I want a business website",
                    "I want a custom website",
                ],
            )

        _add_variations(
            faqs,
            "What services do you provide?",
            (
                f"Yes. {company_name} provides digital marketing, website, SEO, "
                "ads, branding, lead generation, and app development services.\n\n"
                f"Available services:\n{_join_items(services)}"
            ),
            [
                "I have a requirement",
                "I want to share my requirement",
                "I need digital marketing services",
                "I need online marketing services",
                "I want a service",
                "I want digital services",
                "I have a project requirement",
                "Can you handle my requirement?",
                "Do you provide this service?",
            ],
        )

    if experience:
        _add_variations(
            faqs,
            "How many years of experience do you have?",
            f"{company_name} has {experience} of experience.",
            [
                "How many years of experience do you have?",
                "What is your experience?",
                "How experienced is RightAds Digital?",
                "How long have you been working?",
                "Company experience",
            ],
        )

    if isinstance(industries, list) and industries:
        _add_variations(
            faqs,
            "What industries do you serve?",
            f"{company_name} serves these industries:\n{_join_items(industries)}",
            [
                "What industries do you serve?",
                "Which industries do you work with?",
                "What businesses do you serve?",
                "Do you work with startups?",
                "Industries served",
                "Who are your clients?",
            ],
        )

    if contact["phone"]:
        _add_variations(
            faqs,
            "What is your phone number?",
            f"{company_name}'s phone number is {contact['phone']}.",
            [
                "What is your phone number?",
                "Share your phone number",
                "Can I call you?",
                "Contact number",
                "Mobile number",
            ],
        )

    if contact["email"]:
        _add_variations(
            faqs,
            "What is your email address?",
            f"{company_name}'s email address is {contact['email']}.",
            [
                "What is your email address?",
                "Share your email",
                "Email address",
                "How can I email you?",
                "Mail id",
            ],
        )

    if contact["website"]:
        _add_variations(
            faqs,
            "What is your website?",
            f"{company_name}'s website is {contact['website']}.",
            [
                "What is your website?",
                "Website details",
                "Share your website",
                "Website URL",
                "Where can I visit your website?",
            ],
        )

    contact_parts = []
    if contact["phone"]:
        contact_parts.append(f"Phone: {contact['phone']}")
    if contact["email"]:
        contact_parts.append(f"Email: {contact['email']}")
    if contact["website"]:
        contact_parts.append(f"Website: {contact['website']}")
    if contact_parts:
        contact_answer = f"You can contact {company_name} here:"
        if contact["email"]:
            contact_answer += f"\nEmail: {contact['email']}"
        if contact["website"]:
            contact_answer += f"\nWebsite: {contact['website']}"

        _add_variations(
            faqs,
            "How can I contact you?",
            contact_answer,
            [
                "How can I contact you?",
                "How may I contact you?",
                "Contact information",
                "How do I reach you?",
                "Can someone contact me?",
                "I want to talk to your team",
                "I want to contact you",
                "Contact you",
                "Share contact details",
                "Give me your contact details",
                "How can I connect with RightAds Digital?",
            ],
        )

    greeting_answer = (
        f"Hello! Welcome to {company_name}. I can help with company information, "
        "services, experience, industries served, contact information, and website details."
    )
    _add_variations(
        faqs,
        "Greeting",
        greeting_answer,
        [
            "Hi",
            "Hello",
            "Hey",
            "Hii",
            "Good morning",
            "Good afternoon",
            "Good evening",
            "Namaste",
        ],
    )

    if contact["email"] or contact["website"]:
        thanks_answer = f"You're welcome. For {company_name}:"
        if contact["email"]:
            thanks_answer += f"\nEmail: {contact['email']}"
        if contact["website"]:
            thanks_answer += f"\nWebsite: {contact['website']}"
    else:
        thanks_answer = f"You're welcome. You can ask me about {company_name} services and company information."

    _add_variations(
        faqs,
        "Thanks",
        thanks_answer,
        [
            "Thank you",
            "Thanks",
            "Thankyou",
            "Thx",
            "Thanks a lot",
            "Thank you so much",
        ],
    )

    ok_answer = (
        f"Okay. You can ask me about {company_name} services, website details, "
        "industries served, experience, or contact information."
    )
    _add_variations(
        faqs,
        "Acknowledgement",
        ok_answer,
        [
            "Ok",
            "Okay",
            "Okk",
            "K",
            "Fine",
            "Got it",
            "Alright",
        ],
    )

    if isinstance(website_features, list) and website_features:
        _add_variations(
            faqs,
            "What website design features do you provide?",
            f"{company_name} provides these website design features:\n{_join_items(website_features)}",
            [
                "What website design features do you provide?",
                "Tell me about website design",
                "Do you make responsive websites?",
                "Website development features",
                "Website design details",
                "What website features do you provide?"
                "What type of features do you provide for websites?",
                "What features are included in website design?",
                "Website features",
                "Features of your websites",
            ],
        )

    if isinstance(seo_services, list) and seo_services:
        _add_variations(
            faqs,
            "Do you provide SEO services?",
            f"{company_name} provides these SEO services:\n{_join_items(seo_services)}",
            [
                "Do you provide SEO services?",
                "Tell me about SEO",
                "What SEO work do you do?",
                "Search engine optimization services",
                "Can you improve Google ranking?",
            ],
        )

    if isinstance(locations, list) and locations:
        _add_variations(
            faqs,
            "What locations do you serve?",
            f"{company_name} targets these locations:\n{_join_items(locations)}",
                [
                    "What locations do you serve?",
                    "Which cities do you work in?",
                    "Target locations",
                    "Service areas",
                    "Tell me your company locations",
                    "Where do you provide services?",
                    "What are your locations?",
                    "Where are you located?",
                    "Where is your office?",
                    "Do you have any branches?",
                    "Office location",
                    "Company location",
                    "Where can I find you?",
                ],
        )

    if isinstance(reasons, list) and reasons:
        _add_variations(
            faqs,
            "Why should I choose RightAds Digital?",
            f"Reasons to choose {company_name}:\n{_join_items(reasons)}",
            [
                "Why should I choose RightAds Digital?",
                "Why choose you?",
                "What makes you different?",
                "Why work with your agency?",
                "Benefits of RightAds Digital",
            ],
        )

    if vision:
        _add_variations(
            faqs,
            "What is your vision?",
            vision,
            ["What is your vision?", "Company vision", "Tell me your vision"],
        )

    if mission:
        _add_variations(
            faqs,
            "What is your mission?",
            mission,
            ["What is your mission?", "Company mission", "Tell me your mission"],
        )

    custom_faqs = company_data.get("faqs", [])
    if isinstance(custom_faqs, list):
        for item in custom_faqs:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question", "")).strip()
            answer = str(item.get("answer", "")).strip()
            if question and answer:
                _add_variations(faqs, question, answer, [question])

    return faqs


def find_best_answer(
    user_message: str,
    faqs: list[FAQEntry],
    threshold: int = MATCH_THRESHOLD,
) -> MatchResult:
    """Return the closest FAQ answer only when the score is conservative enough.

    RapidFuzz compares normalized text, which handles capitalization, minor
    spelling errors, and many wording variations. The threshold protects the
    bot from answering unrelated questions.
    """

    if not user_message or not user_message.strip() or not faqs:
        return MatchResult(SAFE_FALLBACK_RESPONSE, None, 0, False)

    normalized_message = normalize_text(user_message)
    normalized_questions = [normalize_text(faq.question) for faq in faqs]

    try:
        match = process.extractOne(
            normalized_message,
            normalized_questions,
            scorer=fuzz.WRatio,
        )
    except Exception:
        return MatchResult(SAFE_FALLBACK_RESPONSE, None, 0, False)

    if not match:
        return MatchResult(SAFE_FALLBACK_RESPONSE, None, 0, False)

    _, score, index = match
    faq = faqs[index]

    if score >= threshold:
        if (
            score < HIGH_CONFIDENCE_SCORE
            and _looks_out_of_scope(normalized_message, faqs)
            and not _is_service_requirement(normalized_message, faq)
        ):
            return MatchResult(SAFE_FALLBACK_RESPONSE, faq.canonical_question, score, False)

        return MatchResult(faq.answer, faq.canonical_question, score, True)

    return MatchResult(SAFE_FALLBACK_RESPONSE, faq.canonical_question, score, False)


def _is_service_requirement(normalized_message: str, faq: FAQEntry) -> bool:
    """Allow requirement-style wording for known service answers.

    Users often describe what they want rather than asking a formal FAQ
    question, for example "I want an animated website". Extra descriptive
    words should not block a matched service answer when the intent is clear.
    """

    if faq.canonical_question not in SERVICE_CANONICAL_QUESTIONS:
        return False

    tokens = set(normalized_message.split())
    return bool(tokens & REQUIREMENT_INTENT_TOKENS)


def _looks_out_of_scope(normalized_message: str, faqs: list[FAQEntry]) -> bool:
    """Reject risky mid-confidence matches with unrelated content words.

    RapidFuzz is good at wording variations, but a short unrelated question can
    still look similar to a generic FAQ. This guard keeps the threshold
    conservative by checking whether the user's meaningful terms appear in the
    company-derived FAQ knowledge. Exact or very high confidence variations are
    still allowed by find_best_answer before this guard is applied.
    """

    user_tokens = _content_tokens(normalized_message)
    if not user_tokens:
        return False

    known_tokens: set[str] = set()
    for faq in faqs:
        known_tokens.update(_content_tokens(faq.question))
        known_tokens.update(_content_tokens(faq.answer))
        known_tokens.update(_content_tokens(faq.canonical_question))

    unknown_tokens = user_tokens - known_tokens
    known_overlap = user_tokens & known_tokens

    return bool(unknown_tokens and not known_overlap)
