"""The classification prompt: single source of truth for every tagging run.

The smoke test, the batch run, and the retry/escalation path all build their
requests through `build_request_params()` below, so the prompt, examples, and
output schema can never drift apart between scripts.

Design notes:

- The system prompt + SDG reference + worked examples deliberately add up to
  a large (~4.5k token) stable prefix. That size is intentional: the model
  (Claude Haiku 4.5) only caches prompt prefixes of 4,096+ tokens, and a
  cached prefix is ~90% cheaper to re-send 19,688 times. The reference list
  also genuinely helps a small model pick between similar goals.

- Output is constrained with the API's structured-outputs feature
  (`output_config.format` with a JSON schema), which guarantees the response
  text is schema-valid JSON. Note the schema dialect doesn't allow numeric
  minimum/maximum, so primary_sdg uses an enum of 1..17 instead.
"""

BULK_MODEL = "claude-haiku-4-5"       # cheap + good at classification
ESCALATION_MODEL = "claude-sonnet-5"  # for cases the bulk model fumbles
MAX_TOKENS = 1000                     # output is a small JSON object
OBJECTS_CHAR_CAP = 6000               # objects text is occasionally huge

SDG_TITLES = {
    1: "No Poverty",
    2: "Zero Hunger",
    3: "Good Health and Well-being",
    4: "Quality Education",
    5: "Gender Equality",
    6: "Clean Water and Sanitation",
    7: "Affordable and Clean Energy",
    8: "Decent Work and Economic Growth",
    9: "Industry, Innovation and Infrastructure",
    10: "Reduced Inequalities",
    11: "Sustainable Cities and Communities",
    12: "Responsible Consumption and Production",
    13: "Climate Action",
    14: "Life Below Water",
    15: "Life on Land",
    16: "Peace, Justice and Strong Institutions",
    17: "Partnerships for the Goals",
}

_SYSTEM_CORE = """\
You are a careful research assistant classifying UK-registered charities. You \
are given a charity's name, its self-described activities, and its charitable \
objects. Your job is to (1) assign the single most relevant UN Sustainable \
Development Goal (primary SDG) and up to two secondary SDGs, (2) write a \
one-line plain-English focus summary, and (3) classify how the charity \
engages overseas.

Rules:
- Base every judgement only on the text provided. Do not use outside \
knowledge about specific named charities.
- SDGs are the 17 UN Sustainable Development Goals, numbered 1 to 17. Use \
the official short titles.
- If the text is too sparse to judge an SDG confidently, set primary_sdg to \
the best single guess and set sdg_confidence to "low".
- For overseas_engagement, choose exactly one: "operates_directly_abroad" \
(the charity itself runs activities or has staff/projects in other \
countries), "funds_partners_abroad" (the charity mainly gives grants to or \
works through partner organisations overseas), or "uk_fundraising_only" (the \
charity raises money in the UK but the text does not indicate it operates or \
funds work abroad itself). If genuinely ambiguous, choose the best fit and \
set engagement_confidence to "low".
- Never invent facts. Keep the summary under 20 words. Return only the \
structured output."""

