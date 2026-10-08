"""Noncryptographic test codec; only for fixtures with fake credentials."""


class SyntheticProtector:
    def transform(self, data, encrypt):
        # Business-logic tests do not assert cryptographic properties or depend on
        # the agent's Windows logon. The production DPAPI provider is not modified.
        return data[::-1]
