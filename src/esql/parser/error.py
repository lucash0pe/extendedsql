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
    # Not about a clause: a literal's delimiters are read before the query is split into clauses,
    # so there is no clause to name yet.
    STRING_LITERAL = "STRING LITERAL"
    # Not about the query at all: the *data* uses a name the language has taken. Raised when the
    # accessor is handed the frame, before any query exists, so it names a column rather than a
    # token. See `accessor._reject_reserved_columns`.
    RESERVED_COLUMN = "RESERVED COLUMN"
    # Also about the data rather than the query: a column label that is not a string, which the
    # language has no way to write. Same place and same reason as RESERVED_COLUMN, and separate from
    # it because the fix is different. See `accessor._reject_non_string_columns`.
    NON_STRING_COLUMN = "NON-STRING COLUMN"


class ParsingError(Exception):
    """A query the parser rejected, with the piece of the query it rejected.

    `token` is the offending fragment — a column name, an aggregate, a whole condition — as it
    appears in the query being parsed. It is what an editor needs to point at the mistake rather
    than only naming the clause it fell in.

    It is a token and not a character offset on purpose: the parser runs on a query that
    `_prepare_query` has whitespace-collapsed outside its string literals, so offsets into it do not
    map back onto what the user typed, while the token still matches literally. Errors about the
    query as a whole carry no token.

    Literally as of v1.9.0. `_prepare_query` used to lowercase the query as well, so a token came
    back lowered and a caller had to fold case to find it. That fold is what made a mixed-case
    DataFrame column unreachable (`.claude/status.md`, K1), and removing it means a token is now
    spelled exactly as the query spelled it.
    """

    def __init__(self, error_type: ParsingErrorType, message: str, token: str | None = None):
        self.error_type = error_type
        self.message = message
        self.token = token.strip() if token else None
        super().__init__(self.message)

    def __str__(self):
        return f"[{self.error_type.value}] {self.message}"
