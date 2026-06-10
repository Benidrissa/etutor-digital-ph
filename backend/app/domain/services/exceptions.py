"""Domain-service exceptions shared across content generators."""


class CourseNotIndexedError(ValueError):
    """Raised when a course has no indexed RAG chunks at all.

    Distinct from "no relevant content for this unit": this signals the course's
    reference materials were never indexed (or indexation produced zero chunks),
    so generation cannot proceed until an admin re-indexes the course.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers keep
    working as a safety net. Its ``str()`` is the stable sentinel
    ``"course_not_indexed"`` that the API and frontend match on.
    """

    SENTINEL = "course_not_indexed"

    def __init__(self, message: str = SENTINEL) -> None:
        super().__init__(message)
