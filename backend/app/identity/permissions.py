from types import MappingProxyType

ROLE_PERMISSIONS = MappingProxyType(
    {
        "admin": frozenset(
            {
                "institution.read",
                "memberships.manage",
                "audit.read",
                "questions.write",
                "questions.review",
                "exams.manage",
                "exams.invigilate",
                "scripts.mark",
                "results.publish",
            }
        ),
        "coordinator": frozenset({"institution.read", "exams.manage", "results.publish"}),
        "author": frozenset({"institution.read", "questions.write"}),
        "reviewer": frozenset({"institution.read", "questions.review"}),
        "invigilator": frozenset({"institution.read", "exams.invigilate"}),
        "examiner": frozenset({"institution.read", "scripts.mark"}),
        "candidate": frozenset({"institution.read", "exams.take", "results.self"}),
    }
)


def allowed(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
