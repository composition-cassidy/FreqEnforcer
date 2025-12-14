from __future__ import annotations

import re
import sys
from pathlib import Path


class I18n:
    def __init__(self):
        self._language = "en"
        self._translations_by_lang: dict[str, dict[str, str]] = {}
        self._loaded = False

    def _resource_base_dir(self) -> Path:
        return Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent.parent)))

    def _translations_path(self) -> Path:
        return self._resource_base_dir() / "i18n" / "translations.txt"

    def load(self):
        if self._loaded:
            return

        self._loaded = True
        self._translations_by_lang = {"en": {}, "es": {}, "pt_BR": {}, "ja": {}, "ru": {}}

        path = self._translations_path()
        if not path.exists():
            return

        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            return

        line_re = re.compile(r"^([^=]+)=(.*)$")
        block_re = re.compile(r"\(([^:]+):([^)]*)\)")

        alias = {
            "en": "en",
            "english": "en",
            "es": "es",
            "spanish": "es",
            "pt": "pt_BR",
            "pt_br": "pt_BR",
            "pt-br": "pt_BR",
            "portuguese": "pt_BR",
            "portuguese (brazil)": "pt_BR",
            "portuguese (brasil)": "pt_BR",
            "ja": "ja",
            "japanese": "ja",
            "ru": "ru",
            "russian": "ru",
            "русский": "ru",
        }

        for line in raw.splitlines():
            ln = str(line).strip()
            if not ln:
                continue
            if ln.startswith("#") or ln.startswith(";"):
                continue

            m = line_re.match(ln)
            if not m:
                continue

            key = str(m.group(1)).strip()
            rest = str(m.group(2)).strip()
            if not key:
                continue

            for lang_raw, val in block_re.findall(rest):
                tag = str(lang_raw).strip().lower()
                lang = alias.get(tag)
                if not lang:
                    continue

                value = str(val)
                if value.startswith(" "):
                    value = value[1:]

                try:
                    value = value.replace("\\n", "\n").replace("\\t", "\t")
                except Exception:
                    pass

                self._translations_by_lang.setdefault(lang, {})[key] = value

    def set_language(self, code: str):
        self.load()
        c = str(code or "").strip()
        if c not in self._translations_by_lang:
            c = "en"
        self._language = c

    def language(self) -> str:
        return str(self._language)

    def tr(self, key: str, default: str | None = None) -> str:
        self.load()
        k = str(key)

        val = self._translations_by_lang.get(self._language, {}).get(k)
        if val is None or val == "":
            val = self._translations_by_lang.get("en", {}).get(k)

        if val is None or val == "":
            val = default if default is not None else k

        return str(val)


i18n = I18n()


def tr(key: str, default: str | None = None) -> str:
    return i18n.tr(key, default=default)