_SDG_REFERENCE = """\
Reference - the 17 UN Sustainable Development Goals and what typically \
falls under each for charity classification:

1. No Poverty - poverty relief, cash/material aid, livelihoods support, \
emergency relief of destitution.
2. Zero Hunger - food aid, feeding programmes, nutrition, agriculture and \
food security, farmer training.
3. Good Health and Well-being - hospitals, clinics, medical aid and \
equipment, disease prevention, disability care, mental health, hospices.
4. Quality Education - schools, scholarships, teacher training, literacy, \
vocational and skills education, educational resources.
5. Gender Equality - women's and girls' rights, empowerment, protection \
from gender-based violence, maternal advocacy.
6. Clean Water and Sanitation - wells, boreholes, water supply, sanitation, \
hygiene (WASH) programmes.
7. Affordable and Clean Energy - solar/renewable energy access, clean \
cookstoves, rural electrification.
8. Decent Work and Economic Growth - employment, microfinance, small \
business support, fair trade, anti-slavery and anti-trafficking work.
9. Industry, Innovation and Infrastructure - technology access, \
engineering, transport and communications infrastructure.
10. Reduced Inequalities - refugees, migrants, minority and marginalised \
group support, social inclusion.
11. Sustainable Cities and Communities - housing, community development, \
disaster resilience and reconstruction, cultural heritage.
12. Responsible Consumption and Production - recycling, waste reduction, \
sustainable supply chains.
13. Climate Action - climate mitigation/adaptation, environmental campaigns \
focused on climate.
14. Life Below Water - marine conservation, oceans, fisheries.
15. Life on Land - wildlife and habitat conservation, forestry, land \
ecosystems, animal welfare abroad.
16. Peace, Justice and Strong Institutions - human rights, legal aid, \
peacebuilding, anti-corruption, good governance, victims of conflict.
17. Partnerships for the Goals - umbrella bodies, capacity building for \
other NGOs, development education and volunteering platforms.

Classification guidance for common hard cases:
- Disaster/humanitarian relief: pick the goal matching the primary need \
addressed (often 1, 2, 3, or 11 for reconstruction).
- Purely religious advancement (missionary work, churches, scripture) with \
no concrete sector mentioned: use 16 and set sdg_confidence to "low". If \
concrete activities are mentioned (mission schools, medical missions), \
classify by those activities instead.
- General "relief of poverty and advancement of education/health" \
boilerplate with nothing specific: pick the single goal best supported by \
any concrete detail; if there is none, use 1 with sdg_confidence "low".
- A "Friends of X" charity that raises money for a named institution \
abroad is funding a partner abroad, not uk_fundraising_only.
- uk_fundraising_only is for text that describes UK fundraising or \
awareness-raising with no indication of how (or whether) money or activity \
reaches other countries."""


def _example(name: str, activities: str, objects: str, output: str) -> list:
    """One worked example as a user/assistant message pair."""
    return [
        {"role": "user", "content": _charity_text(name, activities, objects)},
        {"role": "assistant", "content": output},
    ]


def _charity_text(name: str, activities: str, objects: str) -> str:
    """The variable input: identical formatting for examples and real rows."""
    return (
        f"Name: {name}\n"
        f"Activities: {activities if activities else '(none provided)'}\n"
        f"Objects: {objects if objects else '(none provided)'}"
    )


