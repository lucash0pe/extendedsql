from enum import Enum


class ParsingErrorType(Enum):
    SELECT_CLAUSE = "SELECT CLAUSE"
    OVER_CLAUSE = "OVER CLAUSE"
    WHERE_CLAUSE = "WHERE CLAUSE"
    SUCH_THAT_CLAUSE = "SUCH THAT CLAUSE"
    HAVING_CLAUSE = "HAVING CLAUSE"
    ORDER_BY_CLAUSE = "ORDER_BY_CLAUSE"

    CLAUSE_ORDER = "CLAUSE ORDER"
    MISSING_CLAUSE = "MISSING CLAUSE"


class ParsingError(Exception):
    """A query the parser rejected, with the piece of the query it rejected.

    `token` is the offending fragment — a column name, an aggregate, a whole condition — as it
    appears in the query being parsed. It is what an editor needs to point at the mistake rather
    than only naming the clause it fell in.

    It is a token and not a character offset on purpose: the parser runs on a query that
    `_prepare_query` has lowercased and whitespace-collapsed, so offsets into it do not map back
    onto what the user typed, while the token still matches (case-insensitively). Errors about
    the query as a whole carry no token.
    """

    def __init__(self, error_type: ParsingErrorType, message: str, token: str | None = None):
        self.error_type = error_type
        self.message = message
        self.token = token.strip() if token else None
        super().__init__(self.message)

    def __str__(self):
        return f"[{self.error_type.value}] {self.message}"
