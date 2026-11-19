"""Validate the approved G2 evaluation profile and observed runtime settings."""
import json
from pathlib import Path


def valid_settings(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.keys() == {"device", "depth", "docTokens"}
        and value["device"] in ("vulkan", "cpu")
        and type(value["depth"]) is int and 1 <= value["depth"] <= 64
        and type(value["docTokens"]) is int and 32 <= value["docTokens"] <= 1024
    )


def _profile_number(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() else value


def approved_settings() -> dict:
    profile = json.loads(
        Path(__file__).with_name("g2-reranker-profile.json").read_text(),
        parse_float=_profile_number,
    )
    if (not isinstance(profile, dict) or profile.keys() != {"version", "settings"}
            or type(profile["version"]) is not int or profile["version"] != 1
            or not valid_settings(profile["settings"])):
        raise ValueError("invalid G2 reranker profile")
    return profile["settings"]
