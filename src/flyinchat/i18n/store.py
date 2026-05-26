from __future__ import annotations

from enum import StrEnum

from .en import EN
from .keys import TKey
from .zh import ZH


class Language(StrEnum):
    EN = "en"
    ZH = "zh"


_TRANSLATIONS: dict[Language, dict[TKey, str]] = {
    Language.EN: EN,
    Language.ZH: ZH,
}


class I18nStore:
    """Lightweight translation store with zero runtime file I/O."""

    def __init__(self, lang: Language = Language.EN) -> None:
        self._lang = lang
        self._dict = _TRANSLATIONS[lang]

    @property
    def language(self) -> Language:
        return self._lang

    def set_language(self, lang: Language) -> None:
        self._lang = lang
        self._dict = _TRANSLATIONS[lang]

    def t(self, key: TKey, **kwargs: object) -> str:
        template = self._dict.get(key)
        if template is None:
            return str(key)
        if not kwargs:
            return template
        return template.format(**{k: v for k, v in kwargs.items()})
