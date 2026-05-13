from enum import Enum


class Group(str, Enum):
    """
    Keycloak groups recognised by this service.

    Keep values in sync with bi-dashboards-service/core/group.py so the two
    services agree on what an ADMIN looks like and on the spelling of any
    shared groups. The only group that strictly belongs to this service is
    ICP_FAMILY_TREE_DASHBOARD.
    """
    ADMIN = "ADMIN"
    ICP_FAMILY_TREE_DASHBOARD = "ICP-FAMILY-TREE-DASHBOARD"
