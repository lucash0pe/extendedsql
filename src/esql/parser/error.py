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
    def __init__(self, error_type: ParsingErrorType, message: str):
        self.error_type = error_type
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f"[{self.error_type.value}] {self.message}"