# Six worked examples covering the main archetypes: a clear direct operator,
# a grant-funder, a fundraising-only body, a sparse record, a dual-purpose
# charity, and a religious charity with concrete activities.
FEW_SHOTS = (
    _example(
        "Wells for Villages Trust",
        "We drill and maintain clean-water boreholes in rural Tanzania and "
        "train local technicians.",
        "The relief of poverty and advancement of health in East Africa.",
        '{"primary_sdg": 6, "primary_sdg_title": "Clean Water and Sanitation", '
        '"secondary_sdgs": [3, 1], "focus_summary": "Builds and maintains '
        'clean-water boreholes in rural Tanzania.", "sdg_confidence": "high", '
        '"overseas_engagement": "operates_directly_abroad", '
        '"engagement_confidence": "high"}',
    )
    + _example(
        "The Hazel Bridge Foundation",
        "We make grants to partner organisations working on girls' education "
        "in Kenya and Uganda, and monitor the projects we fund.",
        "The advancement of education of girls and young women in East Africa.",
        '{"primary_sdg": 4, "primary_sdg_title": "Quality Education", '
        '"secondary_sdgs": [5], "focus_summary": "Funds partner organisations '
        'providing girls\' education in Kenya and Uganda.", '
        '"sdg_confidence": "high", "overseas_engagement": '
        '"funds_partners_abroad", "engagement_confidence": "high"}',
    )
    + _example(
        "Hope for Syria Appeal",
        "We hold fundraising dinners, collections and sponsored walks across "
        "the Midlands to raise awareness and money for those suffering in "
        "Syria.",
        "The relief of poverty and sickness among victims of conflict.",
        '{"primary_sdg": 1, "primary_sdg_title": "No Poverty", '
        '"secondary_sdgs": [16], "focus_summary": "Raises funds in the UK for '
        'victims of the Syrian conflict.", "sdg_confidence": "medium", '
        '"overseas_engagement": "uk_fundraising_only", '
        '"engagement_confidence": "medium"}',
    )
    + _example(
        "The Radcliffe Overseas Trust",
        "",
        "The relief of poverty overseas.",
        '{"primary_sdg": 1, "primary_sdg_title": "No Poverty", '
        '"secondary_sdgs": [], "focus_summary": "Relieves poverty overseas; '
        'no detail on how it operates.", "sdg_confidence": "low", '
        '"overseas_engagement": "uk_fundraising_only", '
        '"engagement_confidence": "low"}',
    )
    + _example(
        "Kathmandu Health and Learning Trust",
        "We run a primary-care clinic and a primary school in Kathmandu, "
        "Nepal, employing local staff in both.",
        "The advancement of health and education in Nepal.",
        '{"primary_sdg": 3, "primary_sdg_title": "Good Health and '
        'Well-being", "secondary_sdgs": [4], "focus_summary": "Runs a clinic '
        'and a primary school in Kathmandu, Nepal.", "sdg_confidence": '
        '"medium", "overseas_engagement": "operates_directly_abroad", '
        '"engagement_confidence": "high"}',
    )
    + _example(
        "Lightbearers Global Mission",
        "We send and support missionaries in West Africa who plant churches "
        "and run mission primary schools.",
        "The advancement of the Christian religion worldwide.",
        '{"primary_sdg": 4, "primary_sdg_title": "Quality Education", '
        '"secondary_sdgs": [16], "focus_summary": "Supports missionaries '
        'running churches and mission schools in West Africa.", '
        '"sdg_confidence": "medium", "overseas_engagement": '
        '"operates_directly_abroad", "engagement_confidence": "high"}',
    )
)

# The system prompt is a list of blocks; the cache marker on the final block
# tells the API to cache everything up to and including it (system + the
# reference), so only the per-charity text is processed fresh each request.
SYSTEM_BLOCKS = [
    {"type": "text", "text": _SYSTEM_CORE},
    {
        "type": "text",
        "text": _SDG_REFERENCE,
        "cache_control": {"type": "ephemeral"},
    },
]

# JSON schema for the structured output. Constraints the structured-outputs
# dialect can't express (e.g. secondary must not repeat primary) are checked
# in parse_validate.py instead.
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_sdg": {"type": "integer", "enum": list(range(1, 18))},
        "primary_sdg_title": {"type": "string"},
        "secondary_sdgs": {
            "type": "array",
            "items": {"type": "integer", "enum": list(range(1, 18))},
            "maxItems": 2,
        },
        "focus_summary": {"type": "string"},
        "sdg_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "overseas_engagement": {
            "type": "string",
            "enum": [
                "operates_directly_abroad",
                "funds_partners_abroad",
                "uk_fundraising_only",
            ],
        },
        "engagement_confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
    },
    "required": [
        "primary_sdg",
        "primary_sdg_title",
        "secondary_sdgs",
        "focus_summary",
        "sdg_confidence",
        "overseas_engagement",
        "engagement_confidence",
    ],
    "additionalProperties": False,
}


def build_request_params(name, activities, objects, model=BULK_MODEL) -> dict:
    """Complete Messages-API params for classifying one charity."""

    def clean(value) -> str:
        # pandas gives NaN (a float) for empty CSV cells
        return "" if value is None or not isinstance(value, str) else value.strip()

    charity = _charity_text(
        clean(name), clean(activities), clean(objects)[:OBJECTS_CHAR_CAP]
    )
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_BLOCKS,
        "messages": FEW_SHOTS + [{"role": "user", "content": charity}],
        "output_config": {
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}
        },
    }
