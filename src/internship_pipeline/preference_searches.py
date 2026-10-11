"""Build broad discovery queries from saved preferences, without inferring candidate facts."""

from itertools import product

from jobspy.model import Country

from internship_pipeline.profile_settings import Preferences
from internship_pipeline.search_runs import SourceConfig


def preference_searches(preferences: Preferences) -> list[SourceConfig]:
    roles = list(dict.fromkeys(role.strip() for role in preferences.soft.roles)) or [""]
    countries = list(dict.fromkeys(preferences.hard.countries)) or [""]
    locations = list(dict.fromkeys(preferences.hard.locations or preferences.soft.locations)) or [
        ""
    ]
    if len(roles) * len(countries) * len(locations) > 100:
        raise ValueError(
            "Choose fewer roles or locations to keep your first search under 100 queries."
        )

    configs = []
    for role, country, location in product(roles, countries, locations):
        region = next(
            (
                item
                for item in Country
                if item not in {Country.WORLDWIDE, Country.US_CANADA}
                and (
                    country.lower() in item.value[0].split(",")
                    or country.upper() == item.value[1].split(":")[-1].upper()
                )
            ),
            None,
        )
        term = f"{role} internship".strip()
        if len(term) > 200:
            raise ValueError(
                "Shorten preferred roles to 189 characters so internship searches fit."
            )
        # Worldwide and unsupported regional boards use LinkedIn's location search.
        # Never silently turn an unrestricted search into a US-only search.
        search_location = location if region else ", ".join(filter(None, (location, country)))
        if len(search_location) > 200:
            raise ValueError(
                "Shorten locations so each search location fits within 200 characters."
            )
        configs.append(
            SourceConfig(
                name=" · ".join(filter(None, (term, location, country)))[:120],
                source="jobspy",
                search_term=term,
                location=search_location,
                country=region.value[0].split(",")[0] if region else "worldwide",
                sites=["indeed"] if region else ["linkedin"],
            )
        )
    return configs
