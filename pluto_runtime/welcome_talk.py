"""Offline WELCOME_TALK v1 answer engine.

This module is intentionally small and deterministic. It does not call network
services, does not require API keys, and does not load an LLM. The goal is a
fast, traceable answer path for a welcoming robot.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any


WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class TalkConfig:
    version: str = "v1"
    primary_engine: str = "keyword"
    enable_ollama_fallback: bool = False
    max_input_words: int = 9
    max_output_words: int = 9
    fuzzy_threshold: float = 0.68
    unknown_response: str = "Ask me something simpler please."
    empty_response: str = "I did not hear you."
    long_input_response: str = "Short question please."


@dataclass(frozen=True)
class IntentRule:
    intent: str
    response: str
    triggers: tuple[str, ...]


@dataclass
class TalkResult:
    accepted: bool
    input_text: str
    normalized_text: str
    input_words: int
    response: str
    response_words: int
    response_source: str
    intent: str | None
    score: float
    latency_ms: float
    reason: str
    engine_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


INTENT_RULES: tuple[IntentRule, ...] = (
    IntentRule("greeting", "Hello. I am Pluto.", ("hi", "hello", "hey", "good morning", "good evening")),
    IntentRule("name", "I am Pluto.", ("your name", "who are you", "what are you", "pluto")),
    IntentRule("creator", "Abdelrahman and the team built me.", ("who made you", "who built you", "your creator", "made you")),
    IntentRule("feeling", "I feel ready to meet people.", ("how are you", "how do you feel", "are you okay")),
    IntentRule("age", "I am still very new.", ("how old", "your age", "when born")),
    IntentRule("dance", "Choose dance from the website.", ("dance", "can you dance", "moonwalk", "music")),
    IntentRule("purpose", "I welcome people and answer simply.", ("what do you do", "your job", "your purpose", "why are you here")),
    IntentRule("help", "Ask me short simple questions.", ("help", "what can i ask", "how talk")),
    IntentRule("robot", "Yes, but I try warmly.", ("are you robot", "robot", "machine")),
    IntentRule("thanks", "You are welcome.", ("thanks", "thank you")),
    IntentRule("goodbye", "Goodbye. Come back soon.", ("bye", "goodbye", "see you")),
)


class WelcomeTalkEngine:
    """Deterministic offline answer selector for WELCOME_TALK v1."""

    def __init__(self, config: TalkConfig | None = None) -> None:
        self.config = config or TalkConfig()
        self._validate_response_bank()

    def answer(self, text: str) -> TalkResult:
        started = time.monotonic()
        raw = str(text or "").strip()
        normalized = normalize_text(raw)
        words = normalized.split() if normalized else []

        if not words:
            return self._result(
                started,
                accepted=False,
                raw=raw,
                normalized=normalized,
                input_words=0,
                response=self.config.empty_response,
                source="blocked",
                intent=None,
                score=0.0,
                reason="empty_input",
            )

        if len(words) > self.config.max_input_words:
            return self._result(
                started,
                accepted=False,
                raw=raw,
                normalized=normalized,
                input_words=len(words),
                response=self.config.long_input_response,
                source="blocked",
                intent=None,
                score=0.0,
                reason="input_too_long",
            )

        intent, response, score, source = self._match(normalized, words)
        if intent is None:
            response = self.config.unknown_response
            source = "fallback"
            reason = "no_intent_match"
        else:
            reason = "matched_intent"

        return self._result(
            started,
            accepted=True,
            raw=raw,
            normalized=normalized,
            input_words=len(words),
            response=response,
            source=source,
            intent=intent,
            score=score,
            reason=reason,
        )

    def status(self) -> dict[str, Any]:
        return {
            "version": self.config.version,
            "primary_engine": self.config.primary_engine,
            "ollama_fallback_enabled": self.config.enable_ollama_fallback,
            "max_input_words": self.config.max_input_words,
            "max_output_words": self.config.max_output_words,
            "intent_count": len(INTENT_RULES),
        }

    def _match(self, normalized: str, words: list[str]) -> tuple[str | None, str, float, str]:
        input_tokens = set(words)
        best: tuple[str | None, str, float, str] = (None, self.config.unknown_response, 0.0, "fallback")

        for rule in INTENT_RULES:
            for trigger in rule.triggers:
                trigger_norm = normalize_text(trigger)
                trigger_tokens = set(trigger_norm.split())
                if not trigger_tokens:
                    continue
                if trigger_norm in normalized or trigger_tokens.issubset(input_tokens):
                    return rule.intent, rule.response, 1.0, "keyword"

                ratio = SequenceMatcher(None, normalized, trigger_norm).ratio()
                overlap = len(input_tokens & trigger_tokens) / max(len(trigger_tokens), 1)
                score = max(ratio, overlap * 0.85)
                if score > best[2]:
                    best = (rule.intent, rule.response, score, "fuzzy")

        if best[2] >= self.config.fuzzy_threshold:
            return best
        return None, self.config.unknown_response, best[2], "fallback"

    def _result(
        self,
        started: float,
        accepted: bool,
        raw: str,
        normalized: str,
        input_words: int,
        response: str,
        source: str,
        intent: str | None,
        score: float,
        reason: str,
    ) -> TalkResult:
        safe_response = enforce_word_limit(response, self.config.max_output_words)
        return TalkResult(
            accepted=accepted,
            input_text=raw,
            normalized_text=normalized,
            input_words=input_words,
            response=safe_response,
            response_words=count_words(safe_response),
            response_source=source,
            intent=intent,
            score=round(score, 3),
            latency_ms=(time.monotonic() - started) * 1000.0,
            reason=reason,
            engine_version=self.config.version,
        )

    def _validate_response_bank(self) -> None:
        responses = [rule.response for rule in INTENT_RULES]
        responses.extend(
            [
                self.config.unknown_response,
                self.config.empty_response,
                self.config.long_input_response,
            ]
        )
        too_long = [text for text in responses if count_words(text) > self.config.max_output_words]
        if too_long:
            raise ValueError(f"WELCOME_TALK responses exceed word limit: {too_long}")


def normalize_text(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def count_words(text: str) -> int:
    normalized = normalize_text(text)
    return len(normalized.split()) if normalized else 0


def enforce_word_limit(text: str, max_words: int) -> str:
    words = WORD_RE.findall(text)
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()
